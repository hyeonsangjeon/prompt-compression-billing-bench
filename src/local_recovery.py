"""Owner-only UNIX-socket authentication for local recovery calls."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import struct
import time
import tomllib
from typing import Any, Callable

from .squeez_recovery import (
    Fingerprint,
    RecoveryAdapter,
    RecoveryFailure,
    TrustedContext,
    digest,
    fingerprint_file,
    read_regular,
)


LABEL_PATTERN = re.compile(r"[a-z][a-z0-9-]{2,47}")
NONCE_PATTERN = re.compile(r"[0-9a-f]{32}")


class BridgeFailure(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _canonical_json(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _write_all(file_descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(file_descriptor, view)
        if written <= 0:
            raise OSError("exclusive write made no progress")
        view = view[written:]


def _exclusive_write(path: Path, payload: bytes, mode: int = 0o600) -> Fingerprint:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        file_descriptor = os.open(path, flags, mode)
    except FileExistsError as error:
        raise BridgeFailure("path_collision") from error
    try:
        _write_all(file_descriptor, payload)
        os.fsync(file_descriptor)
    finally:
        os.close(file_descriptor)
    return Fingerprint(len(payload), digest(payload))


def _ensure_under(path: Path, root: Path) -> Path:
    resolved_root = root.resolve(strict=True)
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise BridgeFailure("path_outside_task_root") from error
    return resolved


def _ensure_no_symlink_components(path: Path, root: Path) -> None:
    lexical_root = root.absolute()
    lexical_path = path.absolute()
    try:
        relative = lexical_path.relative_to(lexical_root)
    except ValueError as error:
        raise BridgeFailure("path_outside_task_root") from error
    current = lexical_root
    for component in relative.parts:
        current = current / component
        if not current.exists() and not current.is_symlink():
            continue
        if stat.S_ISLNK(current.lstat().st_mode):
            raise BridgeFailure("symlink_component_refused")
    _ensure_under(path, root)


@dataclass(frozen=True)
class BridgePolicy:
    scope: str
    transport: str
    peer_credentials: str
    external_tcp_enabled: bool
    capability_ttl_seconds: int
    capability_max_supplier_calls: int
    capability_max_recovered_bytes: int
    max_request_bytes: int
    max_response_bytes: int

    def validate(self) -> None:
        if self.scope != "local_software_control_not_operational":
            raise BridgeFailure("bridge_scope_invalid")
        if self.transport != "unix_domain_socket" or self.peer_credentials != "linux_so_peercred":
            raise BridgeFailure("bridge_transport_invalid")
        if self.external_tcp_enabled:
            raise BridgeFailure("external_tcp_forbidden")
        limits = (
            self.capability_ttl_seconds,
            self.capability_max_supplier_calls,
            self.capability_max_recovered_bytes,
            self.max_request_bytes,
            self.max_response_bytes,
        )
        if any(type(value) is not int or value <= 0 for value in limits):
            raise BridgeFailure("bridge_limit_invalid")


def load_bridge_policy(path: Path) -> BridgePolicy:
    payload = tomllib.loads(read_regular(path).decode("utf-8", errors="strict"))
    bridge = payload.get("local_bridge")
    if (
        payload.get("schema_version") != 1
        or payload.get("mode") != "squeez_local_recovery"
        or not isinstance(bridge, dict)
    ):
        raise BridgeFailure("bridge_ledger_identity_invalid")
    policy = BridgePolicy(
        scope=bridge.get("scope"),
        transport=bridge.get("transport"),
        peer_credentials=bridge.get("peer_credentials"),
        external_tcp_enabled=bridge.get("external_tcp_enabled"),
        capability_ttl_seconds=bridge.get("capability_ttl_seconds"),
        capability_max_supplier_calls=bridge.get("capability_max_supplier_calls"),
        capability_max_recovered_bytes=bridge.get("capability_max_recovered_bytes"),
        max_request_bytes=bridge.get("max_request_bytes"),
        max_response_bytes=bridge.get("max_response_bytes"),
    )
    policy.validate()
    return policy


@dataclass(frozen=True)
class PeerCredentials:
    pid: int
    uid: int
    gid: int

    def as_dict(self) -> dict[str, int]:
        return {"pid": self.pid, "uid": self.uid, "gid": self.gid}


def socket_peer_credentials(connection: socket.socket) -> PeerCredentials:
    if not hasattr(socket, "SO_PEERCRED"):
        raise BridgeFailure("peer_credentials_unsupported")
    payload = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    pid, uid, gid = struct.unpack("3i", payload)
    if pid <= 0 or uid < 0 or gid < 0:
        raise BridgeFailure("peer_credentials_invalid")
    return PeerCredentials(pid=pid, uid=uid, gid=gid)


@dataclass(frozen=True)
class SocketIdentity:
    device: int
    inode: int
    owner_uid: int
    mode: int


def _capture_socket_identity(path: Path, expected_uid: int) -> SocketIdentity:
    metadata = path.lstat()
    if not stat.S_ISSOCK(metadata.st_mode):
        raise BridgeFailure("socket_path_not_socket")
    if metadata.st_uid != expected_uid or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise BridgeFailure("socket_boundary_invalid")
    return SocketIdentity(metadata.st_dev, metadata.st_ino, metadata.st_uid, stat.S_IMODE(metadata.st_mode))


def verify_socket_identity(path: Path, identity: SocketIdentity, task_root: Path) -> None:
    _ensure_no_symlink_components(path.parent, task_root)
    parent = path.parent.lstat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != identity.owner_uid
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise BridgeFailure("socket_parent_boundary_drift")
    if _capture_socket_identity(path, identity.owner_uid) != identity:
        raise BridgeFailure("socket_identity_drift")


def bind_local_server(path: Path, task_root: Path, backlog: int = 8) -> tuple[socket.socket, SocketIdentity]:
    if not task_root.is_absolute() or task_root.is_symlink():
        raise BridgeFailure("task_root_invalid")
    task_root = task_root.resolve(strict=True)
    _ensure_no_symlink_components(path.parent, task_root)
    parent = path.parent.lstat()
    expected_uid = os.geteuid()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != expected_uid
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise BridgeFailure("socket_parent_boundary_invalid")
    if path.exists() or path.is_symlink():
        raise BridgeFailure("socket_path_collision")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    identity = None
    try:
        server.bind(str(path))
        os.chmod(path, 0o600)
        identity = _capture_socket_identity(path, expected_uid)
        server.listen(backlog)
        return server, identity
    except BaseException:
        server.close()
        if identity is not None:
            try:
                if _capture_socket_identity(path, expected_uid) == identity:
                    path.unlink()
            except (FileNotFoundError, BridgeFailure):
                pass
        raise


def close_local_server(server: socket.socket, path: Path, identity: SocketIdentity, task_root: Path) -> None:
    server.close()
    verify_socket_identity(path, identity, task_root)
    path.unlink()


def _send_message(connection: socket.socket, payload: dict[str, Any], maximum: int) -> None:
    data = _canonical_json(payload)
    if len(data) > maximum:
        raise BridgeFailure("message_too_large")
    connection.sendall(data)


def _receive_message(connection: socket.socket, maximum: int) -> dict[str, Any]:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = connection.recv(min(4096, maximum + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum:
            raise BridgeFailure("message_too_large")
        if b"\n" in chunk:
            break
    data = b"".join(chunks)
    if not data.endswith(b"\n") or data.count(b"\n") != 1:
        raise BridgeFailure("message_framing_invalid")
    try:
        value = json.loads(data.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BridgeFailure("message_json_invalid") from error
    if not isinstance(value, dict):
        raise BridgeFailure("message_not_object")
    return value


@dataclass(frozen=True)
class BridgeBindings:
    caller_id: str
    run_id: str
    trial_id: str
    handle: str
    ownership_epoch: str
    original_bytes: int


@dataclass
class CapabilityRecord:
    label: str
    token: str
    token_sha256: str
    caller_id: str
    peer_uid: int
    peer_pid: int
    run_id: str
    trial_id: str
    handle: str
    ownership_epoch: str
    expires_at: float
    max_supplier_calls: int
    max_recovered_bytes: int
    supplier_calls: int = 0
    recovered_bytes: int = 0


def _validate_private_directory(directory: Path, expected_uid: int) -> None:
    metadata = directory.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != expected_uid
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise BridgeFailure("private_directory_boundary_invalid")


class CapabilityStore:
    def __init__(self, directory: Path, expected_uid: int, policy: BridgePolicy) -> None:
        _validate_private_directory(directory, expected_uid)
        self.directory = directory
        self.expected_uid = expected_uid
        self.policy = policy
        self.records: dict[str, CapabilityRecord] = {}

    def issue(self, *, label: str, peer: PeerCredentials, bindings: BridgeBindings, now: float) -> CapabilityRecord:
        _validate_private_directory(self.directory, self.expected_uid)
        if not isinstance(label, str) or LABEL_PATTERN.fullmatch(label) is None:
            raise BridgeFailure("capability_label_invalid")
        if label in self.records:
            raise BridgeFailure("capability_label_collision")
        token = secrets.token_urlsafe(32)
        record = CapabilityRecord(
            label=label,
            token=token,
            token_sha256=digest(token.encode("ascii")),
            caller_id=bindings.caller_id,
            peer_uid=peer.uid,
            peer_pid=peer.pid,
            run_id=bindings.run_id,
            trial_id=bindings.trial_id,
            handle=bindings.handle,
            ownership_epoch=bindings.ownership_epoch,
            expires_at=now + self.policy.capability_ttl_seconds,
            max_supplier_calls=self.policy.capability_max_supplier_calls,
            max_recovered_bytes=self.policy.capability_max_recovered_bytes,
        )
        payload = _canonical_json(
            {
                "schema_version": 1,
                "kind": "private_run_scoped_recovery_capability",
                "token": token,
                "caller_id": bindings.caller_id,
                "peer_uid": peer.uid,
                "peer_pid": peer.pid,
                "run_id": bindings.run_id,
                "trial_id": bindings.trial_id,
                "handle": bindings.handle,
                "ownership_epoch": bindings.ownership_epoch,
                "expires_at_unix": record.expires_at,
                "max_supplier_calls": record.max_supplier_calls,
                "max_recovered_bytes": record.max_recovered_bytes,
                "operational_default": False,
            }
        )
        path = self.directory / f"{label}.json"
        try:
            _exclusive_write(path, payload)
        except BridgeFailure as error:
            if error.code == "path_collision":
                raise BridgeFailure("capability_path_collision") from error
            raise
        metadata = path.lstat()
        if metadata.st_uid != self.expected_uid or metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise BridgeFailure("capability_file_boundary_invalid")
        self.records[label] = record
        return record

    def authenticate(self, label: Any, token: Any) -> CapabilityRecord:
        if not isinstance(label, str) or LABEL_PATTERN.fullmatch(label) is None or not isinstance(token, str):
            raise BridgeFailure("invalid_capability")
        record = self.records.get(label)
        if record is None or not hmac.compare_digest(record.token, token):
            raise BridgeFailure("invalid_capability")
        return record


class NonceStore:
    def __init__(self, directory: Path, expected_uid: int) -> None:
        _validate_private_directory(directory, expected_uid)
        self.directory = directory
        self.expected_uid = expected_uid

    def consume(self, label: str, token_sha256: str, nonce: Any) -> None:
        _validate_private_directory(self.directory, self.expected_uid)
        if (
            LABEL_PATTERN.fullmatch(label) is None
            or not isinstance(nonce, str)
            or NONCE_PATTERN.fullmatch(nonce) is None
        ):
            raise BridgeFailure("request_nonce_invalid")
        nonce_sha256 = digest(nonce.encode("ascii"))
        path = self.directory / f"{label}-{nonce_sha256}.used"
        payload = _canonical_json(
            {
                "schema_version": 1,
                "kind": "private_recovery_nonce_consumption",
                "capability_sha256": token_sha256,
                "nonce_sha256": nonce_sha256,
                "raw_nonce_recorded": False,
            }
        )
        try:
            _exclusive_write(path, payload)
        except BridgeFailure as error:
            if error.code == "path_collision":
                raise BridgeFailure("request_replay") from error
            raise
        metadata = path.lstat()
        if metadata.st_uid != self.expected_uid or metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise BridgeFailure("nonce_state_boundary_invalid")


class AuditWriter:
    def __init__(self, file_descriptor: int) -> None:
        self.file_descriptor = file_descriptor
        self.sequence = 0
        self.closed = False

    @classmethod
    def reserve(cls, path: Path) -> "AuditWriter":
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            file_descriptor = os.open(path, flags, 0o600)
        except FileExistsError as error:
            raise BridgeFailure("audit_path_collision") from error
        return cls(file_descriptor)

    def append(self, event: dict[str, Any]) -> None:
        if self.closed:
            raise BridgeFailure("audit_closed")
        self.sequence += 1
        data = _canonical_json(
            {
                "schema_version": 1,
                "kind": "private_local_recovery_audit_event",
                "sequence": self.sequence,
                **event,
            }
        )
        _write_all(self.file_descriptor, data)
        os.fsync(self.file_descriptor)

    def close(self) -> None:
        if not self.closed:
            os.close(self.file_descriptor)
            self.closed = True


@dataclass(frozen=True)
class RuntimeCleanupEntry:
    relative_path: str
    kind: str
    device: int
    inode: int
    mode: int
    owner_uid: int
    link_count: int
    fingerprint: Fingerprint | None


@dataclass(frozen=True)
class RuntimeCleanupPlan:
    root: Path
    root_device: int
    root_inode: int
    root_mode: int
    expected_uid: int
    entries: tuple[RuntimeCleanupEntry, ...]


def _runtime_relative_paths(root: Path) -> set[str]:
    paths: set[str] = set()

    def visit(directory: Path) -> None:
        with os.scandir(directory) as iterator:
            children = sorted(iterator, key=lambda item: os.fsencode(item.name))
        for child in children:
            path = Path(child.path)
            relative = path.relative_to(root).as_posix()
            paths.add(relative)
            metadata = child.stat(follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                visit(path)

    visit(root)
    return paths


def plan_runtime_cleanup(
    root: Path,
    allowed_relative_paths: set[str],
    expected_uid: int,
) -> RuntimeCleanupPlan:
    root_metadata = root.lstat()
    root_mode = stat.S_IMODE(root_metadata.st_mode)
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or stat.S_ISLNK(root_metadata.st_mode)
        or root_metadata.st_uid != expected_uid
        or root_mode != 0o700
    ):
        raise BridgeFailure("cleanup_root_invalid")
    observed = _runtime_relative_paths(root)
    if observed != allowed_relative_paths:
        raise BridgeFailure("cleanup_tree_allowlist_mismatch")
    entries: list[RuntimeCleanupEntry] = []
    for relative in sorted(observed, key=lambda item: (item.count("/"), os.fsencode(item))):
        path = root / relative
        _ensure_no_symlink_components(path.parent, root)
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if metadata.st_uid != expected_uid:
            raise BridgeFailure("cleanup_entry_owner_mismatch")
        if stat.S_ISREG(metadata.st_mode):
            if metadata.st_nlink != 1:
                raise BridgeFailure("cleanup_regular_link_count_invalid")
            if mode != 0o600:
                raise BridgeFailure("cleanup_regular_mode_invalid")
            kind = "regular"
            fingerprint = fingerprint_file(path)
        elif stat.S_ISDIR(metadata.st_mode):
            if mode != 0o700:
                raise BridgeFailure("cleanup_directory_mode_invalid")
            kind = "directory"
            fingerprint = None
        elif stat.S_ISSOCK(metadata.st_mode):
            if metadata.st_nlink != 1:
                raise BridgeFailure("cleanup_socket_link_count_invalid")
            if mode != 0o600:
                raise BridgeFailure("cleanup_socket_mode_invalid")
            kind = "socket"
            fingerprint = None
        elif stat.S_ISLNK(metadata.st_mode):
            raise BridgeFailure("cleanup_symlink_refused")
        else:
            raise BridgeFailure("cleanup_special_file_refused")
        entries.append(
            RuntimeCleanupEntry(
                relative_path=relative,
                kind=kind,
                device=metadata.st_dev,
                inode=metadata.st_ino,
                mode=mode,
                owner_uid=metadata.st_uid,
                link_count=metadata.st_nlink,
                fingerprint=fingerprint,
            )
        )
    return RuntimeCleanupPlan(
        root=root,
        root_device=root_metadata.st_dev,
        root_inode=root_metadata.st_ino,
        root_mode=root_mode,
        expected_uid=expected_uid,
        entries=tuple(entries),
    )


def execute_runtime_cleanup(plan: RuntimeCleanupPlan) -> tuple[RuntimeCleanupEntry, ...]:
    root_metadata = plan.root.lstat()
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or stat.S_ISLNK(root_metadata.st_mode)
        or root_metadata.st_dev != plan.root_device
        or root_metadata.st_ino != plan.root_inode
        or root_metadata.st_uid != plan.expected_uid
        or stat.S_IMODE(root_metadata.st_mode) != plan.root_mode
    ):
        raise BridgeFailure("cleanup_root_identity_changed")
    allowed = {entry.relative_path for entry in plan.entries}
    if _runtime_relative_paths(plan.root) != allowed:
        raise BridgeFailure("cleanup_tree_changed_before_delete")
    indexed = {entry.relative_path: entry for entry in plan.entries}
    for relative, expected in indexed.items():
        path = plan.root / relative
        metadata = path.lstat()
        if (
            metadata.st_uid != plan.expected_uid
            or metadata.st_dev != expected.device
            or metadata.st_ino != expected.inode
            or metadata.st_nlink != expected.link_count
            or stat.S_IMODE(metadata.st_mode) != expected.mode
        ):
            raise BridgeFailure("cleanup_entry_identity_changed")
        if expected.kind == "regular":
            if not stat.S_ISREG(metadata.st_mode) or fingerprint_file(path) != expected.fingerprint:
                raise BridgeFailure("cleanup_regular_drift")
        elif expected.kind == "directory":
            if not stat.S_ISDIR(metadata.st_mode):
                raise BridgeFailure("cleanup_directory_drift")
        elif expected.kind == "socket":
            if not stat.S_ISSOCK(metadata.st_mode):
                raise BridgeFailure("cleanup_socket_drift")
        else:
            raise BridgeFailure("cleanup_kind_invalid")
    for relative, expected in sorted(
        indexed.items(),
        key=lambda item: (-item[0].count("/"), os.fsencode(item[0])),
    ):
        path = plan.root / relative
        if expected.kind in {"regular", "socket"}:
            parent_descriptor = os.open(
                path.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                named = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
                if named.st_dev != expected.device or named.st_ino != expected.inode:
                    raise BridgeFailure("cleanup_entry_identity_changed")
                os.unlink(path.name, dir_fd=parent_descriptor)
            finally:
                os.close(parent_descriptor)
        else:
            os.rmdir(path)
    if _runtime_relative_paths(plan.root):
        raise BridgeFailure("cleanup_root_not_empty")
    return plan.entries


class LocalRecoveryBridge:
    def __init__(
        self,
        *,
        expected_uid: int,
        policy: BridgePolicy,
        bindings: BridgeBindings,
        trusted_context: TrustedContext,
        capabilities: CapabilityStore,
        nonces: NonceStore,
        adapter: RecoveryAdapter,
        audit: AuditWriter | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        policy.validate()
        if trusted_context.caller_id != bindings.caller_id or trusted_context.run_id != bindings.run_id:
            raise BridgeFailure("bridge_context_binding_mismatch")
        if (
            trusted_context.trial_id != bindings.trial_id
            or trusted_context.ownership_epoch != bindings.ownership_epoch
        ):
            raise BridgeFailure("bridge_context_binding_mismatch")
        record = adapter.registry.get(bindings.handle)
        if record is None or record.original.bytes != bindings.original_bytes:
            raise BridgeFailure("bridge_source_binding_mismatch")
        if (
            record.caller_id != bindings.caller_id
            or record.run_id != bindings.run_id
            or record.trial_id != bindings.trial_id
            or record.ownership_epoch != bindings.ownership_epoch
        ):
            raise BridgeFailure("bridge_source_binding_mismatch")
        self.expected_uid = expected_uid
        self.policy = policy
        self.bindings = bindings
        self.trusted_context = trusted_context
        self.capabilities = capabilities
        self.nonces = nonces
        self.adapter = adapter
        self.audit = audit
        self.clock = clock

    def _audit(self, event: dict[str, Any]) -> None:
        if self.audit is not None:
            self.audit.append(event)

    def _reject(
        self,
        action: str,
        peer: PeerCredentials,
        code: str,
        label: Any = None,
        nonce: Any = None,
    ) -> dict[str, Any]:
        self._audit(
            {
                "event": "request_rejected",
                "action": action,
                "reason": code,
                "peer": peer.as_dict(),
                "capability_label": label if isinstance(label, str) else None,
                "nonce_sha256": digest(nonce.encode("utf-8")) if isinstance(nonce, str) else None,
                "supplier_invoked": False,
            }
        )
        return {"ok": False, "error": code, "supplier_invoked": False}

    def handle(self, peer: PeerCredentials, request: dict[str, Any]) -> dict[str, Any]:
        action = request.get("action") if isinstance(request, dict) else None
        if action == "issue":
            return self._issue(peer, request)
        if action == "recover":
            return self._recover(peer, request)
        return self._reject("unknown", peer, "action_invalid")

    def _issue(self, peer: PeerCredentials, request: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "action", "label", "caller_id", "claimed_pid", "run_id", "trial_id", "handle", "ownership_epoch"
        }
        label = request.get("label")
        if set(request) != allowed:
            return self._reject("issue", peer, "issue_fields_invalid", label)
        if peer.uid != self.expected_uid:
            return self._reject("issue", peer, "peer_uid_mismatch", label)
        if request.get("claimed_pid") != peer.pid:
            return self._reject("issue", peer, "claimed_pid_mismatch", label)
        checks = (
            (request.get("caller_id"), self.bindings.caller_id, "caller_mismatch"),
            (request.get("run_id"), self.bindings.run_id, "run_mismatch"),
            (request.get("trial_id"), self.bindings.trial_id, "trial_mismatch"),
            (request.get("handle"), self.bindings.handle, "handle_mismatch"),
            (request.get("ownership_epoch"), self.bindings.ownership_epoch, "ownership_epoch_mismatch"),
        )
        for observed, expected, code in checks:
            if observed != expected:
                return self._reject("issue", peer, code, label)
        try:
            capability = self.capabilities.issue(
                label=label,
                peer=peer,
                bindings=self.bindings,
                now=self.clock(),
            )
        except BridgeFailure as error:
            return self._reject("issue", peer, error.code, label)
        self._audit(
            {
                "event": "capability_issued",
                "peer": peer.as_dict(),
                "capability_label": label,
                "capability_sha256": capability.token_sha256,
                "bound_run_sha256": digest(capability.run_id.encode("utf-8")),
                "bound_handle_sha256": digest(capability.handle.encode("utf-8")),
                "bound_epoch_sha256": digest(capability.ownership_epoch.encode("utf-8")),
                "expires_at_unix": capability.expires_at,
                "supplier_invoked": False,
            }
        )
        return {
            "ok": True,
            "status": "capability_issued",
            "capability_label": label,
            "expires_at_unix": capability.expires_at,
            "supplier_invoked": False,
        }

    def _recover(self, peer: PeerCredentials, request: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "action", "label", "token", "nonce", "caller_id", "run_id", "trial_id", "handle", "ownership_epoch"
        }
        label = request.get("label")
        nonce = request.get("nonce")
        if set(request) != allowed:
            return self._reject("recover", peer, "recover_fields_invalid", label, nonce)
        try:
            capability = self.capabilities.authenticate(label, request.get("token"))
        except BridgeFailure as error:
            return self._reject("recover", peer, error.code, label, nonce)
        checks = (
            (peer.uid, capability.peer_uid, "peer_uid_mismatch"),
            (peer.pid, capability.peer_pid, "peer_pid_mismatch"),
            (request.get("caller_id"), capability.caller_id, "caller_mismatch"),
            (request.get("run_id"), capability.run_id, "run_mismatch"),
            (request.get("trial_id"), capability.trial_id, "trial_mismatch"),
            (request.get("handle"), capability.handle, "handle_mismatch"),
            (request.get("ownership_epoch"), capability.ownership_epoch, "ownership_epoch_mismatch"),
        )
        for observed, expected, code in checks:
            if observed != expected:
                return self._reject("recover", peer, code, label, nonce)
        if self.clock() >= capability.expires_at:
            return self._reject("recover", peer, "capability_expired", label, nonce)
        try:
            self.nonces.consume(capability.label, capability.token_sha256, nonce)
        except BridgeFailure as error:
            return self._reject("recover", peer, error.code, label, nonce)
        if capability.supplier_calls >= capability.max_supplier_calls:
            return self._reject("recover", peer, "capability_supplier_quota_reached", label, nonce)
        if capability.recovered_bytes + self.bindings.original_bytes > capability.max_recovered_bytes:
            return self._reject("recover", peer, "capability_byte_quota_reached", label, nonce)
        before_calls = self.adapter.supplier.calls
        decision = self.adapter.recover(
            context=self.trusted_context,
            request={"handle": capability.handle},
        )
        observed_calls = self.adapter.supplier.calls - before_calls
        if decision.supplier_invoked and observed_calls != 1:
            raise BridgeFailure("supplier_invocation_count_invalid")
        if not decision.supplier_invoked and observed_calls != 0:
            raise BridgeFailure("supplier_invocation_count_invalid")
        if decision.supplier_invoked:
            capability.supplier_calls += 1
        if decision.content is None:
            self._audit(
                {
                    "event": "supplier_result",
                    "peer": peer.as_dict(),
                    "capability_label": capability.label,
                    "capability_sha256": capability.token_sha256,
                    "nonce_sha256": digest(nonce.encode("ascii")),
                    "status": "error",
                    "reason": decision.private_reason,
                    "supplier_invoked": decision.supplier_invoked,
                }
            )
            return {
                "ok": False,
                "error": decision.public_error,
                "supplier_invoked": decision.supplier_invoked,
            }
        if capability.recovered_bytes + len(decision.content) > capability.max_recovered_bytes:
            raise BridgeFailure("capability_byte_quota_overrun")
        capability.recovered_bytes += len(decision.content)
        content = Fingerprint(len(decision.content), digest(decision.content))
        self._audit(
            {
                "event": "supplier_result",
                "peer": peer.as_dict(),
                "capability_label": capability.label,
                "capability_sha256": capability.token_sha256,
                "nonce_sha256": digest(nonce.encode("ascii")),
                "status": decision.status,
                "content": content.as_dict(),
                "supplier_invoked": decision.supplier_invoked,
            }
        )
        return {
            "ok": True,
            "status": decision.status,
            "complete": decision.complete,
            "content_base64": base64.b64encode(decision.content).decode("ascii"),
            "content": content.as_dict(),
            "next_cursor": decision.next_cursor,
            "supplier_invoked": decision.supplier_invoked,
            "remaining_supplier_calls": capability.max_supplier_calls - capability.supplier_calls,
            "remaining_recovered_bytes": capability.max_recovered_bytes - capability.recovered_bytes,
        }


def serve_connection(
    server: socket.socket,
    socket_path: Path,
    socket_identity: SocketIdentity,
    task_root: Path,
    bridge: LocalRecoveryBridge,
) -> dict[str, Any]:
    verify_socket_identity(socket_path, socket_identity, task_root)
    connection, _address = server.accept()
    with connection:
        peer = socket_peer_credentials(connection)
        try:
            request = _receive_message(connection, bridge.policy.max_request_bytes)
            response = bridge.handle(peer, request)
        except BridgeFailure as error:
            response = {"ok": False, "error": error.code, "supplier_invoked": False}
        _send_message(connection, response, bridge.policy.max_response_bytes)
    return response


def request_local(
    socket_path: Path,
    request: dict[str, Any],
    *,
    expected_server_uid: int,
    max_request_bytes: int,
    max_response_bytes: int,
) -> dict[str, Any]:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.connect(str(socket_path))
        peer = socket_peer_credentials(connection)
        if peer.uid != expected_server_uid:
            raise BridgeFailure("server_uid_mismatch")
        _send_message(connection, request, max_request_bytes)
        connection.shutdown(socket.SHUT_WR)
        return _receive_message(connection, max_response_bytes)
    finally:
        connection.close()
