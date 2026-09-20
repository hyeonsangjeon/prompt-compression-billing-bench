"""Fail-closed, local-only recovery primitives for pinned squeez output."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import signal
import stat
import subprocess
import time
import tomllib
from typing import Any, Callable, Mapping, Protocol


PERMISSION = "recovery:read"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
HANDLE_PATTERN = re.compile(r"recover-[0-9a-f]{32}")
RUN_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")
SUPPLIER_KEY_PATTERN = re.compile(r"[0-9a-f]{16,64}")
REQUEST_FIELDS = {"handle", "cursor"}


class RecoveryFailure(ValueError):
    def __init__(self, public_error: str, reason: str):
        super().__init__(reason)
        self.public_error = public_error
        self.reason = reason


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class Fingerprint:
    bytes: int
    sha256: str

    def validate(self) -> None:
        if type(self.bytes) is not int or self.bytes < 0:
            raise RecoveryFailure("configuration_error", "fingerprint_bytes_invalid")
        if not isinstance(self.sha256, str) or SHA256_PATTERN.fullmatch(self.sha256) is None:
            raise RecoveryFailure("configuration_error", "fingerprint_sha256_invalid")

    def as_dict(self) -> dict[str, Any]:
        return {"bytes": self.bytes, "sha256": self.sha256}


def _read_descriptor(file_descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        block = os.read(file_descriptor, 1024 * 1024)
        if not block:
            return b"".join(chunks)
        chunks.append(block)


def read_regular(path: Path) -> bytes:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise RecoveryFailure("configuration_error", "path_not_regular")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        file_descriptor = os.open(path, flags)
    except OSError as error:
        raise RecoveryFailure("configuration_error", "regular_open_refused") from error
    try:
        opened = os.fstat(file_descriptor)
        if opened.st_dev != metadata.st_dev or opened.st_ino != metadata.st_ino:
            raise RecoveryFailure("configuration_error", "path_identity_changed")
        return _read_descriptor(file_descriptor)
    finally:
        os.close(file_descriptor)


def fingerprint_file(path: Path) -> Fingerprint:
    payload = read_regular(path)
    return Fingerprint(len(payload), digest(payload))


def _write_all(file_descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(file_descriptor, view)
        if written <= 0:
            raise OSError("exclusive write made no progress")
        view = view[written:]


def exclusive_write(path: Path, payload: bytes, mode: int = 0o600) -> Fingerprint:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        file_descriptor = os.open(path, flags, mode)
    except FileExistsError as error:
        raise RecoveryFailure("configuration_error", "result_path_collision") from error
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
        raise RecoveryFailure("configuration_error", "path_outside_task_root") from error
    return resolved


def _ensure_no_symlink_components(path: Path, root: Path) -> None:
    lexical_root = root.absolute()
    lexical_path = path.absolute()
    try:
        relative = lexical_path.relative_to(lexical_root)
    except ValueError as error:
        raise RecoveryFailure("configuration_error", "path_outside_task_root") from error
    current = lexical_root
    for component in relative.parts:
        current = current / component
        if not current.exists() and not current.is_symlink():
            continue
        if stat.S_ISLNK(current.lstat().st_mode):
            raise RecoveryFailure("configuration_error", "symlink_component_refused")
    _ensure_under(path, root)


@dataclass(frozen=True)
class RecoveryPolicy:
    scope: str
    enabled: bool
    external_agent_or_mcp_enabled: bool
    multi_user_authentication_implemented: bool
    required_permission: str
    ttl_seconds: int
    retention_seconds: int
    max_response_bytes: int
    max_total_bytes_per_handle: int
    max_calls_per_handle: int
    max_supplier_calls_per_trial: int
    max_recovered_bytes_per_trial: int
    supplier_timeout_seconds: float
    supplier_stdout_limit_bytes: int
    supplier_stderr_limit_bytes: int

    def validate(self) -> None:
        if self.scope != "local_software_control_not_operational":
            raise RecoveryFailure("configuration_error", "policy_scope_invalid")
        if type(self.enabled) is not bool:
            raise RecoveryFailure("configuration_error", "policy_enabled_invalid")
        if self.external_agent_or_mcp_enabled:
            raise RecoveryFailure("configuration_error", "external_exposure_forbidden")
        if self.multi_user_authentication_implemented:
            raise RecoveryFailure("configuration_error", "multi_user_authentication_claim_unsupported")
        if self.required_permission != PERMISSION:
            raise RecoveryFailure("configuration_error", "required_permission_invalid")
        integer_limits = (
            self.ttl_seconds,
            self.retention_seconds,
            self.max_response_bytes,
            self.max_total_bytes_per_handle,
            self.max_calls_per_handle,
            self.max_supplier_calls_per_trial,
            self.max_recovered_bytes_per_trial,
            self.supplier_stdout_limit_bytes,
            self.supplier_stderr_limit_bytes,
        )
        if any(type(value) is not int or value <= 0 for value in integer_limits):
            raise RecoveryFailure("configuration_error", "policy_integer_limit_invalid")
        if self.ttl_seconds > self.retention_seconds:
            raise RecoveryFailure("configuration_error", "ttl_exceeds_retention")
        if self.max_response_bytes > self.max_total_bytes_per_handle:
            raise RecoveryFailure("configuration_error", "response_exceeds_handle_limit")
        if self.max_calls_per_handle > self.max_supplier_calls_per_trial:
            raise RecoveryFailure("configuration_error", "handle_calls_exceed_trial_limit")
        if self.max_total_bytes_per_handle > self.max_recovered_bytes_per_trial:
            raise RecoveryFailure("configuration_error", "handle_bytes_exceed_trial_limit")
        if (
            not isinstance(self.supplier_timeout_seconds, (int, float))
            or isinstance(self.supplier_timeout_seconds, bool)
            or not math.isfinite(self.supplier_timeout_seconds)
            or self.supplier_timeout_seconds <= 0
        ):
            raise RecoveryFailure("configuration_error", "supplier_timeout_invalid")


def load_recovery_policy(path: Path) -> RecoveryPolicy:
    payload = tomllib.loads(read_regular(path).decode("utf-8", errors="strict"))
    if payload.get("schema_version") != 1 or payload.get("mode") != "squeez_local_recovery":
        raise RecoveryFailure("configuration_error", "recovery_ledger_identity_invalid")
    recovery = payload.get("recovery")
    supplier = payload.get("supplier")
    if not isinstance(recovery, dict) or not isinstance(supplier, dict):
        raise RecoveryFailure("configuration_error", "recovery_ledger_sections_missing")
    policy = RecoveryPolicy(
        scope=recovery.get("scope"),
        enabled=recovery.get("enabled"),
        external_agent_or_mcp_enabled=recovery.get("external_agent_or_mcp_enabled"),
        multi_user_authentication_implemented=recovery.get("multi_user_authentication_implemented"),
        required_permission=recovery.get("required_permission"),
        ttl_seconds=recovery.get("ttl_seconds"),
        retention_seconds=recovery.get("retention_seconds"),
        max_response_bytes=recovery.get("max_response_bytes"),
        max_total_bytes_per_handle=recovery.get("max_total_bytes_per_handle"),
        max_calls_per_handle=recovery.get("max_calls_per_handle"),
        max_supplier_calls_per_trial=recovery.get("max_supplier_calls_per_trial"),
        max_recovered_bytes_per_trial=recovery.get("max_recovered_bytes_per_trial"),
        supplier_timeout_seconds=supplier.get("timeout_seconds"),
        supplier_stdout_limit_bytes=supplier.get("stdout_limit_bytes"),
        supplier_stderr_limit_bytes=supplier.get("stderr_limit_bytes"),
    )
    policy.validate()
    return policy


@dataclass(frozen=True)
class SupplierSpec:
    binary_env: str
    version: str
    fingerprint: Fingerprint
    transport: str

    def validate(self) -> None:
        if (
            not isinstance(self.binary_env, str)
            or re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", self.binary_env) is None
        ):
            raise RecoveryFailure("configuration_error", "supplier_binary_env_invalid")
        if not isinstance(self.version, str) or not self.version:
            raise RecoveryFailure("configuration_error", "supplier_version_invalid")
        self.fingerprint.validate()
        if self.transport != "stdio_mcp":
            raise RecoveryFailure("configuration_error", "supplier_transport_invalid")

    def resolve_binary(self, environment: Mapping[str, str]) -> Path:
        value = environment.get(self.binary_env)
        if not value or not Path(value).is_absolute():
            raise RecoveryFailure("configuration_error", "supplier_binary_path_missing")
        path = Path(value)
        if fingerprint_file(path) != self.fingerprint or not os.access(path, os.X_OK):
            raise RecoveryFailure("configuration_error", "supplier_binary_drift")
        return path.resolve(strict=True)


def load_supplier_spec(path: Path) -> SupplierSpec:
    payload = tomllib.loads(read_regular(path).decode("utf-8", errors="strict"))
    supplier = payload.get("supplier")
    if (
        payload.get("schema_version") != 1
        or payload.get("mode") != "squeez_local_recovery"
        or not isinstance(supplier, dict)
    ):
        raise RecoveryFailure("configuration_error", "supplier_ledger_identity_invalid")
    specification = SupplierSpec(
        binary_env=supplier.get("binary_env"),
        version=supplier.get("version"),
        fingerprint=Fingerprint(supplier.get("bytes"), supplier.get("sha256")),
        transport=supplier.get("transport"),
    )
    specification.validate()
    return specification


@dataclass(frozen=True)
class TrustedContext:
    caller_id: str
    run_id: str
    trial_id: str
    ownership_epoch: str | None
    authority: str
    permissions: frozenset[str]

    def validate(self, *, allow_missing_epoch: bool = False) -> None:
        for field_name in ("caller_id", "run_id", "trial_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise RecoveryFailure("not_available", "trusted_context_invalid")
        if self.authority != "trusted_harness":
            raise RecoveryFailure("not_available", "trusted_authority_invalid")
        if not isinstance(self.permissions, frozenset) or any(
            not isinstance(item, str) or not item for item in self.permissions
        ):
            raise RecoveryFailure("not_available", "trusted_permissions_invalid")
        if not allow_missing_epoch and (
            not isinstance(self.ownership_epoch, str) or not self.ownership_epoch
        ):
            raise RecoveryFailure("not_available", "restart_ownership_unverified")


@dataclass
class HandleRecord:
    handle: str
    supplier_key: str
    caller_id: str
    run_id: str
    trial_id: str
    ownership_epoch: str
    original: Fingerprint
    input_sha256: str
    created_at: float
    state: str = "active"
    calls: int = 0
    delivered_bytes: int = 0
    next_offset: int = 0
    next_cursor: str | None = None


@dataclass
class TrialUsage:
    supplier_calls: int = 0
    recovered_bytes: int = 0


class RecoveryRegistry:
    def __init__(self) -> None:
        self._records: dict[str, HandleRecord] = {}
        self._trial_usage: dict[tuple[str, str], TrialUsage] = {}

    def issue_candidate(
        self,
        *,
        context: TrustedContext,
        handle: str,
        supplier_key: str,
        original: bytes,
        input_sha256: str,
        candidate: bool,
        provenance: str,
        compressor: str,
        created_at: float,
    ) -> HandleRecord:
        context.validate()
        if HANDLE_PATTERN.fullmatch(handle) is None or handle in self._records:
            raise RecoveryFailure("configuration_error", "trusted_handle_invalid_or_duplicate")
        if SUPPLIER_KEY_PATTERN.fullmatch(supplier_key) is None:
            raise RecoveryFailure("configuration_error", "supplier_key_invalid")
        if candidate is not True or provenance != "fresh_candidate" or compressor != "squeez":
            raise RecoveryFailure("configuration_error", "unsupported_handle_source")
        if not isinstance(original, bytes) or not original:
            raise RecoveryFailure("configuration_error", "trusted_original_empty_or_invalid")
        try:
            original.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise RecoveryFailure("configuration_error", "trusted_original_not_strict_utf8") from error
        if SHA256_PATTERN.fullmatch(input_sha256) is None:
            raise RecoveryFailure("configuration_error", "input_sha256_invalid")
        if not isinstance(created_at, (int, float)) or isinstance(created_at, bool) or not math.isfinite(created_at):
            raise RecoveryFailure("configuration_error", "created_at_invalid")
        record = HandleRecord(
            handle=handle,
            supplier_key=supplier_key,
            caller_id=context.caller_id,
            run_id=context.run_id,
            trial_id=context.trial_id,
            ownership_epoch=context.ownership_epoch,
            original=Fingerprint(len(original), digest(original)),
            input_sha256=input_sha256,
            created_at=float(created_at),
        )
        self._records[handle] = record
        return record

    def get(self, handle: str) -> HandleRecord | None:
        return self._records.get(handle)

    def usage(self, run_id: str, trial_id: str) -> TrialUsage:
        return self._trial_usage.setdefault((run_id, trial_id), TrialUsage())

    def revoke(self, context: TrustedContext, handle: str) -> None:
        context.validate()
        record = self._records.get(handle)
        if record is None:
            raise RecoveryFailure("not_available", "missing_handle")
        if (
            context.caller_id != record.caller_id
            or context.run_id != record.run_id
            or context.trial_id != record.trial_id
            or context.ownership_epoch != record.ownership_epoch
        ):
            raise RecoveryFailure("not_available", "ownership_mismatch")
        record.state = "revoked"


@dataclass(frozen=True)
class ProcessObservation:
    pid: int | None
    exit_code: int | None
    timed_out: bool
    waited: bool
    wall_seconds: float
    stdout: Fingerprint
    stderr: Fingerprint

    def as_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "waited": self.waited,
            "wall_seconds": self.wall_seconds,
            "stdout": self.stdout.as_dict(),
            "stderr": self.stderr.as_dict(),
        }


@dataclass(frozen=True)
class SupplierEnvelope:
    outcome: str
    content: bytes | None
    observation: ProcessObservation


class Supplier(Protocol):
    calls: int

    def recover(self, record: HandleRecord) -> SupplierEnvelope:
        ...


def squeez_mcp_request(supplier_key: str) -> bytes:
    if SUPPLIER_KEY_PATTERN.fullmatch(supplier_key) is None:
        raise RecoveryFailure("configuration_error", "supplier_key_invalid")
    messages = (
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pccb-squeez-recovery", "version": "1"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "squeez_retrieve", "arguments": {"key": supplier_key}},
        },
    )
    return (
        "\n".join(
            json.dumps(item, ensure_ascii=False, separators=(",", ":"))
            for item in messages
        )
        + "\n"
    ).encode("utf-8")


def classify_squeez_mcp_response(
    stdout: bytes,
    stderr: bytes,
    supplier_key: str,
    observation: ProcessObservation,
) -> SupplierEnvelope:
    if observation.timed_out:
        return SupplierEnvelope("timeout", None, observation)
    if observation.exit_code != 0 or stderr:
        return SupplierEnvelope("transport_error", None, observation)
    try:
        lines = stdout.decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError:
        return SupplierEnvelope("malformed", None, observation)
    responses: list[dict[str, Any]] = []
    for line in lines:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            return SupplierEnvelope("malformed", None, observation)
        if isinstance(message, dict) and message.get("id") == 2:
            responses.append(message)
    if len(responses) != 1:
        return SupplierEnvelope("malformed", None, observation)
    response = responses[0]
    if response.get("jsonrpc") != "2.0" or "error" in response:
        return SupplierEnvelope("reported_error", None, observation)
    result = response.get("result")
    if not isinstance(result, dict) or result.get("isError") is True:
        return SupplierEnvelope("reported_error", None, observation)
    content = result.get("content")
    if not isinstance(content, list) or len(content) != 1:
        return SupplierEnvelope("malformed", None, observation)
    item = content[0]
    if not isinstance(item, dict) or item.get("type") != "text" or not isinstance(item.get("text"), str):
        return SupplierEnvelope("malformed", None, observation)
    payload = item["text"].encode("utf-8", errors="strict")
    missing = (
        f"squeez_retrieve: no stored output for key '{supplier_key}'. "
        "It may be malformed, expired (past retrieve_ttl_days), or never stored."
    ).encode("utf-8")
    if payload == missing:
        return SupplierEnvelope("not_found", None, observation)
    return SupplierEnvelope("recovered", payload, observation)


@dataclass(frozen=True)
class RunLayout:
    task_root: Path
    root: Path
    home: Path
    cwd: Path
    xdg_config: Path
    xdg_data: Path
    xdg_cache: Path
    xdg_runtime: Path
    temporary: Path
    marker_path: Path
    marker: Fingerprint
    root_device: int
    root_inode: int
    run_id: str

    @classmethod
    def create(cls, task_root: Path, run_id: str) -> "RunLayout":
        if RUN_ID_PATTERN.fullmatch(run_id) is None:
            raise RecoveryFailure("configuration_error", "run_id_invalid")
        if not task_root.is_absolute() or task_root.is_symlink():
            raise RecoveryFailure("configuration_error", "task_root_invalid")
        task_root = task_root.resolve(strict=True)
        if not task_root.is_dir():
            raise RecoveryFailure("configuration_error", "task_root_not_directory")
        runs = task_root / "runs"
        runs.mkdir(mode=0o700, exist_ok=True)
        _ensure_no_symlink_components(runs, task_root)
        runs_status = runs.lstat()
        if (
            not stat.S_ISDIR(runs_status.st_mode)
            or runs_status.st_uid != os.geteuid()
            or stat.S_IMODE(runs_status.st_mode) != 0o700
        ):
            raise RecoveryFailure("configuration_error", "run_parent_boundary_invalid")
        root = runs / run_id
        try:
            os.mkdir(root, 0o700)
        except FileExistsError as error:
            raise RecoveryFailure("configuration_error", "run_path_collision") from error
        root_status = root.lstat()
        if root_status.st_uid != os.geteuid() or stat.S_IMODE(root_status.st_mode) != 0o700:
            raise RecoveryFailure("configuration_error", "run_root_boundary_invalid")
        marker_path = root / "ownership.json"
        marker_payload = (
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "task_owned_squeez_recovery_run",
                    "run_id": run_id,
                    "nonce": secrets.token_hex(16),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        marker = exclusive_write(marker_path, marker_payload)
        directories = {
            "home": root / "home",
            "cwd": root / "cwd",
            "xdg_config": root / "xdg" / "config",
            "xdg_data": root / "xdg" / "data",
            "xdg_cache": root / "xdg" / "cache",
            "xdg_runtime": root / "xdg" / "runtime",
            "temporary": root / "tmp",
        }
        (root / "xdg").mkdir(mode=0o700)
        for directory in directories.values():
            directory.mkdir(mode=0o700)
        return cls(
            task_root=task_root,
            root=root,
            home=directories["home"],
            cwd=directories["cwd"],
            xdg_config=directories["xdg_config"],
            xdg_data=directories["xdg_data"],
            xdg_cache=directories["xdg_cache"],
            xdg_runtime=directories["xdg_runtime"],
            temporary=directories["temporary"],
            marker_path=marker_path,
            marker=marker,
            root_device=root_status.st_dev,
            root_inode=root_status.st_ino,
            run_id=run_id,
        )

    @property
    def vendor_store(self) -> Path:
        return self.home / ".claude" / "squeez"

    @property
    def vendor_blobs(self) -> Path:
        return self.vendor_store / "blobs"

    def verify(self) -> None:
        _ensure_no_symlink_components(self.root, self.task_root)
        metadata = self.root.lstat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise RecoveryFailure("configuration_error", "run_root_not_directory")
        if metadata.st_dev != self.root_device or metadata.st_ino != self.root_inode:
            raise RecoveryFailure("configuration_error", "run_root_identity_changed")
        marker_status = self.marker_path.lstat()
        if (
            not stat.S_ISREG(marker_status.st_mode)
            or marker_status.st_nlink != 1
            or marker_status.st_uid != os.geteuid()
            or stat.S_IMODE(marker_status.st_mode) != 0o600
        ):
            raise RecoveryFailure("configuration_error", "ownership_marker_boundary_drift")
        if fingerprint_file(self.marker_path) != self.marker:
            raise RecoveryFailure("configuration_error", "ownership_marker_drift")

    def environment(self) -> dict[str, str]:
        return {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.home),
            "LANG": "C.UTF-8",
            "XDG_CONFIG_HOME": str(self.xdg_config),
            "XDG_DATA_HOME": str(self.xdg_data),
            "XDG_CACHE_HOME": str(self.xdg_cache),
            "XDG_RUNTIME_DIR": str(self.xdg_runtime),
            "TMPDIR": str(self.temporary),
            "NO_COLOR": "1",
            "DO_NOT_TRACK": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }


class SqueezMcpSupplier:
    backend = "pinned_squeez_task_owned_stdio"

    def __init__(
        self,
        *,
        binary: Path,
        expected_binary: Fingerprint,
        layout: RunLayout,
        timeout_seconds: float,
        stdout_limit_bytes: int,
        stderr_limit_bytes: int,
    ) -> None:
        expected_binary.validate()
        self.binary = binary
        self.expected_binary = expected_binary
        self.layout = layout
        self.timeout_seconds = timeout_seconds
        self.stdout_limit_bytes = stdout_limit_bytes
        self.stderr_limit_bytes = stderr_limit_bytes
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise RecoveryFailure("configuration_error", "supplier_timeout_invalid")
        if any(type(value) is not int or value <= 0 for value in (stdout_limit_bytes, stderr_limit_bytes)):
            raise RecoveryFailure("configuration_error", "supplier_output_limit_invalid")
        self.calls = 0
        self.active_pids: set[int] = set()
        self.observations: list[ProcessObservation] = []

    def verify_binary(self) -> None:
        if fingerprint_file(self.binary) != self.expected_binary:
            raise RecoveryFailure("configuration_error", "supplier_binary_drift")
        if not os.access(self.binary, os.X_OK):
            raise RecoveryFailure("configuration_error", "supplier_binary_not_executable")

    def assert_idle(self) -> None:
        if self.active_pids:
            raise RecoveryFailure("not_available", "supplier_process_still_active")

    def recover(self, record: HandleRecord) -> SupplierEnvelope:
        self.layout.verify()
        self.verify_binary()
        request = squeez_mcp_request(record.supplier_key)
        self.calls += 1
        started = time.monotonic_ns()
        process = subprocess.Popen(
            [str(self.binary), "mcp"],
            cwd=self.layout.cwd,
            env=self.layout.environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        self.active_pids.add(process.pid)
        timed_out = False
        try:
            try:
                stdout, stderr = process.communicate(input=request, timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate()
        finally:
            self.active_pids.discard(process.pid)
        elapsed = (time.monotonic_ns() - started) / 1_000_000_000
        observation = ProcessObservation(
            pid=process.pid,
            exit_code=process.returncode,
            timed_out=timed_out,
            waited=process.poll() is not None,
            wall_seconds=round(elapsed, 9),
            stdout=Fingerprint(len(stdout), digest(stdout)),
            stderr=Fingerprint(len(stderr), digest(stderr)),
        )
        self.observations.append(observation)
        if len(stdout) > self.stdout_limit_bytes or len(stderr) > self.stderr_limit_bytes:
            return SupplierEnvelope("output_limit_exceeded", None, observation)
        return classify_squeez_mcp_response(stdout, stderr, record.supplier_key, observation)


def make_squeez_mcp_supplier(
    ledger_path: Path,
    layout: RunLayout,
    environment: Mapping[str, str] = os.environ,
) -> SqueezMcpSupplier:
    policy = load_recovery_policy(ledger_path)
    if not policy.enabled:
        raise RecoveryFailure("feature_disabled", "recovery_ledger_disabled")
    specification = load_supplier_spec(ledger_path)
    return SqueezMcpSupplier(
        binary=specification.resolve_binary(environment),
        expected_binary=specification.fingerprint,
        layout=layout,
        timeout_seconds=policy.supplier_timeout_seconds,
        stdout_limit_bytes=policy.supplier_stdout_limit_bytes,
        stderr_limit_bytes=policy.supplier_stderr_limit_bytes,
    )


@dataclass(frozen=True)
class RecoveryDecision:
    status: str
    complete: bool
    content: bytes | None
    public_error: str | None
    private_reason: str
    supplier_invoked: bool
    supplier_observation: ProcessObservation | None = None
    original: Fingerprint | None = None
    range_start: int | None = None
    range_end: int | None = None
    chunk_sha256: str | None = None
    next_cursor: str | None = None
    remaining_calls: int | None = None
    remaining_total_bytes: int | None = None
    trial_remaining_supplier_calls: int | None = None
    trial_remaining_recovered_bytes: int | None = None

    @classmethod
    def error(
        cls,
        public_error: str,
        private_reason: str,
        *,
        supplier_invoked: bool = False,
        observation: ProcessObservation | None = None,
    ) -> "RecoveryDecision":
        return cls(
            status="error",
            complete=False,
            content=None,
            public_error=public_error,
            private_reason=private_reason,
            supplier_invoked=supplier_invoked,
            supplier_observation=observation,
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "complete": self.complete,
            "public_error": self.public_error,
            "private_reason": self.private_reason,
            "supplier_invoked": self.supplier_invoked,
            "supplier_observation": None if self.supplier_observation is None else self.supplier_observation.as_dict(),
            "content": (
                None
                if self.content is None
                else Fingerprint(len(self.content), digest(self.content)).as_dict()
            ),
            "original": None if self.original is None else self.original.as_dict(),
            "range_start": self.range_start,
            "range_end": self.range_end,
            "chunk_sha256": self.chunk_sha256,
            "next_cursor": self.next_cursor,
            "remaining_calls": self.remaining_calls,
            "remaining_total_bytes": self.remaining_total_bytes,
            "trial_remaining_supplier_calls": self.trial_remaining_supplier_calls,
            "trial_remaining_recovered_bytes": self.trial_remaining_recovered_bytes,
        }


class RecoveryAdapter:
    def __init__(
        self,
        *,
        policy: RecoveryPolicy,
        registry: RecoveryRegistry,
        supplier: Supplier,
        clock: Callable[[], float] = time.time,
    ) -> None:
        policy.validate()
        self.policy = policy
        self.registry = registry
        self.supplier = supplier
        self.clock = clock

    @staticmethod
    def _parse_request(payload: dict[str, Any]) -> tuple[str, str | None]:
        if not isinstance(payload, dict) or set(payload) - REQUEST_FIELDS or "handle" not in payload:
            raise RecoveryFailure("invalid_request", "caller_fields_rejected")
        handle = payload["handle"]
        cursor = payload.get("cursor")
        if not isinstance(handle, str) or HANDLE_PATTERN.fullmatch(handle) is None:
            raise RecoveryFailure("invalid_request", "caller_handle_invalid")
        if cursor is not None and (not isinstance(cursor, str) or not cursor):
            raise RecoveryFailure("invalid_request", "caller_cursor_invalid")
        return handle, cursor

    @staticmethod
    def _cursor(record: HandleRecord, offset: int) -> str:
        material = f"{record.handle}|{record.ownership_epoch}|{offset}".encode("utf-8")
        return "cursor-" + digest(material)[:24]

    @staticmethod
    def _chunk_end(content: bytes, start: int, maximum: int) -> int:
        end = min(len(content), start + maximum)
        while end > start:
            try:
                content[start:end].decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                end -= 1
                continue
            return end
        raise RecoveryFailure("limit_reached", "response_limit_cannot_fit_utf8_scalar")

    def recover(self, *, context: TrustedContext, request: dict[str, Any]) -> RecoveryDecision:
        if not self.policy.enabled:
            return RecoveryDecision.error("feature_disabled", "feature_disabled")
        try:
            handle, cursor = self._parse_request(request)
            context.validate(allow_missing_epoch=True)
        except RecoveryFailure as error:
            return RecoveryDecision.error(error.public_error, error.reason)
        if self.policy.required_permission not in context.permissions:
            return RecoveryDecision.error("not_available", "permission_denied")
        if context.ownership_epoch is None:
            return RecoveryDecision.error("not_available", "restart_ownership_unverified")
        record = self.registry.get(handle)
        if record is None:
            return RecoveryDecision.error("not_available", "missing_handle")
        comparisons = (
            (context.caller_id, record.caller_id, "ownership_mismatch"),
            (context.run_id, record.run_id, "run_mismatch"),
            (context.trial_id, record.trial_id, "trial_mismatch"),
            (context.ownership_epoch, record.ownership_epoch, "restart_ownership_unverified"),
        )
        for observed, expected, reason in comparisons:
            if observed != expected:
                return RecoveryDecision.error("not_available", reason)
        if record.state in {"revoked", "expired", "closed"}:
            return RecoveryDecision.error("not_available", f"handle_{record.state}")
        if record.state == "fully_delivered":
            return RecoveryDecision.error("not_available", "already_fully_delivered")
        current_time = self.clock()
        if current_time >= record.created_at + self.policy.retention_seconds:
            record.state = "expired"
            return RecoveryDecision.error("not_available", "source_retention_expired")
        if current_time >= record.created_at + self.policy.ttl_seconds:
            record.state = "expired"
            return RecoveryDecision.error("not_available", "handle_expired")
        expected_cursor = None if record.next_offset == 0 else record.next_cursor
        if cursor != expected_cursor:
            return RecoveryDecision.error("invalid_request", "cursor_mismatch")
        if record.calls >= self.policy.max_calls_per_handle:
            return RecoveryDecision.error("limit_reached", "handle_call_limit_reached")
        remaining_total = self.policy.max_total_bytes_per_handle - record.delivered_bytes
        if remaining_total <= 0:
            return RecoveryDecision.error("limit_reached", "handle_total_bytes_limit_reached")
        planned_bytes = min(
            self.policy.max_response_bytes,
            remaining_total,
            record.original.bytes - record.next_offset,
        )
        trial_usage = self.registry.usage(record.run_id, record.trial_id)
        if trial_usage.supplier_calls >= self.policy.max_supplier_calls_per_trial:
            return RecoveryDecision.error("limit_reached", "trial_supplier_call_quota_reached")
        if trial_usage.recovered_bytes + planned_bytes > self.policy.max_recovered_bytes_per_trial:
            return RecoveryDecision.error("limit_reached", "trial_recovered_bytes_quota_reached")
        before_calls = self.supplier.calls
        record.calls += 1
        trial_usage.supplier_calls += 1
        try:
            envelope = self.supplier.recover(record)
        except RecoveryFailure as error:
            return RecoveryDecision.error(
                error.public_error,
                error.reason,
                supplier_invoked=self.supplier.calls == before_calls + 1,
            )
        supplier_invoked = self.supplier.calls == before_calls + 1
        if not supplier_invoked:
            return RecoveryDecision.error("integrity_failure", "supplier_call_not_observed")
        if envelope.outcome == "not_found":
            return RecoveryDecision.error(
                "not_available",
                "supplier_not_found",
                supplier_invoked=True,
                observation=envelope.observation,
            )
        if envelope.outcome != "recovered":
            return RecoveryDecision.error(
                "integrity_failure",
                f"supplier_{envelope.outcome}",
                supplier_invoked=True,
                observation=envelope.observation,
            )
        content = envelope.content
        if not isinstance(content, bytes) or not content:
            return RecoveryDecision.error(
                "integrity_failure",
                "supplier_content_missing",
                supplier_invoked=True,
                observation=envelope.observation,
            )
        try:
            content.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return RecoveryDecision.error(
                "integrity_failure",
                "supplier_content_not_strict_utf8",
                supplier_invoked=True,
                observation=envelope.observation,
            )
        if Fingerprint(len(content), digest(content)) != record.original:
            return RecoveryDecision.error(
                "integrity_failure",
                "supplier_content_fingerprint_mismatch",
                supplier_invoked=True,
                observation=envelope.observation,
            )
        try:
            end = self._chunk_end(content, record.next_offset, planned_bytes)
        except RecoveryFailure as error:
            return RecoveryDecision.error(
                error.public_error, error.reason, supplier_invoked=True, observation=envelope.observation
            )
        start = record.next_offset
        chunk = content[start:end]
        complete = end == len(content)
        record.delivered_bytes += len(chunk)
        record.next_offset = end
        record.next_cursor = None if complete else self._cursor(record, end)
        record.state = "fully_delivered" if complete else "partially_delivered"
        trial_usage.recovered_bytes += len(chunk)
        return RecoveryDecision(
            status="full" if complete else "partial",
            complete=complete,
            content=chunk,
            public_error=None,
            private_reason="recovery_full" if complete else "recovery_partial",
            supplier_invoked=True,
            supplier_observation=envelope.observation,
            original=record.original,
            range_start=start,
            range_end=end,
            chunk_sha256=digest(chunk),
            next_cursor=record.next_cursor,
            remaining_calls=self.policy.max_calls_per_handle - record.calls,
            remaining_total_bytes=self.policy.max_total_bytes_per_handle - record.delivered_bytes,
            trial_remaining_supplier_calls=self.policy.max_supplier_calls_per_trial - trial_usage.supplier_calls,
            trial_remaining_recovered_bytes=self.policy.max_recovered_bytes_per_trial - trial_usage.recovered_bytes,
        )


@dataclass(frozen=True)
class CleanupEntry:
    name: str
    fingerprint: Fingerprint
    device: int
    inode: int
    owner_uid: int


@dataclass(frozen=True)
class VendorCleanupPlan:
    directory: Path
    directory_device: int
    directory_inode: int
    expected_uid: int
    entries: tuple[CleanupEntry, ...]


def plan_vendor_cleanup(layout: RunLayout, supplier_key: str, supplier: SqueezMcpSupplier) -> VendorCleanupPlan:
    supplier.assert_idle()
    layout.verify()
    if SUPPLIER_KEY_PATTERN.fullmatch(supplier_key) is None:
        raise RecoveryFailure("configuration_error", "supplier_key_invalid")
    directory = layout.vendor_blobs
    _ensure_no_symlink_components(directory, layout.root)
    metadata = directory.lstat()
    expected_uid = os.geteuid()
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != expected_uid:
        raise RecoveryFailure("not_available", "vendor_blob_directory_invalid")
    expected_names = {supplier_key, f"{supplier_key}.idx"}
    if set(os.listdir(directory)) != expected_names:
        raise RecoveryFailure("not_available", "unexpected_vendor_blob_entry")
    entries: list[CleanupEntry] = []
    for name in sorted(expected_names, key=os.fsencode):
        path = directory / name
        item = path.lstat()
        if not stat.S_ISREG(item.st_mode) or stat.S_ISLNK(item.st_mode):
            raise RecoveryFailure("not_available", "cleanup_target_not_regular")
        if item.st_uid != expected_uid or item.st_nlink != 1:
            raise RecoveryFailure("not_available", "cleanup_target_ownership_or_link_invalid")
        entries.append(CleanupEntry(name, fingerprint_file(path), item.st_dev, item.st_ino, item.st_uid))
    return VendorCleanupPlan(directory, metadata.st_dev, metadata.st_ino, expected_uid, tuple(entries))


def execute_vendor_cleanup(plan: VendorCleanupPlan, supplier: SqueezMcpSupplier) -> tuple[CleanupEntry, ...]:
    supplier.assert_idle()
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    file_descriptor = os.open(plan.directory, flags)
    try:
        directory_status = os.fstat(file_descriptor)
        if (
            directory_status.st_dev != plan.directory_device
            or directory_status.st_ino != plan.directory_inode
            or directory_status.st_uid != plan.expected_uid
        ):
            raise RecoveryFailure("not_available", "cleanup_directory_identity_changed")
        if set(os.listdir(file_descriptor)) != {entry.name for entry in plan.entries}:
            raise RecoveryFailure("not_available", "cleanup_tree_changed_before_delete")
        opened: list[tuple[CleanupEntry, int]] = []
        try:
            for entry in plan.entries:
                descriptor = os.open(
                    entry.name,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=file_descriptor,
                )
                metadata = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_nlink != 1
                    or metadata.st_uid != entry.owner_uid
                    or metadata.st_dev != entry.device
                    or metadata.st_ino != entry.inode
                ):
                    os.close(descriptor)
                    raise RecoveryFailure("not_available", "cleanup_target_identity_changed")
                payload = _read_descriptor(descriptor)
                if Fingerprint(len(payload), digest(payload)) != entry.fingerprint:
                    os.close(descriptor)
                    raise RecoveryFailure("not_available", "cleanup_target_drift")
                named = os.stat(entry.name, dir_fd=file_descriptor, follow_symlinks=False)
                if named.st_dev != entry.device or named.st_ino != entry.inode or named.st_nlink != 1:
                    os.close(descriptor)
                    raise RecoveryFailure("not_available", "cleanup_target_identity_changed")
                opened.append((entry, descriptor))
            for entry, descriptor in opened:
                os.close(descriptor)
                os.unlink(entry.name, dir_fd=file_descriptor)
            opened.clear()
            os.fsync(file_descriptor)
        finally:
            for _entry, descriptor in opened:
                os.close(descriptor)
        if os.listdir(file_descriptor):
            raise RecoveryFailure("not_available", "vendor_blob_directory_not_empty")
    finally:
        os.close(file_descriptor)
    return plan.entries
