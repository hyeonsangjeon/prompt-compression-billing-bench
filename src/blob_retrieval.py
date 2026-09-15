"""Atomic local result spooling with background Azure Blob upload."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import format_datetime
import hashlib
import http.client
import io
import json
import math
import os
from pathlib import Path
from queue import Empty, Queue
import re
import secrets
import shutil
import socket
import tarfile
import threading
import time
import urllib.parse
import urllib.request

from accounting import now
from .contracts import safe_child
from .protection import digest


class BlobUploadError(RuntimeError):
    def __init__(self, status: int, category: str):
        super().__init__(f"Blob upload failed with HTTP {status}")
        self.status = status
        self.category = category


def file_digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def error_category(error: BaseException) -> str:
    if isinstance(error, BlobUploadError):
        return error.category
    if isinstance(error, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(error, OSError):
        return "network_or_local_io"
    return type(error).__name__


class StorageManagedIdentity:
    def __init__(self):
        self.token = ""
        self.expires = 0
        self.lock = threading.Lock()

    def __call__(self) -> str:
        with self.lock:
            if time.time() >= self.expires - 300:
                query = urllib.parse.urlencode({
                    "api-version": "2018-02-01", "resource": "https://storage.azure.com/",
                })
                request = urllib.request.Request(
                    "http://169.254.169.254/metadata/identity/oauth2/token?" + query,
                    headers={"Metadata": "true"},
                )
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(request, timeout=15) as response:
                    record = json.load(response)
                self.token, self.expires = record["access_token"], int(record["expires_on"])
        return self.token


class AzureBlobClient:
    def __init__(self, account_url: str, container: str, token=None, timeout_seconds: int = 300):
        parsed = urllib.parse.urlsplit(account_url)
        if (
            parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path.rstrip("/")
            or not parsed.hostname.endswith(".blob.core.windows.net")
        ):
            raise ValueError("Use an explicit Azure Blob HTTPS account URL without credentials or a path")
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?", container):
            raise ValueError("Blob container name is invalid")
        if type(timeout_seconds) is not int or timeout_seconds < 1:
            raise ValueError("Blob timeout must be a positive integer")
        self.account_url = account_url.rstrip("/")
        self.hostname = parsed.hostname
        self.port = parsed.port
        self.container = container
        self.token = token or StorageManagedIdentity()
        self.timeout_seconds = timeout_seconds

    def _path(self, blob: str) -> str:
        if not isinstance(blob, str) or not blob or blob.startswith("/") or any(
            part in ("", ".", "..") for part in blob.split("/")
        ):
            raise ValueError("Blob name must be a safe relative path")
        return "/" + urllib.parse.quote(self.container, safe="") + "/" + "/".join(
            urllib.parse.quote(part, safe="") for part in blob.split("/")
        )

    def _put(self, blob: str, body, length: int, sha256: str, content_type: str) -> dict:
        if type(length) is not int or length < 0 or not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError("Blob payload length or SHA-256 is invalid")
        connection = http.client.HTTPSConnection(self.hostname, self.port, timeout=self.timeout_seconds)
        headers = {
            "Authorization": "Bearer " + self.token(),
            "Content-Length": str(length),
            "Content-Type": content_type,
            "x-ms-blob-type": "BlockBlob",
            "x-ms-date": format_datetime(datetime.now(timezone.utc), usegmt=True),
            "x-ms-meta-sha256": sha256,
            "x-ms-version": "2023-11-03",
        }
        try:
            connection.request("PUT", self._path(blob), body=body, headers=headers)
            response = connection.getresponse()
            response.read(65536)
            if response.status != 201:
                category = (
                    "authentication_or_authorization" if response.status in (401, 403)
                    else "rate_limited" if response.status == 429
                    else "service_unavailable" if response.status >= 500
                    else f"http_{response.status}"
                )
                raise BlobUploadError(response.status, category)
            return {
                "etag": response.getheader("ETag"),
                "request_id": response.getheader("x-ms-request-id"),
                "bytes": length,
            }
        finally:
            connection.close()

    def put_file(self, blob: str, path: Path, sha256: str) -> dict:
        size = path.stat().st_size
        with path.open("rb") as handle:
            return self._put(blob, handle, size, sha256, "application/x-tar")

    def put_bytes(self, blob: str, payload: bytes) -> dict:
        return self._put(blob, payload, len(payload), digest(payload), "application/json")

    def verify_blob(self, blob: str, expected_bytes: int, expected_sha256: str) -> dict:
        if type(expected_bytes) is not int or expected_bytes < 0 or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise ValueError("Expected Blob identity is invalid")
        connection = http.client.HTTPSConnection(self.hostname, self.port, timeout=self.timeout_seconds)
        headers = {
            "Authorization": "Bearer " + self.token(),
            "x-ms-date": format_datetime(datetime.now(timezone.utc), usegmt=True),
            "x-ms-version": "2023-11-03",
        }
        checksum = hashlib.sha256()
        total = 0
        try:
            connection.request("GET", self._path(blob), headers=headers)
            response = connection.getresponse()
            if response.status != 200:
                response.read(65536)
                raise BlobUploadError(response.status, f"remote_verify_http_{response.status}")
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                checksum.update(block)
                total += len(block)
            actual_sha256 = checksum.hexdigest()
            if total != expected_bytes or actual_sha256 != expected_sha256:
                raise ValueError("Remote Blob content differs from the uploaded payload")
            return {
                "bytes": total,
                "sha256": actual_sha256,
                "request_id": response.getheader("x-ms-request-id"),
            }
        finally:
            connection.close()


def _add_bytes(archive: tarfile.TarFile, name: str, content: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    info.mode = 0o600
    info.mtime = 0
    archive.addfile(info, io.BytesIO(content))


def _files(path: Path):
    if path.is_symlink():
        raise ValueError("Retrieval snapshots do not follow symlinks")
    if path.is_file():
        yield path
        return
    if not path.is_dir():
        raise ValueError("Retrieval snapshot source is not a regular file or directory")
    for child in sorted(path.rglob("*")):
        if child.is_symlink():
            raise ValueError("Retrieval snapshots do not follow symlinks")
        if child.is_file():
            yield child


class BlobSpool:
    def __init__(self, root: Path, run_id: str, source_commit: str, ledger_sha256: str,
                 condition: str, client, *, prefix: str, maximum_attempts: int,
                 initial_backoff_seconds: float, maximum_backoff_seconds: float):
        if not root.is_absolute() or root.is_symlink():
            raise ValueError("Blob spool root must be an absolute non-symlink path")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{2,127}", run_id):
            raise ValueError("Run identifier is not safe for a spool path")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,31}", condition):
            raise ValueError("Condition is not safe for a spool path")
        if not re.fullmatch(r"[0-9a-f]{40}", source_commit) or not re.fullmatch(r"[0-9a-f]{64}", ledger_sha256):
            raise ValueError("Spool source lineage is invalid")
        if not isinstance(prefix, str) or not prefix or any(part in ("", ".", "..") for part in prefix.split("/")):
            raise ValueError("Blob prefix must be a safe relative path")
        if type(maximum_attempts) is not int or maximum_attempts < 1:
            raise ValueError("Blob retries must be a positive integer")
        for value in (initial_backoff_seconds, maximum_backoff_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("Blob retry delays must be finite and nonnegative")
        if initial_backoff_seconds > maximum_backoff_seconds:
            raise ValueError("Initial Blob retry delay exceeds its maximum")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory = root / run_id
        self.directory.mkdir(mode=0o700)
        self.run_id, self.source_commit, self.ledger_sha256 = run_id, source_commit, ledger_sha256
        self.condition, self.client, self.prefix = condition, client, prefix
        self.maximum_attempts = maximum_attempts
        self.initial_backoff_seconds = initial_backoff_seconds
        self.maximum_backoff_seconds = maximum_backoff_seconds
        self.queue = Queue()
        self.items = {}
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.stop_event = threading.Event()
        self.accepting = True
        self.worker = threading.Thread(target=self._worker, name="blob-uploader", daemon=True)
        self.worker.start()

    @property
    def account_url_sha256(self) -> str:
        return digest(self.client.account_url.encode())

    def _remote_base(self, item_id: str) -> str:
        return f"{self.prefix}/{self.source_commit}/{self.run_id}/{self.condition}/{item_id}"

    def _initial_state(self, item_id: str, payload: Path, kind: str, metadata: dict) -> dict:
        remote = self._remote_base(item_id)
        return {
            "schema_version": 1, "kind": kind, "run_id": self.run_id,
            "source_commit": self.source_commit, "ledger_sha256": self.ledger_sha256,
            "condition": self.condition, "item_id": item_id, "metadata": metadata,
            "destination": {
                "account_url_sha256": self.account_url_sha256,
                "container": self.client.container, "prefix": self.prefix,
            },
            "payload": {
                "name": payload.name, "bytes": payload.stat().st_size,
                "sha256": file_digest(payload), "blob": remote + "/payload.tar",
            },
            "manifest_blob": remote + "/manifest.json", "manifest_uploaded_last": True,
            "upload_state": "pending", "attempts": 0, "first_attempt_at": None,
            "last_attempt_at": None, "last_error_category": None,
            "uploaded_at": None, "payload_etag": None, "manifest_etag": None,
            "remote_verified_at": None, "payload_verify_request_id": None,
            "manifest_verify_request_id": None,
            "manifest_bytes": None,
            "operations": {
                name: {"started": 0, "succeeded": 0}
                for name in (
                    "payload_write", "manifest_write",
                    "payload_verify_read", "manifest_verify_read",
                )
            },
        }

    def _finish_stage(self, temporary: Path, target: Path, state: dict) -> dict:
        atomic_json(temporary / "state.json", state)
        os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        with self.changed:
            if not self.accepting:
                raise RuntimeError("Blob spool no longer accepts results")
            self.items[state["item_id"]] = target
            self.queue.put(target)
            self.changed.notify_all()
        return self._public_state(state)

    def stage_file(self, source: Path, item_id: str, *, kind: str, metadata: dict) -> dict:
        if source.is_symlink():
            raise ValueError("Only a regular result payload can be staged")
        source = source.resolve(strict=True)
        if not source.is_file():
            raise ValueError("Only a regular result payload can be staged")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", item_id):
            raise ValueError("Retrieval item identifier is invalid")
        target = self.directory / item_id
        if target.exists() or item_id in self.items:
            raise ValueError("Retrieval item already exists")
        temporary = self.directory / f".{item_id}.{secrets.token_hex(8)}.tmp"
        temporary.mkdir(mode=0o700)
        try:
            payload = temporary / "payload.tar"
            shutil.copyfile(source, payload)
            with payload.open("rb") as handle:
                os.fsync(handle.fileno())
            state = self._initial_state(item_id, payload, kind, metadata)
            return self._finish_stage(temporary, target, state)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def stage_directory(self, source: Path, item_id: str, *, kind: str, metadata: dict) -> dict:
        if source.is_symlink():
            raise ValueError("Only a regular result directory can be staged")
        source = source.resolve(strict=True)
        if not source.is_dir():
            raise ValueError("Only a regular result directory can be staged")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", item_id):
            raise ValueError("Retrieval item identifier is invalid")
        target = self.directory / item_id
        if target.exists() or item_id in self.items:
            raise ValueError("Retrieval item already exists")
        temporary = self.directory / f".{item_id}.{secrets.token_hex(8)}.tmp"
        temporary.mkdir(mode=0o700)
        try:
            payload = temporary / "payload.tar"
            files = list(_files(source))
            inventory = {
                path.relative_to(source).as_posix(): {
                    "bytes": path.stat().st_size,
                    "sha256": file_digest(path),
                }
                for path in files
            }
            with tarfile.open(payload, "w", format=tarfile.PAX_FORMAT, dereference=False) as archive:
                _add_bytes(archive, "retrieval-tree.json", json.dumps(
                    {"kind": kind, "files": inventory}, ensure_ascii=False,
                    sort_keys=True, separators=(",", ":"), allow_nan=False,
                ).encode())
                for path in files:
                    archive.add(path, arcname=path.relative_to(source).as_posix(), recursive=False)
            with payload.open("rb") as handle:
                os.fsync(handle.fileno())
            state = self._initial_state(item_id, payload, kind, {
                **metadata,
                "source_file_count": len(inventory),
                "source_tree_sha256": digest(json.dumps(
                    inventory, sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode()),
            })
            return self._finish_stage(temporary, target, state)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def stage_run_snapshot(self, run_directory: Path, repetition: int, trials: list[dict]) -> dict:
        item_id = f"repetition-{repetition:03d}"
        trial_ids = [trial["trial_id"] for trial in trials]
        if len(trials) != 5 or any(trial["repetition"] != repetition for trial in trials):
            raise ValueError("A retrieval snapshot requires one complete five-task repetition")
        target = self.directory / item_id
        if target.exists() or item_id in self.items:
            raise ValueError("Retrieval repetition already exists")
        temporary = self.directory / f".{item_id}.{secrets.token_hex(8)}.tmp"
        temporary.mkdir(mode=0o700)
        try:
            payload = temporary / "payload.tar"
            events = []
            events_path = run_directory / "transport/events.jsonl"
            if events_path.is_file():
                for line in events_path.read_text(encoding="utf-8").splitlines():
                    event = json.loads(line)
                    if event.get("trial_id") in trial_ids:
                        events.append(line)
            request_paths = []
            for path in sorted((run_directory / "transport").glob("request-*")):
                manifest = path / "manifest.json"
                if manifest.is_file() and json.loads(manifest.read_bytes()).get("trial_id") in trial_ids:
                    request_paths.append(path)
            paths = []
            for name in (
                "ledger.toml", "provenance.json", "execution.json", "task-sources.json",
                "baseline-summary.json", "source", "tasks", "compressor",
            ):
                path = run_directory / name
                if path.exists():
                    paths.append(path)
            for trial_id in trial_ids:
                for name in (f"trials/{trial_id}", f"jobs/{trial_id}"):
                    path = safe_child(run_directory, name)
                    if not path.exists():
                        raise ValueError(f"Completed retrieval trial artifact is missing: {name}")
                    paths.append(path)
            paths.extend(request_paths)
            snapshot = {
                "schema_version": 1, "kind": "native_repetition_snapshot",
                "run_id": self.run_id, "source_commit": self.source_commit,
                "ledger_sha256": self.ledger_sha256, "condition": self.condition,
                "repetition": repetition, "trial_ids": trial_ids,
                "native_rewards": {trial["task"]: trial["native_outcome"]["native_reward"] for trial in trials},
                "created_at": now(),
            }
            with tarfile.open(payload, "w", format=tarfile.PAX_FORMAT, dereference=False) as archive:
                _add_bytes(archive, "retrieval-snapshot.json", json.dumps(
                    snapshot, ensure_ascii=False, indent=2, allow_nan=False
                ).encode() + b"\n")
                if events:
                    _add_bytes(archive, "transport/events.jsonl", ("\n".join(events) + "\n").encode())
                added = set()
                for path in paths:
                    for file in _files(path):
                        relative = file.relative_to(run_directory).as_posix()
                        if relative in added:
                            continue
                        archive.add(file, arcname=relative, recursive=False)
                        added.add(relative)
            with payload.open("rb") as handle:
                os.fsync(handle.fileno())
            state = self._initial_state(item_id, payload, "native_repetition_snapshot", {
                "repetition": repetition, "trial_ids": trial_ids,
            })
            return self._finish_stage(temporary, target, state)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def _write_state(self, directory: Path, state: dict) -> None:
        atomic_json(directory / "state.json", state)
        with self.changed:
            self.changed.notify_all()

    def _blob_operation(self, directory: Path, state: dict, name: str, operation):
        record = state["operations"][name]
        record["started"] += 1
        self._write_state(directory, state)
        result = operation()
        record["succeeded"] += 1
        self._write_state(directory, state)
        return result

    def _upload(self, directory: Path) -> None:
        state_path = directory / "state.json"
        state = json.loads(state_path.read_bytes())
        delay = self.initial_backoff_seconds
        remaining_attempts = self.maximum_attempts
        while remaining_attempts and not self.stop_event.is_set():
            remaining_attempts -= 1
            state["attempts"] += 1
            state["first_attempt_at"] = state["first_attempt_at"] or now()
            state["last_attempt_at"] = now()
            state["upload_state"] = "uploading"
            state["last_error_category"] = None
            self._write_state(directory, state)
            try:
                payload = directory / state["payload"]["name"]
                if payload.stat().st_size != state["payload"]["bytes"] or file_digest(payload) != state["payload"]["sha256"]:
                    raise ValueError("Spool payload changed after atomic staging")
                payload_result = self._blob_operation(
                    directory, state, "payload_write",
                    lambda: self.client.put_file(
                        state["payload"]["blob"], payload, state["payload"]["sha256"]
                    ),
                )
                completed_at = now()
                manifest = {
                    "schema_version": 1, "kind": state["kind"], "status": "complete",
                    "run_id": state["run_id"], "source_commit": state["source_commit"],
                    "ledger_sha256": state["ledger_sha256"], "condition": state["condition"],
                    "item_id": state["item_id"], "metadata": state["metadata"],
                    "payload": state["payload"], "payload_etag": payload_result["etag"],
                    "attempts": state["attempts"], "first_attempt_at": state["first_attempt_at"],
                    "uploaded_at": completed_at, "manifest_uploaded_last": True,
                }
                manifest_bytes = json.dumps(
                    manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode()
                state["manifest_bytes"] = len(manifest_bytes)
                self._write_state(directory, state)
                manifest_result = self._blob_operation(
                    directory, state, "manifest_write",
                    lambda: self.client.put_bytes(state["manifest_blob"], manifest_bytes),
                )
                payload_verification = self._blob_operation(
                    directory, state, "payload_verify_read",
                    lambda: self.client.verify_blob(
                        state["payload"]["blob"], state["payload"]["bytes"], state["payload"]["sha256"]
                    ),
                )
                manifest_verification = self._blob_operation(
                    directory, state, "manifest_verify_read",
                    lambda: self.client.verify_blob(
                        state["manifest_blob"], len(manifest_bytes), digest(manifest_bytes)
                    ),
                )
                state.update(
                    upload_state="uploaded", uploaded_at=completed_at,
                    payload_etag=payload_result["etag"], manifest_etag=manifest_result["etag"],
                    remote_verified_at=now(),
                    payload_verify_request_id=payload_verification.get("request_id"),
                    manifest_verify_request_id=manifest_verification.get("request_id"),
                    last_error_category=None,
                )
                self._write_state(directory, state)
                return
            except BaseException as error:
                state["last_error_category"] = error_category(error)
                state["upload_state"] = (
                    "failed" if not remaining_attempts else "pending"
                )
                self._write_state(directory, state)
                if state["upload_state"] == "failed" or self.stop_event.wait(delay):
                    return
                delay = min(self.maximum_backoff_seconds, max(delay * 2, self.initial_backoff_seconds))

    def _worker(self) -> None:
        while not self.stop_event.is_set():
            try:
                directory = self.queue.get(timeout=0.2)
            except Empty:
                continue
            try:
                self._upload(directory)
            finally:
                self.queue.task_done()
                with self.changed:
                    self.changed.notify_all()

    @staticmethod
    def _public_state(state: dict) -> dict:
        return {key: state[key] for key in (
            "kind", "item_id", "metadata", "destination", "payload", "manifest_blob", "manifest_uploaded_last",
            "upload_state", "attempts", "first_attempt_at", "last_attempt_at",
            "last_error_category", "uploaded_at", "payload_etag", "manifest_etag",
            "remote_verified_at", "payload_verify_request_id", "manifest_verify_request_id",
            "manifest_bytes", "operations",
        )}

    def report(self) -> dict:
        with self.lock:
            records = [
                self._public_state(json.loads((directory / "state.json").read_bytes()))
                for _item_id, directory in sorted(self.items.items())
            ]
        return {
            "schema_version": 1, "kind": "native_blob_retrieval",
            "account_url_sha256": self.account_url_sha256,
            "container": self.client.container, "prefix": self.prefix,
            "run_id": self.run_id, "source_commit": self.source_commit,
            "ledger_sha256": self.ledger_sha256, "condition": self.condition,
            "upload_state": "no_complete_items" if not records else "uploaded" if all(
                record["upload_state"] == "uploaded" and record["remote_verified_at"] for record in records
            ) else "retrieval_pending",
            "items": records, "nas_read_verification": "pending_external",
            "credentials_recorded": False,
        }

    def wait_for_upload(self, item_ids: list[str], wait_seconds: float) -> dict:
        if not item_ids or len(set(item_ids)) != len(item_ids):
            raise ValueError("Blob wait needs unique item identifiers")
        if type(wait_seconds) not in (int, float) or not math.isfinite(wait_seconds) or wait_seconds < 0:
            raise ValueError("Blob wait must be finite and nonnegative")
        with self.changed:
            deadline = time.monotonic() + wait_seconds
            while True:
                report = self.report()
                indexed = {record["item_id"]: record for record in report["items"]}
                if set(item_ids) - set(indexed):
                    raise ValueError("Blob wait item has not been staged")
                selected = [indexed[item_id] for item_id in item_ids]
                if all(record["upload_state"] == "uploaded" and record["remote_verified_at"] for record in selected):
                    return {"status": "uploaded", "items": selected}
                if any(record["upload_state"] == "failed" for record in selected):
                    return {"status": "retrieval_pending", "items": selected}
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {"status": "retrieval_pending", "items": selected}
                self.changed.wait(min(remaining, 0.5))

    @classmethod
    def resume(cls, directory: Path, client, *, prefix: str, maximum_attempts: int,
               initial_backoff_seconds: float, maximum_backoff_seconds: float,
               accepting: bool = False):
        if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
            raise ValueError("Resume requires an existing absolute non-symlink spool directory")
        state_paths = sorted(directory.glob("*/state.json"))
        if not state_paths:
            raise ValueError("Resume found no staged Blob items")
        states = [json.loads(path.read_bytes()) for path in state_paths]
        first = states[0]
        expected_destination = {
            "account_url_sha256": digest(client.account_url.encode()),
            "container": client.container, "prefix": prefix,
        }
        lineage = (first["run_id"], first["source_commit"], first["ledger_sha256"], first["condition"])
        items = {}
        for path, state in zip(state_paths, states, strict=True):
            if (state["run_id"], state["source_commit"], state["ledger_sha256"], state["condition"]) != lineage:
                raise ValueError("Spool resume items have mixed source lineage")
            if state.get("destination") != expected_destination or state["item_id"] != path.parent.name:
                raise ValueError("Spool resume destination or item path differs")
            payload = path.parent / state["payload"]["name"]
            if payload.is_symlink() or not payload.is_file():
                raise ValueError("Spool resume payload is missing or unsafe")
            if payload.stat().st_size != state["payload"]["bytes"] or file_digest(payload) != state["payload"]["sha256"]:
                raise ValueError("Spool resume payload differs from its recorded boundary")
            items[state["item_id"]] = path.parent
        self = cls.__new__(cls)
        self.directory = directory
        self.run_id, self.source_commit, self.ledger_sha256, self.condition = lineage
        self.client, self.prefix = client, prefix
        self.maximum_attempts = maximum_attempts
        self.initial_backoff_seconds = initial_backoff_seconds
        self.maximum_backoff_seconds = maximum_backoff_seconds
        self.queue = Queue()
        self.items = items
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.stop_event = threading.Event()
        self.accepting = accepting
        for path, state in zip(state_paths, states, strict=True):
            if state["upload_state"] != "uploaded":
                state["upload_state"] = "pending"
                atomic_json(path, state)
                self.queue.put(items[state["item_id"]])
        self.worker = threading.Thread(target=self._worker, name="blob-uploader-resume", daemon=True)
        self.worker.start()
        return self

    def finish(self, wait_seconds: float) -> dict:
        if type(wait_seconds) not in (int, float) or not math.isfinite(wait_seconds) or wait_seconds < 0:
            raise ValueError("Blob final wait must be finite and nonnegative")
        with self.changed:
            self.accepting = False
            deadline = time.monotonic() + wait_seconds
            while True:
                report = self.report()
                states = [record["upload_state"] for record in report["items"]]
                if not states or all(state in ("uploaded", "failed") for state in states):
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.changed.wait(min(remaining, 0.5))
        self.stop_event.set()
        self.worker.join(timeout=min(self.client.timeout_seconds + 1, max(wait_seconds, 1)))
        return self.report()


def retrieval_settings(ledger: dict, root: Path) -> dict:
    specification = ledger["retrieval"]
    account_url = os.environ.get(specification["account_url_env"], "")
    spool_value = os.environ.get(specification["spool_root_env"], "")
    if not spool_value or not Path(spool_value).is_absolute():
        raise ValueError("Set an absolute managed-disk Blob spool root")
    spool_root = Path(spool_value)
    try:
        spool_root.resolve().relative_to(root.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("Blob spool must stay outside the source checkout")
    client = AzureBlobClient(
        account_url, specification["container"], timeout_seconds=specification["upload_timeout_seconds"]
    )
    return {"client": client, "spool_root": spool_root, **specification}


def make_blob_spool(settings: dict, run_id: str, source_commit: str,
                    ledger_sha256: str, condition: str) -> BlobSpool:
    return BlobSpool(
        settings["spool_root"], run_id, source_commit, ledger_sha256, condition,
        settings["client"], prefix=settings["prefix"],
        maximum_attempts=settings["maximum_attempts"],
        initial_backoff_seconds=settings["initial_backoff_seconds"],
        maximum_backoff_seconds=settings["maximum_backoff_seconds"],
    )


def resume_blob_spool(settings: dict, directory: Path, *, accepting: bool = False) -> BlobSpool:
    return BlobSpool.resume(
        directory, settings["client"], prefix=settings["prefix"],
        maximum_attempts=settings["maximum_attempts"],
        initial_backoff_seconds=settings["initial_backoff_seconds"],
        maximum_backoff_seconds=settings["maximum_backoff_seconds"],
        accepting=accepting,
    )
