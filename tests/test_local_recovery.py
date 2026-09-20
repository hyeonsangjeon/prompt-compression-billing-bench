import base64
from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

from src.local_recovery import (
    AuditWriter,
    BridgeBindings,
    BridgeFailure,
    CapabilityStore,
    LocalRecoveryBridge,
    NonceStore,
    PeerCredentials,
    bind_local_server,
    close_local_server,
    execute_runtime_cleanup,
    load_bridge_policy,
    plan_runtime_cleanup,
    serve_connection,
)
from src.squeez_recovery import (
    Fingerprint,
    ProcessObservation,
    RecoveryAdapter,
    RecoveryPolicy,
    RecoveryRegistry,
    SupplierEnvelope,
    TrustedContext,
    digest,
)


ROOT = Path(__file__).resolve().parents[1]


class FakeSupplier:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls = 0

    def recover(self, record) -> SupplierEnvelope:
        self.calls += 1
        empty = Fingerprint(0, digest(b""))
        observed = ProcessObservation(None, 0, False, True, 0.001, empty, empty)
        return SupplierEnvelope("recovered", self.payload, observed)


class LocalRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.ipc = self.root / "ipc"
        self.capabilities = self.root / "capabilities"
        self.nonces = self.root / "nonces"
        for directory in (self.ipc, self.capabilities, self.nonces):
            directory.mkdir(mode=0o700)
        self.payload = "software-controlled recovery 한글\n".encode("utf-8")
        self.handle = "recover-" + "a" * 32
        self.bindings = BridgeBindings(
            caller_id="controlled-caller",
            run_id="controlled-run-v1",
            trial_id="controlled-trial-v1",
            handle=self.handle,
            ownership_epoch="controlled-epoch-v1",
            original_bytes=len(self.payload),
        )
        self.trusted = TrustedContext(
            caller_id=self.bindings.caller_id,
            run_id=self.bindings.run_id,
            trial_id=self.bindings.trial_id,
            ownership_epoch=self.bindings.ownership_epoch,
            authority="trusted_harness",
            permissions=frozenset({"recovery:read"}),
        )
        self.recovery_policy = RecoveryPolicy(
            scope="local_software_control_not_operational",
            enabled=True,
            external_agent_or_mcp_enabled=False,
            multi_user_authentication_implemented=False,
            required_permission="recovery:read",
            ttl_seconds=300,
            retention_seconds=600,
            max_response_bytes=65536,
            max_total_bytes_per_handle=65536,
            max_calls_per_handle=4,
            max_supplier_calls_per_trial=4,
            max_recovered_bytes_per_trial=131072,
            supplier_timeout_seconds=10.0,
            supplier_stdout_limit_bytes=262144,
            supplier_stderr_limit_bytes=65536,
        )
        self.bridge_policy = load_bridge_policy(ROOT / "ledgers/recovery.template.toml")
        self.now = [1000.0]

    def make_bridge(self, *, audit=None):
        supplier = FakeSupplier(self.payload)
        registry = RecoveryRegistry()
        registry.issue_candidate(
            context=self.trusted,
            handle=self.handle,
            supplier_key="b" * 32,
            original=self.payload,
            input_sha256=digest(b"input"),
            candidate=True,
            provenance="fresh_candidate",
            compressor="squeez",
            created_at=1000.0,
        )
        adapter = RecoveryAdapter(
            policy=self.recovery_policy,
            registry=registry,
            supplier=supplier,
            clock=lambda: self.now[0],
        )
        bridge = LocalRecoveryBridge(
            expected_uid=os.geteuid(),
            policy=self.bridge_policy,
            bindings=self.bindings,
            trusted_context=self.trusted,
            capabilities=CapabilityStore(self.capabilities, os.geteuid(), self.bridge_policy),
            nonces=NonceStore(self.nonces, os.geteuid()),
            adapter=adapter,
            audit=audit,
            clock=lambda: self.now[0],
        )
        return bridge, supplier

    def issue(self, bridge, peer, label="valid-cap"):
        return bridge.handle(
            peer,
            {
                "action": "issue",
                "label": label,
                "caller_id": self.bindings.caller_id,
                "claimed_pid": peer.pid,
                "run_id": self.bindings.run_id,
                "trial_id": self.bindings.trial_id,
                "handle": self.bindings.handle,
                "ownership_epoch": self.bindings.ownership_epoch,
            },
        )

    def token(self, label="valid-cap"):
        return json.loads((self.capabilities / f"{label}.json").read_text(encoding="utf-8"))["token"]

    def recover(self, bridge, peer, token, nonce="1" * 32, **changes):
        request = {
            "action": "recover",
            "label": "valid-cap",
            "token": token,
            "nonce": nonce,
            "caller_id": self.bindings.caller_id,
            "run_id": self.bindings.run_id,
            "trial_id": self.bindings.trial_id,
            "handle": self.bindings.handle,
            "ownership_epoch": self.bindings.ownership_epoch,
        }
        request.update(changes)
        return bridge.handle(peer, request)

    def test_capability_is_bound_owner_only_and_not_returned(self):
        bridge, supplier = self.make_bridge()
        peer = PeerCredentials(os.getpid(), os.geteuid(), os.getegid())
        response = self.issue(bridge, peer)
        document = json.loads((self.capabilities / "valid-cap.json").read_text(encoding="utf-8"))
        self.assertTrue(response["ok"])
        self.assertEqual((self.capabilities / "valid-cap.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(document["peer_pid"], peer.pid)
        self.assertNotIn(document["token"], json.dumps(response))
        self.assertEqual(supplier.calls, 0)

    def test_authentication_binding_and_expiry_reject_before_supplier(self):
        peer = PeerCredentials(os.getpid(), os.geteuid(), os.getegid())
        cases = (
            ("invalid", {}, "invalid_capability"),
            (None, {"run_id": "other-run"}, "run_mismatch"),
            (None, {"trial_id": "other-trial"}, "trial_mismatch"),
            (None, {"handle": "recover-" + "f" * 32}, "handle_mismatch"),
            (None, {"ownership_epoch": "other-epoch"}, "ownership_epoch_mismatch"),
        )
        for index, (explicit_token, changes, expected) in enumerate(cases):
            case_root = self.root / f"case-{index}"
            self.capabilities = case_root / "capabilities"
            self.nonces = case_root / "nonces"
            self.capabilities.mkdir(parents=True, mode=0o700)
            self.nonces.mkdir(mode=0o700)
            bridge, supplier = self.make_bridge()
            self.issue(bridge, peer)
            token = explicit_token or self.token()
            response = self.recover(bridge, peer, token, **changes)
            with self.subTest(expected=expected):
                self.assertEqual(response["error"], expected)
                self.assertEqual(supplier.calls, 0)
        self.capabilities = self.root / "expired-capabilities"
        self.nonces = self.root / "expired-nonces"
        self.capabilities.mkdir(mode=0o700)
        self.nonces.mkdir(mode=0o700)
        bridge, supplier = self.make_bridge()
        self.issue(bridge, peer)
        token = self.token()
        self.now[0] += self.bridge_policy.capability_ttl_seconds
        response = self.recover(bridge, peer, token)
        self.assertEqual(response["error"], "capability_expired")
        self.assertEqual(supplier.calls, 0)

    def test_peer_uid_pid_and_byte_quota_reject_before_supplier(self):
        bridge, supplier = self.make_bridge()
        peer = PeerCredentials(os.getpid(), os.geteuid(), os.getegid())
        different_uid = PeerCredentials(peer.pid, peer.uid + 1, peer.gid)
        denied_issue = self.issue(bridge, different_uid, "different-uid")
        self.assertEqual(denied_issue["error"], "peer_uid_mismatch")
        self.issue(bridge, peer)
        token = self.token()
        different_pid = PeerCredentials(peer.pid + 1, peer.uid, peer.gid)
        denied_recovery = self.recover(bridge, different_pid, token)
        self.assertEqual(denied_recovery["error"], "peer_pid_mismatch")
        self.assertEqual(supplier.calls, 0)

        self.capabilities = self.root / "byte-capabilities"
        self.nonces = self.root / "byte-nonces"
        self.capabilities.mkdir(mode=0o700)
        self.nonces.mkdir(mode=0o700)
        self.bridge_policy = replace(
            self.bridge_policy,
            capability_max_recovered_bytes=len(self.payload) - 1,
        )
        bridge, supplier = self.make_bridge()
        self.issue(bridge, peer)
        denied_bytes = self.recover(bridge, peer, self.token())
        self.assertEqual(denied_bytes["error"], "capability_byte_quota_reached")
        self.assertEqual(supplier.calls, 0)

    def test_replay_and_quota_do_not_start_another_supplier(self):
        bridge, supplier = self.make_bridge()
        peer = PeerCredentials(os.getpid(), os.geteuid(), os.getegid())
        self.issue(bridge, peer)
        token = self.token()
        first = self.recover(bridge, peer, token, "2" * 32)
        replay = self.recover(bridge, peer, token, "2" * 32)
        quota = self.recover(bridge, peer, token, "3" * 32)
        self.assertEqual(base64.b64decode(first["content_base64"]), self.payload)
        self.assertEqual(replay["error"], "request_replay")
        self.assertEqual(quota["error"], "capability_supplier_quota_reached")
        self.assertEqual(supplier.calls, 1)

    def test_nonce_and_capability_collisions_preserve_existing_bytes(self):
        bridge, supplier = self.make_bridge()
        peer = PeerCredentials(os.getpid(), os.geteuid(), os.getegid())
        self.issue(bridge, peer)
        capability_path = self.capabilities / "valid-cap.json"
        original_capability = capability_path.read_bytes()
        duplicate = self.issue(bridge, peer)
        self.assertFalse(duplicate["ok"])
        self.assertEqual(capability_path.read_bytes(), original_capability)
        nonce = "4" * 32
        nonce_path = self.nonces / f"valid-cap-{digest(nonce.encode('ascii'))}.used"
        nonce_path.write_bytes(b"sentinel")
        os.chmod(nonce_path, 0o600)
        response = self.recover(bridge, peer, self.token(), nonce)
        self.assertEqual(response["error"], "request_replay")
        self.assertEqual(nonce_path.read_bytes(), b"sentinel")
        self.assertEqual(supplier.calls, 0)

    @unittest.skipUnless(hasattr(__import__("socket"), "SO_PEERCRED"), "Linux SO_PEERCRED is required")
    def test_separate_client_process_uses_unix_peer_credentials(self):
        audit_path = self.root / "audit.jsonl"
        audit = AuditWriter.reserve(audit_path)
        bridge, supplier = self.make_bridge(audit=audit)
        socket_path = self.ipc / "recovery.sock"
        server, identity = bind_local_server(socket_path, self.root)
        responses = []
        errors = []

        def serve():
            try:
                for _index in range(2):
                    responses.append(serve_connection(server, socket_path, identity, self.root, bridge))
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=serve)
        thread.start()
        script = r'''
import json, os, pathlib, socket, sys

socket_path, capability_path, caller_id, run_id, trial_id, handle, epoch = sys.argv[1:]

def request(payload):
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.connect(socket_path)
    connection.sendall((json.dumps(payload, separators=(",", ":")) + "\n").encode())
    connection.shutdown(socket.SHUT_WR)
    data = b""
    while not data.endswith(b"\n"):
        data += connection.recv(4096)
    connection.close()
    return json.loads(data)

issued = request({
    "action": "issue", "label": "process-cap", "caller_id": caller_id,
    "claimed_pid": os.getpid(), "run_id": run_id, "trial_id": trial_id,
    "handle": handle, "ownership_epoch": epoch,
})
token = json.loads(pathlib.Path(capability_path).read_text())["token"]
recovered = request({
    "action": "recover", "label": "process-cap", "token": token,
    "nonce": "5" * 32, "caller_id": caller_id, "run_id": run_id,
    "trial_id": trial_id, "handle": handle, "ownership_epoch": epoch,
})
print(json.dumps({"pid": os.getpid(), "issued": issued, "recovered": recovered}))
'''
        process = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                script,
                str(socket_path),
                str(self.capabilities / "process-cap.json"),
                self.bindings.caller_id,
                self.bindings.run_id,
                self.bindings.trial_id,
                self.bindings.handle,
                self.bindings.ownership_epoch,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            check=False,
        )
        thread.join(timeout=5)
        close_local_server(server, socket_path, identity, self.root)
        audit.close()
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertTrue(result["issued"]["ok"])
        self.assertEqual(base64.b64decode(result["recovered"]["content_base64"]), self.payload)
        self.assertEqual(bridge.capabilities.records["process-cap"].peer_pid, result["pid"])
        self.assertEqual(supplier.calls, 1)
        token = json.loads((self.capabilities / "process-cap.json").read_text(encoding="utf-8"))["token"]
        self.assertNotIn(token.encode("ascii"), audit_path.read_bytes())
        self.assertEqual(len(responses), 2)

    def test_socket_collision_does_not_follow_symlink(self):
        sentinel = self.root / "sentinel"
        sentinel.write_bytes(b"preserve")
        socket_path = self.ipc / "recovery.sock"
        socket_path.symlink_to(sentinel)
        with self.assertRaises(BridgeFailure):
            bind_local_server(socket_path, self.root)
        self.assertEqual(sentinel.read_bytes(), b"preserve")

    def test_runtime_cleanup_removes_only_the_complete_allowlist(self):
        runtime = self.root / "private-runtime"
        ipc = runtime / "ipc"
        capabilities = runtime / "capabilities"
        nonces = runtime / "nonces"
        for directory in (runtime, ipc, capabilities, nonces):
            directory.mkdir(mode=0o700)
        capability = capabilities / "capability.json"
        nonce = nonces / "nonce.used"
        capability.write_bytes(b"secret")
        nonce.write_bytes(b"used")
        os.chmod(capability, 0o600)
        os.chmod(nonce, 0o600)
        socket_path = ipc / "bridge.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(socket_path))
        os.chmod(socket_path, 0o600)
        server.close()
        allowed = {
            "ipc",
            "ipc/bridge.sock",
            "capabilities",
            "capabilities/capability.json",
            "nonces",
            "nonces/nonce.used",
        }
        plan = plan_runtime_cleanup(runtime, allowed, os.geteuid())
        execute_runtime_cleanup(plan)
        self.assertEqual(list(runtime.iterdir()), [])

        unsafe = self.root / "unsafe-runtime"
        unsafe.mkdir(mode=0o700)
        expected = unsafe / "expected"
        unexpected = unsafe / "unexpected"
        expected.write_bytes(b"expected")
        unexpected.write_bytes(b"unexpected")
        with self.assertRaisesRegex(BridgeFailure, "cleanup_tree_allowlist_mismatch"):
            plan_runtime_cleanup(unsafe, {"expected"}, os.geteuid())
        self.assertEqual(expected.read_bytes(), b"expected")
        self.assertEqual(unexpected.read_bytes(), b"unexpected")

    def test_runtime_cleanup_refuses_links_and_root_drift(self):
        symlink_root = self.root / "symlink-runtime"
        symlink_root.mkdir(mode=0o700)
        target = self.root / "symlink-target"
        target.write_bytes(b"preserve")
        (symlink_root / "link").symlink_to(target)
        with self.assertRaisesRegex(BridgeFailure, "cleanup_symlink_refused"):
            plan_runtime_cleanup(symlink_root, {"link"}, os.geteuid())
        self.assertEqual(target.read_bytes(), b"preserve")

        hardlink_root = self.root / "hardlink-runtime"
        hardlink_root.mkdir(mode=0o700)
        first = hardlink_root / "first"
        second = hardlink_root / "second"
        first.write_bytes(b"preserve")
        os.chmod(first, 0o600)
        os.link(first, second)
        with self.assertRaisesRegex(BridgeFailure, "cleanup_regular_link_count_invalid"):
            plan_runtime_cleanup(hardlink_root, {"first", "second"}, os.geteuid())
        self.assertEqual(first.read_bytes(), b"preserve")
        self.assertEqual(second.read_bytes(), b"preserve")

        drift_root = self.root / "drift-runtime"
        drift_root.mkdir(mode=0o700)
        state = drift_root / "state"
        state.write_bytes(b"preserve")
        os.chmod(state, 0o600)
        plan = plan_runtime_cleanup(drift_root, {"state"}, os.geteuid())
        os.chmod(drift_root, 0o750)
        with self.assertRaisesRegex(BridgeFailure, "cleanup_root_identity_changed"):
            execute_runtime_cleanup(plan)
        self.assertEqual(state.read_bytes(), b"preserve")


if __name__ == "__main__":
    unittest.main()
