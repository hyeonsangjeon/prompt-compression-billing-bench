from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest

from src.squeez_recovery import (
    Fingerprint,
    ProcessObservation,
    RecoveryAdapter,
    RecoveryFailure,
    RecoveryPolicy,
    RecoveryRegistry,
    RunLayout,
    SqueezMcpSupplier,
    SupplierEnvelope,
    TrustedContext,
    digest,
    execute_vendor_cleanup,
    fingerprint_file,
    load_recovery_policy,
    load_supplier_spec,
    make_squeez_mcp_supplier,
    plan_vendor_cleanup,
)


ROOT = Path(__file__).resolve().parents[1]


def policy(**changes) -> RecoveryPolicy:
    baseline = RecoveryPolicy(
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
    return replace(baseline, **changes)


def context(**changes) -> TrustedContext:
    baseline = {
        "caller_id": "controlled-caller",
        "run_id": "controlled-run-v1",
        "trial_id": "controlled-trial-v1",
        "ownership_epoch": "controlled-epoch-v1",
        "authority": "trusted_harness",
        "permissions": frozenset({"recovery:read"}),
    }
    baseline.update(changes)
    return TrustedContext(**baseline)


def observation(exit_code=0) -> ProcessObservation:
    empty = Fingerprint(0, digest(b""))
    return ProcessObservation(None, exit_code, False, True, 0.001, empty, empty)


class FakeSupplier:
    def __init__(self, outcome: str, content: bytes | None) -> None:
        self.outcome = outcome
        self.content = content
        self.calls = 0

    def recover(self, record) -> SupplierEnvelope:
        self.calls += 1
        return SupplierEnvelope(self.outcome, self.content, observation())


def adapter_for(content: bytes, supplier: FakeSupplier, *, selected_policy=None, selected_context=None):
    trusted = selected_context or context()
    registry = RecoveryRegistry()
    record = registry.issue_candidate(
        context=trusted,
        handle="recover-" + "a" * 32,
        supplier_key="b" * 32,
        original=content,
        input_sha256=digest(b"input"),
        candidate=True,
        provenance="fresh_candidate",
        compressor="squeez",
        created_at=1000.0,
    )
    adapter = RecoveryAdapter(
        policy=selected_policy or policy(),
        registry=registry,
        supplier=supplier,
        clock=lambda: 1001.0,
    )
    return adapter, trusted, registry, record


class RecoveryContractTests(unittest.TestCase):
    def test_public_template_is_disabled_and_pins_the_reviewed_supplier(self):
        path = ROOT / "ledgers/recovery.template.toml"
        loaded = load_recovery_policy(path)
        supplier = load_supplier_spec(path)
        document = path.read_text(encoding="utf-8")
        self.assertFalse(loaded.enabled)
        self.assertFalse(loaded.external_agent_or_mcp_enabled)
        self.assertEqual(
            supplier.fingerprint,
            Fingerprint(
                2056992,
                "ef956365ace3aa5f362847afc000aa008d5b4a26db4ee2c5bcc0d2718d043773",
            ),
        )
        self.assertIn('version = "1.48.4"', document)
        self.assertIn('sha256 = "ef956365ace3aa5f362847afc000aa008d5b4a26db4ee2c5bcc0d2718d043773"', document)
        with tempfile.TemporaryDirectory() as temporary:
            layout = RunLayout.create(Path(temporary).resolve(), "disabled-run")
            with self.assertRaisesRegex(RecoveryFailure, "recovery_ledger_disabled"):
                make_squeez_mcp_supplier(path, layout, {})

    def test_only_fresh_squeez_candidates_receive_handles(self):
        original = b"candidate"
        for changes in (
            {"candidate": False},
            {"provenance": "recovered_original"},
            {"compressor": "none"},
        ):
            arguments = {
                "context": context(),
                "handle": "recover-" + "c" * 32,
                "supplier_key": "d" * 32,
                "original": original,
                "input_sha256": digest(b"input"),
                "candidate": True,
                "provenance": "fresh_candidate",
                "compressor": "squeez",
                "created_at": 1000.0,
            }
            arguments.update(changes)
            with self.subTest(changes=changes), self.assertRaises(RecoveryFailure):
                RecoveryRegistry().issue_candidate(**arguments)

    def test_recovery_requires_exact_source_bytes_and_distinguishes_not_found(self):
        original = "source 한글\n".encode("utf-8")
        success_supplier = FakeSupplier("recovered", original)
        adapter, trusted, _registry, _record = adapter_for(original, success_supplier)
        success = adapter.recover(context=trusted, request={"handle": "recover-" + "a" * 32})
        self.assertEqual(success.status, "full")
        self.assertEqual(success.content, original)
        self.assertEqual(success.original, Fingerprint(len(original), digest(original)))

        missing_supplier = FakeSupplier("not_found", None)
        missing_adapter, trusted, _registry, _record = adapter_for(original, missing_supplier)
        missing = missing_adapter.recover(context=trusted, request={"handle": "recover-" + "a" * 32})
        self.assertEqual(missing.public_error, "not_available")
        self.assertEqual(missing.private_reason, "supplier_not_found")
        self.assertTrue(missing.supplier_invoked)

        changed_supplier = FakeSupplier("recovered", original + b"changed")
        changed_adapter, trusted, _registry, _record = adapter_for(original, changed_supplier)
        changed = changed_adapter.recover(context=trusted, request={"handle": "recover-" + "a" * 32})
        self.assertEqual(changed.public_error, "integrity_failure")
        self.assertEqual(changed.private_reason, "supplier_content_fingerprint_mismatch")

    def test_identity_lifetime_and_permission_fail_before_supplier(self):
        original = b"source"
        cases = (
            (context(permissions=frozenset()), 1001.0, None, "permission_denied"),
            (context(run_id="other-run"), 1001.0, None, "run_mismatch"),
            (context(trial_id="other-trial"), 1001.0, None, "trial_mismatch"),
            (context(ownership_epoch="other-epoch"), 1001.0, None, "restart_ownership_unverified"),
            (context(), 1300.0, None, "handle_expired"),
            (context(), 1600.0, None, "source_retention_expired"),
            (context(), 1001.0, "revoked", "handle_revoked"),
        )
        for supplied_context, now, state, expected in cases:
            supplier = FakeSupplier("recovered", original)
            adapter, trusted, _registry, record = adapter_for(original, supplier)
            adapter.clock = lambda now=now: now
            if state is not None:
                record.state = state
            decision = adapter.recover(
                context=supplied_context,
                request={"handle": "recover-" + "a" * 32},
            )
            with self.subTest(expected=expected):
                self.assertEqual(decision.private_reason, expected)
                self.assertFalse(decision.supplier_invoked)
                self.assertEqual(supplier.calls, 0)

    def test_utf8_chunks_use_bound_cursors_and_trial_quota(self):
        original = "ab한글cd".encode("utf-8")
        selected_policy = policy(
            max_response_bytes=5,
            max_total_bytes_per_handle=64,
            max_calls_per_handle=4,
            max_supplier_calls_per_trial=4,
            max_recovered_bytes_per_trial=64,
        )
        supplier = FakeSupplier("recovered", original)
        adapter, trusted, _registry, _record = adapter_for(original, supplier, selected_policy=selected_policy)
        decisions = []
        request = {"handle": "recover-" + "a" * 32}
        while True:
            decision = adapter.recover(context=trusted, request=request)
            decisions.append(decision)
            if decision.complete:
                break
            request = {"handle": "recover-" + "a" * 32, "cursor": decision.next_cursor}
        first = decisions[0]
        self.assertEqual(first.content.decode("utf-8"), "ab한")
        self.assertFalse(first.complete)
        self.assertEqual(b"".join(item.content for item in decisions), original)
        self.assertTrue(decisions[-1].complete)
        self.assertEqual(supplier.calls, len(decisions))


class RecoveryLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.task_root = Path(self.temporary.name).resolve()
        self.binary = self.task_root / "synthetic-squeez"
        self.binary.write_text(
            "#!/usr/bin/python3\n"
            "import json, os, pathlib, sys\n"
            "assert sys.argv[1:] == ['mcp']\n"
            "messages = [json.loads(line) for line in sys.stdin if line.strip()]\n"
            "key = messages[-1]['params']['arguments']['key']\n"
            "path = pathlib.Path(os.environ['HOME']) / '.claude/squeez/blobs' / key\n"
            "if path.is_file():\n"
            "    text = path.read_text(encoding='utf-8')\n"
            "else:\n"
            "    text = f\"squeez_retrieve: no stored output for key '{key}'. "
            "It may be malformed, expired (past retrieve_ttl_days), or never stored.\"\n"
            "print(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': {}}))\n"
            "print(json.dumps({'jsonrpc': '2.0', 'id': 2, "
            "'result': {'content': [{'type': 'text', 'text': text}]}}))\n",
            encoding="utf-8",
        )
        self.binary.chmod(0o700)
        self.expected_binary = fingerprint_file(self.binary)

    def make_supplier(self, layout: RunLayout) -> SqueezMcpSupplier:
        return SqueezMcpSupplier(
            binary=self.binary,
            expected_binary=self.expected_binary,
            layout=layout,
            timeout_seconds=2.0,
            stdout_limit_bytes=131072,
            stderr_limit_bytes=65536,
        )

    @staticmethod
    def populate(layout: RunLayout, key: str, payload: bytes) -> None:
        layout.vendor_blobs.mkdir(parents=True, mode=0o700)
        (layout.vendor_blobs / key).write_bytes(payload)
        (layout.vendor_blobs / f"{key}.idx").write_bytes(b"index")
        (layout.vendor_store / "session.json").write_text("{}\n", encoding="utf-8")

    def adapter(self, layout: RunLayout, supplier: SqueezMcpSupplier, payload: bytes, key: str):
        trusted = context(run_id=layout.run_id)
        registry = RecoveryRegistry()
        record = registry.issue_candidate(
            context=trusted,
            handle="recover-" + "e" * 32,
            supplier_key=key,
            original=payload,
            input_sha256=digest(b"input"),
            candidate=True,
            provenance="fresh_candidate",
            compressor="squeez",
            created_at=1000.0,
        )
        adapter = RecoveryAdapter(
            policy=policy(),
            registry=registry,
            supplier=supplier,
            clock=lambda: 1001.0,
        )
        return adapter, trusted, record

    def test_run_stores_are_isolated_and_exact_cleanup_makes_fresh_process_not_found(self):
        payload = "isolated synthetic 원문\n".encode("utf-8")
        key = "f" * 32
        primary = RunLayout.create(self.task_root, "primary-run")
        control = RunLayout.create(self.task_root, "control-run")
        self.populate(primary, key, payload)
        self.populate(control, key, payload)
        control_before = {
            path.relative_to(control.root).as_posix(): fingerprint_file(path)
            for path in sorted(control.root.rglob("*"))
            if path.is_file()
        }

        supplier = self.make_supplier(primary)
        adapter, trusted, _record = self.adapter(primary, supplier, payload, key)
        decision = adapter.recover(context=trusted, request={"handle": "recover-" + "e" * 32})
        self.assertEqual(decision.content, payload)
        self.assertTrue(supplier.observations[-1].waited)
        supplier.assert_idle()

        cleanup = plan_vendor_cleanup(primary, key, supplier)
        removed = execute_vendor_cleanup(cleanup, supplier)
        self.assertEqual({item.name for item in removed}, {key, f"{key}.idx"})
        self.assertEqual(list(primary.vendor_blobs.iterdir()), [])
        self.assertTrue((primary.vendor_store / "session.json").is_file())

        fresh_supplier = self.make_supplier(primary)
        fresh_adapter, fresh_context, _record = self.adapter(primary, fresh_supplier, payload, key)
        missing = fresh_adapter.recover(
            context=fresh_context,
            request={"handle": "recover-" + "e" * 32},
        )
        self.assertEqual(fresh_supplier.observations[-1].exit_code, 0)
        self.assertEqual(missing.private_reason, "supplier_not_found")
        self.assertIsNone(missing.content)

        control_after = {
            path.relative_to(control.root).as_posix(): fingerprint_file(path)
            for path in sorted(control.root.rglob("*"))
            if path.is_file()
        }
        self.assertEqual(control_after, control_before)

    def test_cleanup_refuses_unexpected_symlink_and_hardlink_entries(self):
        key = "1" * 32
        for kind in ("unexpected", "symlink", "hardlink"):
            layout = RunLayout.create(self.task_root, f"case-{kind}")
            self.populate(layout, key, b"payload")
            supplier = self.make_supplier(layout)
            sentinel = self.task_root / f"sentinel-{kind}"
            sentinel.write_bytes(b"preserve")
            if kind == "unexpected":
                (layout.vendor_blobs / "extra").write_bytes(b"extra")
            elif kind == "symlink":
                (layout.vendor_blobs / f"{key}.idx").unlink()
                (layout.vendor_blobs / f"{key}.idx").symlink_to(sentinel)
            else:
                (layout.vendor_blobs / f"{key}.idx").unlink()
                os.link(layout.vendor_blobs / key, layout.vendor_blobs / f"{key}.idx")
            with self.subTest(kind=kind), self.assertRaises(RecoveryFailure):
                plan_vendor_cleanup(layout, key, supplier)
            self.assertEqual(sentinel.read_bytes(), b"preserve")
            self.assertTrue((layout.vendor_blobs / key).exists())


if __name__ == "__main__":
    unittest.main()
