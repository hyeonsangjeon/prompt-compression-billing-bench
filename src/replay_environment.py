"""Docker environment that preserves and replays verifier-visible state."""

from __future__ import annotations

import asyncio
from hashlib import sha256
import io
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import tarfile

from harbor.environments.docker.docker import DockerEnvironment

from .blob_retrieval import atomic_json, file_digest
from .screening_inventory import canonical_json


PSEUDO_FILESYSTEMS = ("/dev", "/proc", "/sys")
SENSITIVE_ENV = re.compile(
    r"(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|CONNECTION_STRING)$", re.IGNORECASE
)


def parse_docker_diff(output: str) -> list[dict]:
    records = []
    for line in output.splitlines():
        if len(line) < 3 or line[0] not in "ACD" or line[1] != " " or not line[2:].startswith("/"):
            raise ValueError("Docker diff output is malformed")
        path = PurePosixPath(line[2:]).as_posix()
        if path == "/" or any(path == prefix or path.startswith(prefix + "/") for prefix in PSEUDO_FILESYSTEMS):
            continue
        records.append({"change": line[0], "path": path})
    return sorted(records, key=lambda record: (record["path"], record["change"]))


def changed_leaf_paths(records: list[dict]) -> list[dict]:
    changed = [record for record in records if record["change"] in ("A", "C")]
    paths = [PurePosixPath(record["path"]) for record in changed]
    changed_paths = set(paths)
    paths_with_changed_descendants = {
        parent
        for path in paths
        for parent in path.parents
        if parent in changed_paths
    }
    return [
        record
        for record, path in zip(changed, paths, strict=True)
        if path not in paths_with_changed_descendants
    ]


def deleted_root_paths(records: list[dict]) -> list[str]:
    deleted = [PurePosixPath(record["path"]) for record in records if record["change"] == "D"]
    deleted_paths = set(deleted)
    return [
        path.as_posix()
        for path in deleted
        if not any(parent in deleted_paths for parent in path.parents)
    ]


def normalized_absolute_paths(paths: list[str]) -> list[str]:
    normalized = []
    for value in paths:
        if "\0" in value:
            raise ValueError("Replay path contains a NUL byte")
        path = PurePosixPath(value)
        if not path.is_absolute() or path == PurePosixPath("/") or ".." in path.parts:
            raise ValueError("Replay paths must be absolute non-root paths")
        normalized.append(path.as_posix())
    if len(set(normalized)) != len(normalized):
        raise ValueError("Replay path list contains duplicates")
    return sorted(normalized)


def outermost_absolute_paths(paths: list[str]) -> list[str]:
    selected = []
    for path in sorted(normalized_absolute_paths(paths), key=lambda value: (value.count("/"), value)):
        if not any(path.startswith(parent.rstrip("/") + "/") for parent in selected):
            selected.append(path)
    return selected


def nul_path_payload(paths: list[str], *, relative: bool) -> bytes:
    normalized = normalized_absolute_paths(paths)
    values = [path.removeprefix("/") if relative else path for path in normalized]
    return b"".join(value.encode() + b"\0" for value in values)


def sorted_mounts(inspect: dict) -> list[dict]:
    mounts = list(inspect.get("Mounts", []))
    return sorted(
        mounts,
        key=lambda mount: (
            str(mount.get("Destination") or ""),
            str(mount.get("Type") or ""),
            str(mount.get("Name") or ""),
        ),
    )


def _archive_member_kind(member: tarfile.TarInfo) -> str:
    if member.isfile():
        return "file"
    if member.isdir():
        return "directory"
    if member.issym():
        return "symlink"
    if member.islnk():
        return "hardlink"
    if member.ischr():
        return "character_device"
    if member.isblk():
        return "block_device"
    if member.isfifo():
        return "fifo"
    return "other"


def archive_inventory(payload: bytes) -> dict:
    entries = []
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError("Replay archive has an unsafe member path")
            record = {
                "path": path.as_posix(),
                "kind": _archive_member_kind(member),
                "mode": member.mode,
                "uid": member.uid,
                "gid": member.gid,
                "size": member.size,
                "link_target": member.linkname or None,
                "sha256": None,
            }
            if member.isfile():
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError("Replay archive regular file has no payload")
                record["sha256"] = sha256(source.read()).hexdigest()
            entries.append(record)
    if len({entry["path"] for entry in entries}) != len(entries):
        raise ValueError("Replay archive contains duplicate member paths")
    entries.sort(key=lambda entry: entry["path"])
    payload_record = {"entries": entries}
    return {
        **payload_record,
        "tree_sha256": sha256(canonical_json(payload_record)).hexdigest(),
    }


def archive_has_members(payload: bytes) -> bool:
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
        return archive.next() is not None


def archive_installation(payload: bytes, target: str) -> tuple[bytes | None, str]:
    target_path = PurePosixPath(target)
    if not target_path.is_absolute() or target_path == PurePosixPath("/"):
        raise ValueError("Replay archive target must be an absolute non-root path")
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
        members = archive.getmembers()
        if not members:
            return None, target_path.parent.as_posix()
        member_paths = [PurePosixPath(member.name) for member in members]
        if any(
            path.is_absolute() or ".." in path.parts or not path.parts
            or path.parts[0] != target_path.name
            for path in member_paths
        ):
            raise ValueError("Replay archive members do not match the target path")

        def link_leaves_archive(member: tarfile.TarInfo, path: PurePosixPath) -> bool:
            if not (member.issym() or member.islnk()):
                return False
            link = PurePosixPath(member.linkname)
            if link.is_absolute():
                return True
            base = PurePosixPath() if member.islnk() else path.parent
            normalized = PurePosixPath(posixpath.normpath((base / link).as_posix()))
            return bool(normalized.parts) and normalized.parts[0] == ".."

        if not any(link_leaves_archive(member, path) for member, path in zip(members, member_paths, strict=True)):
            return payload, target_path.parent.as_posix()

        prefix = target_path.parent.relative_to("/")
        destination = io.BytesIO()
        with tarfile.open(fileobj=destination, mode="w", format=tarfile.PAX_FORMAT) as rebased:
            for member, path in zip(members, member_paths, strict=True):
                linkname = member.linkname
                if member.islnk():
                    link_path = PurePosixPath(linkname)
                    linkname = (
                        link_path.relative_to("/").as_posix()
                        if link_path.is_absolute()
                        else (prefix / link_path).as_posix()
                    )
                replacement = member.replace(
                    name=(prefix / path).as_posix(), linkname=linkname, deep=True,
                )
                replacement.pax_headers.pop("path", None)
                replacement.pax_headers.pop("linkpath", None)
                source = archive.extractfile(member) if member.isfile() else None
                rebased.addfile(replacement, source)
        return destination.getvalue(), "/"


def redact_inspect(document: list[dict]) -> list[dict]:
    redacted = json.loads(json.dumps(document))
    for container in redacted:
        environment = container.get("Config", {}).get("Env")
        if isinstance(environment, list):
            values = []
            for entry in environment:
                name, separator, value = entry.partition("=")
                if separator and SENSITIVE_ENV.search(name):
                    values.append(name + "=sha256:" + sha256(value.encode()).hexdigest())
                else:
                    values.append(entry)
            container["Config"]["Env"] = values
        for mount in container.get("Mounts", []):
            source = mount.get("Source")
            if isinstance(source, str):
                mount["Source"] = "sha256:" + sha256(source.encode()).hexdigest()
        binds = container.get("HostConfig", {}).get("Binds")
        if isinstance(binds, list):
            container["HostConfig"]["Binds"] = [
                "sha256:" + sha256(bind.encode()).hexdigest() for bind in binds
            ]
    return redacted


def verifier_signature(directory: Path, return_code: int) -> dict:
    rewards = None
    reward_source = None
    reward_json = directory / "reward.json"
    reward_text = directory / "reward.txt"
    if reward_json.is_file():
        rewards = json.loads(reward_json.read_bytes())
        reward_source = "reward.json"
    elif reward_text.is_file():
        rewards = {"reward": float(reward_text.read_text().strip())}
        reward_source = "reward.txt"
    ctrf_path = directory / "ctrf.json"
    tests = None
    if ctrf_path.is_file():
        document = json.loads(ctrf_path.read_bytes())
        rows = document.get("results", {}).get("tests")
        if not isinstance(rows, list):
            raise ValueError("Verifier CTRF test list is absent")
        tests = [
            {
                "name": row.get("name"),
                "status": row.get("status"),
                "raw_status": row.get("raw_status"),
            }
            for row in rows
        ]
    return {
        "command_return_code": return_code,
        "reward_source": reward_source,
        "rewards": rewards,
        "tests": tests,
    }


def replay_bundle_manifest(path: Path) -> dict:
    manifests = list(path.glob("*/manifest.json")) if path.name == "workspace-replay" else [path]
    if len(manifests) != 1:
        raise ValueError("Expected exactly one replay manifest")
    manifest_path = manifests[0]
    value = json.loads(manifest_path.read_bytes())
    claimed_hash = value.get("manifest_sha256")
    payload = {key: item for key, item in value.items() if key != "manifest_sha256"}
    if claimed_hash != sha256(canonical_json(payload)).hexdigest():
        raise ValueError("Replay manifest hash differs")
    root = manifest_path.parent
    for name, record in value.get("files", {}).items():
        file_path = root / name
        if file_path.is_symlink() or not file_path.is_file():
            raise ValueError("Replay manifest file is missing or unsafe")
        if file_path.stat().st_size != record["bytes"] or file_digest(file_path) != record["sha256"]:
            raise ValueError("Replay manifest file content differs")
    return value


class PreservingDockerEnvironment(DockerEnvironment):
    """Capture state before verification and repeat the verifier without an agent call."""

    _tests_uploaded = False
    _replay_started = False
    _preparatory_verifier_commands: list[dict]
    _replay_directory: Path | None = None
    _replay_manifest: dict | None = None
    _pending_verifier_replay: dict | None = None

    @staticmethod
    def _safe_name(value: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-.")
        return normalized[:80] or "container"

    @staticmethod
    def _under_mount(path: str, destinations: list[str]) -> bool:
        return any(path == destination or path.startswith(destination + "/") for destination in destinations)

    @staticmethod
    def _contains_mount(path: str, destinations: list[str]) -> bool:
        return any(destination.startswith(path.rstrip("/") + "/") for destination in destinations)

    @staticmethod
    def _verifier_test_command(command: str) -> bool:
        return "/tests/" in command and "/logs/verifier/" in command and not command.lstrip().startswith("chmod ")

    async def _command(
        self,
        arguments: list[str],
        *,
        input_bytes: bytes | None = None,
        timeout: int = 300,
        check: bool = True,
    ) -> tuple[int, bytes]:
        return_code, stdout, stderr = await self._command_streams(
            arguments, input_bytes=input_bytes, timeout=timeout, check=check,
        )
        return return_code, stdout + stderr

    async def _command_streams(
        self,
        arguments: list[str],
        *,
        input_bytes: bytes | None = None,
        timeout: int = 300,
        check: bool = True,
    ) -> tuple[int, bytes, bytes]:
        process = await asyncio.create_subprocess_exec(
            *arguments,
            stdin=asyncio.subprocess.PIPE if input_bytes is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(input_bytes), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise
        if check and process.returncode != 0:
            operation = " ".join(arguments[:2])
            raise RuntimeError(f"Docker evidence command failed: {operation} returned {process.returncode}")
        return process.returncode, stdout, stderr

    async def _archive_paths(
        self,
        container_id: str,
        paths: list[str],
        *,
        recursive: bool = False,
    ) -> tuple[int, bytes, bytes]:
        arguments = [
            "docker", "exec", "-i", container_id,
            "tar", "--create", "--file=-", "--format=pax", "--numeric-owner",
        ]
        if not recursive:
            arguments.append("--no-recursion")
        arguments.extend(["--null", "--verbatim-files-from", "--directory=/", "--files-from=-"])
        return await self._command_streams(
            arguments,
            input_bytes=nul_path_payload(paths, relative=True),
            timeout=600,
            check=False,
        )

    async def _archive_image_paths(
        self,
        image_id: str,
        paths: list[str],
        *,
        recursive: bool,
    ) -> tuple[int, bytes, bytes]:
        arguments = [
            "docker", "run", "--rm", "-i", "--network", "none", "--user", "0",
            "--entrypoint", "tar", image_id,
            "--create", "--file=-", "--format=pax", "--numeric-owner",
        ]
        if not recursive:
            arguments.append("--no-recursion")
        arguments.extend(["--null", "--verbatim-files-from", "--directory=/", "--files-from=-"])
        return await self._command_streams(
            arguments,
            input_bytes=nul_path_payload(paths, relative=True),
            timeout=600,
            check=False,
        )

    async def _special_path_kinds(self, container_id: str, paths: list[str]) -> list[dict]:
        if not paths:
            return []
        script = """
set -euo pipefail
while IFS= read -r -d '' path; do
    if [[ -S "$path" ]]; then kind=socket
    elif [[ -p "$path" ]]; then kind=fifo
    elif [[ -b "$path" ]]; then kind=block_device
    elif [[ -c "$path" ]]; then kind=character_device
    elif [[ -L "$path" ]]; then kind=symlink
    elif [[ -f "$path" ]]; then kind=file
    elif [[ -d "$path" ]]; then kind=directory
    else kind=missing
    fi
    printf '%s\\0%s\\0' "$path" "$kind"
done
""".strip()
        return_code, stdout, stderr = await self._command_streams(
            ["docker", "exec", "-i", container_id, "bash", "-c", script],
            input_bytes=nul_path_payload(paths, relative=False),
            check=False,
        )
        if return_code != 0 or stderr:
            raise RuntimeError("Could not classify unarchived replay paths")
        fields = stdout.split(b"\0")
        if fields[-1:] == [b""]:
            fields.pop()
        if len(fields) % 2:
            raise ValueError("Special-path classification output is malformed")
        records = [
            {"path": fields[index].decode(), "kind": fields[index + 1].decode()}
            for index in range(0, len(fields), 2)
        ]
        if [record["path"] for record in records] != normalized_absolute_paths(paths):
            raise ValueError("Special-path classification changed path order")
        return records

    async def _remove_paths(self, container_id: str, paths: list[str]) -> None:
        if not paths:
            return
        roots = outermost_absolute_paths(paths)
        return_code, output = await self._command(
            ["docker", "exec", container_id, "find", *roots, "-depth", "-delete"],
            check=False,
        )
        if return_code != 0:
            raise RuntimeError(f"Could not reset verifier-visible paths: {output.decode(errors='replace').strip()}")

    async def _install_root_archive(self, container_id: str, payload: bytes) -> None:
        inventory = archive_inventory(payload)
        if not inventory["entries"]:
            return
        return_code, output = await self._command(
            ["docker", "cp", "-", f"{container_id}:/"],
            input_bytes=payload,
            timeout=600,
            check=False,
        )
        if return_code != 0:
            raise RuntimeError(
                "Could not install a root replay archive: " + output.decode(errors="replace").strip()
            )

    async def _archive_path(self, container_id: str, source: str) -> tuple[int, bytes]:
        return await self._command(
            ["docker", "cp", f"{container_id}:{source}", "-"], timeout=600, check=False
        )

    async def _copy_path(self, container_id: str, source: str, target: Path) -> dict:
        return_code, payload = await self._archive_path(container_id, source)
        record = {"source": source, "return_code": return_code, "payload": None}
        if return_code == 0:
            inventory = archive_inventory(payload)
            target.write_bytes(payload)
            record["payload"] = {
                "path": target.name,
                "bytes": len(payload),
                "sha256": sha256(payload).hexdigest(),
                "format": "docker_cp_tar_stream",
                "tree_sha256": inventory["tree_sha256"],
                "entries": inventory["entries"],
            }
        return record

    async def _container_details(self, container_id: str) -> tuple[list[dict], list[dict], int, bytes]:
        _, inspect_bytes = await self._command(["docker", "inspect", container_id])
        inspect = json.loads(inspect_bytes)
        if not isinstance(inspect, list) or len(inspect) != 1:
            raise ValueError("Docker inspect did not return exactly one container")
        _, diff_bytes = await self._command(["docker", "diff", container_id])
        diff = parse_docker_diff(diff_bytes.decode())
        process_code, process_bytes = await self._command(
            ["docker", "top", container_id, "-eo", "pid,ppid,user,stat,lstart,cmd"], check=False
        )
        return inspect, diff, process_code, process_bytes

    async def _root_snapshot(
        self,
        container_id: str,
        diff: list[dict],
        mount_destinations: list[str],
        target: Path | None = None,
    ) -> tuple[dict, list[dict]]:
        changed = [
            entry for entry in diff
            if entry["change"] in ("A", "C")
            and not self._under_mount(entry["path"], mount_destinations)
        ]
        paths = [entry["path"] for entry in changed]
        return_code, payload, stderr = await self._archive_paths(container_id, paths)
        inventory = archive_inventory(payload)
        entries = {"/" + entry["path"].lstrip("/"): entry for entry in inventory["entries"]}
        missing = [path for path in normalized_absolute_paths(paths) if path not in entries]
        special_paths = await self._special_path_kinds(container_id, missing)
        unsupported = [record for record in special_paths if record["kind"] != "socket"]
        if target is not None:
            target.write_bytes(payload)
            if stderr:
                target.with_suffix(target.suffix + ".stderr").write_bytes(stderr)
        records = []
        for record in changed:
            entry = entries.get(record["path"])
            entry_payload = {"entries": [entry]} if entry is not None else None
            special = next((item for item in special_paths if item["path"] == record["path"]), None)
            records.append({
                **record,
                "kind": entry["kind"] if entry is not None else (special or {}).get("kind"),
                "tree_sha256": sha256(canonical_json(entry_payload)).hexdigest() if entry_payload else None,
                "archived": entry is not None,
            })
        snapshot = {
            "status": "complete" if return_code == 0 and not unsupported else "incomplete",
            "return_code": return_code,
            "requested_path_count": len(paths),
            "archived_path_count": len(entries),
            "unarchived_special_paths": special_paths,
            "stderr_sha256": sha256(stderr).hexdigest() if stderr else None,
            "payload": {
                "path": target.name if target is not None else None,
                "bytes": len(payload),
                "sha256": sha256(payload).hexdigest(),
                "format": "gnu_tar_nul_path_list_no_recursion",
                "tree_sha256": inventory["tree_sha256"],
                "entries": len(inventory["entries"]),
            },
        }
        return snapshot, records

    async def _capture_container(self, container_id: str, directory: Path) -> dict:
        inspect, diff, process_code, process_bytes = await self._container_details(container_id)
        safe_name = self._safe_name(inspect[0].get("Name", "").lstrip("/") or container_id[:12])
        container_directory = directory / safe_name
        container_directory.mkdir()
        atomic_json(container_directory / "inspect.json", redact_inspect(inspect))
        atomic_json(container_directory / "diff.json", {"entries": diff})
        (container_directory / "processes.txt").write_bytes(process_bytes)
        logs_code, logs_bytes = await self._command(["docker", "logs", container_id], check=False)
        (container_directory / "container.log").write_bytes(logs_bytes)
        mounts_in_order = sorted_mounts(inspect[0])
        mount_destinations = [
            mount.get("Destination")
            for mount in mounts_in_order
            if isinstance(mount.get("Destination"), str)
        ]
        root_snapshot, changed = await self._root_snapshot(
            container_id, diff, mount_destinations, container_directory / "root-snapshot.tar",
        )
        mounts = []
        for index, mount in enumerate(mounts_in_order):
            record = {
                "type": mount.get("Type"),
                "destination": mount.get("Destination"),
                "name": mount.get("Name"),
                "read_write": mount.get("RW"),
                "propagation": mount.get("Propagation"),
            }
            source = mount.get("Source")
            if isinstance(source, str):
                record["source_sha256"] = sha256(source.encode()).hexdigest()
            destination = record["destination"]
            if isinstance(destination, str) and destination.startswith("/") and not any(
                destination == prefix or destination.startswith(prefix + "/") for prefix in PSEUDO_FILESYSTEMS
            ):
                target = container_directory / f"mount-{index:03d}.tar"
                record["snapshot"] = await self._copy_path(container_id, destination, target)
            else:
                record["snapshot"] = {
                    "source": destination,
                    "return_code": None,
                    "payload": None,
                    "reason": "unsupported_mount_destination",
                }
            mounts.append(record)
        status = "complete" if process_code == 0 and root_snapshot["status"] == "complete" and all(
            mount["snapshot"].get("return_code") == 0 for mount in mounts
        ) else "incomplete"
        return {
            "container_id": container_id,
            "container_name": inspect[0].get("Name"),
            "image_id": inspect[0].get("Image"),
            "configured_image": inspect[0].get("Config", {}).get("Image"),
            "status": status,
            "logs_return_code": logs_code,
            "processes_return_code": process_code,
            "processes_sha256": sha256(process_bytes).hexdigest(),
            "diff": diff,
            "changed_paths": changed,
            "root_snapshot": root_snapshot,
            "mounts": mounts,
        }

    @staticmethod
    def _container_state_signature(container: dict) -> dict:
        return {
            "image_id": container["image_id"],
            "configured_image": container["configured_image"],
            "processes_sha256": container["processes_sha256"],
            "diff": container["diff"],
            "changed_paths": [
                {
                    "change": record["change"],
                    "path": record["path"],
                    "kind": record["kind"],
                    "archived": record["archived"],
                    "tree_sha256": record["tree_sha256"],
                }
                for record in container["changed_paths"]
            ],
            "root_snapshot_tree_sha256": container["root_snapshot"]["payload"]["tree_sha256"],
            "unarchived_special_paths": container["root_snapshot"]["unarchived_special_paths"],
            "mounts": [
                {
                    "type": mount["type"],
                    "destination": mount["destination"],
                    "read_write": mount["read_write"],
                    "tree_sha256": (mount["snapshot"].get("payload") or {}).get("tree_sha256"),
                }
                for mount in container["mounts"]
            ],
        }

    async def _capture_environment(self, phase: str = "manual_preflight") -> dict:
        started = asyncio.get_running_loop().time()
        root = self.trial_paths.trial_dir / "workspace-replay"
        root.mkdir(parents=True, exist_ok=True)
        directory = root / self._safe_name(self.session_id)
        directory.mkdir(exist_ok=False)
        compose = await self._run_docker_compose_command(["ps", "-aq"], check=False, timeout_sec=30)
        container_ids = sorted(line.strip() for line in (compose.stdout or "").splitlines() if line.strip())
        containers = []
        error = None
        try:
            if compose.return_code != 0 or not container_ids:
                raise RuntimeError("No running compose containers were available for replay capture")
            for container_id in container_ids:
                containers.append(await self._capture_container(container_id, directory))
        except BaseException as caught:
            error = {"type": type(caught).__name__, "message": str(caught)}
        status = "complete" if error is None and containers and all(
            container["status"] == "complete" for container in containers
        ) else "incomplete"
        payload = {
            "schema_version": 3,
            "kind": "docker_verifier_replay_bundle",
            "session_id": self.session_id,
            "capture_phase": phase,
            "status": status,
            "compose_ps_return_code": compose.return_code,
            "container_count": len(containers),
            "containers": containers,
            "state_sha256": sha256(canonical_json({
                "containers": [self._container_state_signature(container) for container in containers]
            })).hexdigest(),
            "capture_wall_seconds": asyncio.get_running_loop().time() - started,
            "verifier_replay": None,
            "files": {},
            "error": error,
        }
        self._replay_directory = directory
        self._replay_manifest = payload
        self._write_manifest()
        return payload

    def _write_manifest(self) -> None:
        if self._replay_directory is None or self._replay_manifest is None:
            raise RuntimeError("Replay capture has not been initialized")
        self._replay_manifest["files"] = {
            path.relative_to(self._replay_directory).as_posix(): {
                "bytes": path.stat().st_size,
                "sha256": file_digest(path),
            }
            for path in sorted(self._replay_directory.rglob("*"))
            if path.is_file() and path.name != "manifest.json"
        }
        payload = {key: item for key, item in self._replay_manifest.items() if key != "manifest_sha256"}
        self._replay_manifest["manifest_sha256"] = sha256(canonical_json(payload)).hexdigest()
        atomic_json(self._replay_directory / "manifest.json", self._replay_manifest)

    async def _remove_path(self, container_id: str, path: str) -> None:
        code, _ = await self._command(
            ["docker", "exec", container_id, "rm", "-rf", "--", path], check=False
        )
        if code != 0:
            raise RuntimeError("Could not reset a verifier-visible path")

    async def _install_archive(self, container_id: str, path: str, payload: bytes) -> None:
        installation, parent = archive_installation(payload, path)
        if installation is None:
            return
        code, _ = await self._command(
            ["docker", "exec", container_id, "mkdir", "-p", "--", parent], check=False
        )
        if code != 0:
            raise RuntimeError("Could not create a replay parent directory")
        code, output = await self._command(
            ["docker", "cp", "-", f"{container_id}:{parent}"], input_bytes=installation,
            timeout=600, check=False,
        )
        if code != 0:
            message = output.decode(errors="replace").strip()
            raise RuntimeError(
                f"Could not install replay archive for {path}: {message or 'docker cp failed without output'}"
            )

    async def _restore_mount(self, container_id: str, mount: dict, container_directory: Path) -> None:
        destination = mount["destination"]
        payload_record = mount["snapshot"].get("payload")
        if not isinstance(destination, str) or payload_record is None:
            raise RuntimeError("A mounted verifier-visible path lacks a snapshot")
        code, _ = await self._command(
            [
                "docker", "exec", container_id, "find", destination,
                "-mindepth", "1", "-maxdepth", "1", "-exec", "rm", "-rf", "--", "{}", "+",
            ],
            check=False,
        )
        if code != 0:
            raise RuntimeError("Could not clear a mounted replay path")
        await self._install_archive(
            container_id, destination, (container_directory / payload_record["path"]).read_bytes()
        )

    async def _restore_container(self, container: dict) -> None:
        if self._replay_directory is None:
            raise RuntimeError("Replay directory is absent")
        container_id = container["container_id"]
        safe_name = self._safe_name((container["container_name"] or "").lstrip("/") or container_id[:12])
        container_directory = self._replay_directory / safe_name
        inspect, current_diff, process_code, process_bytes = await self._container_details(container_id)
        if process_code != 0:
            raise RuntimeError("Could not inspect process state before replay")
        if sha256(process_bytes).hexdigest() != container["processes_sha256"]:
            raise RuntimeError("Process state changed and cannot be reconstructed for verifier replay")
        destinations = [
            mount.get("Destination") for mount in sorted_mounts(inspect[0])
            if isinstance(mount.get("Destination"), str)
        ]
        current_snapshot, current_changed = await self._root_snapshot(
            container_id, current_diff, destinations,
        )
        if current_snapshot["status"] != "complete":
            raise RuntimeError("Current writable-layer state could not be archived for replay")
        if current_snapshot["unarchived_special_paths"] != container["root_snapshot"]["unarchived_special_paths"]:
            raise RuntimeError("Unarchived runtime paths changed and cannot be reconstructed for verifier replay")
        protected_paths = destinations + [
            record["path"] for record in current_snapshot["unarchived_special_paths"]
        ]

        remove_paths = [
            record["path"]
            for record in current_changed
            if record["archived"] and (
                record["change"] == "A"
                or (record["change"] == "C" and record["kind"] != "directory")
            ) and not self._contains_mount(record["path"], protected_paths)
        ]
        modified_base_paths = [
            record["path"]
            for record in current_changed
            if record["archived"] and record["change"] == "C"
        ]
        deleted_base_paths = [
            path for path in deleted_root_paths(current_diff)
            if not self._under_mount(path, destinations)
        ]

        base_archives = []
        for paths, recursive in ((modified_base_paths, False), (deleted_base_paths, True)):
            if not paths:
                continue
            return_code, payload, stderr = await self._archive_image_paths(
                container["image_id"], paths, recursive=recursive,
            )
            if return_code != 0:
                raise RuntimeError(
                    "Could not read immutable-image paths for replay: "
                    + stderr.decode(errors="replace").strip()
                )
            inventory = archive_inventory(payload)
            archived = {"/" + entry["path"].lstrip("/") for entry in inventory["entries"]}
            if any(path not in archived for path in normalized_absolute_paths(paths)):
                raise RuntimeError("An immutable-image replay path was not archived")
            base_archives.append(payload)

        await self._remove_paths(
            container_id,
            sorted(set(remove_paths), key=lambda value: (value.count("/"), value), reverse=True),
        )
        for payload in base_archives:
            await self._install_root_archive(container_id, payload)

        captured_deleted_paths = [
            path for path in deleted_root_paths(container["diff"])
            if not self._under_mount(path, destinations)
            and not self._contains_mount(path, protected_paths)
        ]
        await self._remove_paths(
            container_id,
            sorted(captured_deleted_paths, key=lambda value: (value.count("/"), value), reverse=True),
        )
        root_payload = container["root_snapshot"].get("payload")
        if root_payload is None:
            raise RuntimeError("A verifier-visible writable-layer snapshot is absent")
        await self._install_root_archive(
            container_id, (container_directory / root_payload["path"]).read_bytes(),
        )
        for mount in container["mounts"]:
            await self._restore_mount(container_id, mount, container_directory)

    async def _state_signature(self, container_id: str) -> dict:
        inspect, diff, process_code, process_bytes = await self._container_details(container_id)
        if process_code != 0:
            raise RuntimeError("Could not inspect replay process state")
        destinations = [
            mount.get("Destination") for mount in sorted_mounts(inspect[0])
            if isinstance(mount.get("Destination"), str)
        ]
        root_snapshot, changed = await self._root_snapshot(container_id, diff, destinations)
        if root_snapshot["status"] != "complete":
            raise RuntimeError("Could not calculate restored writable-layer state")
        mounts = []
        for mount in sorted_mounts(inspect[0]):
            destination = mount.get("Destination")
            return_code, payload = await self._archive_path(container_id, destination)
            mounts.append({
                "type": mount.get("Type"),
                "destination": destination,
                "read_write": mount.get("RW"),
                "tree_sha256": archive_inventory(payload)["tree_sha256"] if return_code == 0 else None,
            })
        return {
            "image_id": inspect[0].get("Image"),
            "configured_image": inspect[0].get("Config", {}).get("Image"),
            "processes_sha256": sha256(process_bytes).hexdigest(),
            "diff": diff,
            "changed_paths": [
                {
                    "change": record["change"],
                    "path": record["path"],
                    "kind": record["kind"],
                    "archived": record["archived"],
                    "tree_sha256": record["tree_sha256"],
                }
                for record in changed
            ],
            "root_snapshot_tree_sha256": root_snapshot["payload"]["tree_sha256"],
            "unarchived_special_paths": root_snapshot["unarchived_special_paths"],
            "mounts": mounts,
        }

    @staticmethod
    def _copy_host_tree(source: Path, target: Path) -> None:
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source)
            destination = target / relative
            if path.is_symlink():
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.symlink_to(os.readlink(path))
            elif path.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                shutil.copystat(path, destination, follow_symlinks=False)
            elif path.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination, follow_symlinks=False)

    @staticmethod
    def _replace_host_tree(source: Path, target: Path) -> None:
        target.mkdir(parents=True, exist_ok=True)
        for path in sorted(target.iterdir()) if target.exists() else []:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source)
            destination = target / relative
            if path.is_symlink():
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.symlink_to(os.readlink(path))
            elif path.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                shutil.copystat(path, destination, follow_symlinks=False)
            elif path.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination, follow_symlinks=False)

    async def _repeat_verifier(
        self, command: str, original_result, *, cwd, env, timeout_sec, user,
        original_verifier_wall_seconds: float,
    ) -> None:
        if self._replay_manifest is None or self._replay_directory is None:
            raise RuntimeError("Verifier replay started without a preserved state")
        started = asyncio.get_running_loop().time()
        replay = {
            "status": "incomplete",
            "execution_phase": "environment_stop_after_original_verifier",
            "command_sha256": sha256(command.encode()).hexdigest(),
            "preparatory_commands": [
                {
                    "command_sha256": sha256(prepared["command"].encode()).hexdigest(),
                    "cwd": prepared["cwd"],
                    "environment_names": sorted((prepared["env"] or {}).keys()),
                    "timeout_seconds": prepared["timeout_sec"],
                    "user": prepared["user"],
                }
                for prepared in self._preparatory_verifier_commands
            ],
            "state_restored": False,
            "same_judgement": False,
            "original_verifier_wall_seconds": original_verifier_wall_seconds,
            "restore_wall_seconds": None,
            "repeated_verifier_wall_seconds": None,
            "wall_seconds": None,
            "error": None,
        }
        original_directory = self._replay_directory / "original-verifier"
        repeated_directory = self._replay_directory / "repeated-verifier"
        self._copy_host_tree(self.trial_paths.verifier_dir, original_directory)
        phase = "restore"
        phase_started = asyncio.get_running_loop().time()
        try:
            if self._replay_manifest["status"] != "complete":
                raise RuntimeError("Verifier replay requires a complete pre-verifier capture")
            for container in self._replay_manifest["containers"]:
                await self._restore_container(container)
            restored = [
                await self._state_signature(container["container_id"])
                for container in self._replay_manifest["containers"]
            ]
            restored_hash = sha256(canonical_json({"containers": restored})).hexdigest()
            replay["restored_state_sha256"] = restored_hash
            replay["state_restored"] = restored_hash == self._replay_manifest["state_sha256"]
            if not replay["state_restored"]:
                raise RuntimeError("Verifier-visible state did not restore byte-for-byte")
            replay["restore_wall_seconds"] = asyncio.get_running_loop().time() - phase_started
            phase = "repeated_verifier"
            phase_started = asyncio.get_running_loop().time()
            for prepared in self._preparatory_verifier_commands:
                await super().exec(**prepared)
            repeated_result = await super().exec(
                command=command, cwd=cwd, env=env, timeout_sec=timeout_sec, user=user
            )
            self._copy_host_tree(self.trial_paths.verifier_dir, repeated_directory)
            original_signature = verifier_signature(original_directory, original_result.return_code)
            repeated_signature = verifier_signature(repeated_directory, repeated_result.return_code)
            replay["original_signature"] = original_signature
            replay["repeated_signature"] = repeated_signature
            replay["same_judgement"] = original_signature == repeated_signature
            replay["status"] = "complete" if replay["same_judgement"] else "mismatch"
            replay["repeated_verifier_wall_seconds"] = asyncio.get_running_loop().time() - phase_started
        except BaseException as caught:
            timing_name = "restore_wall_seconds" if phase == "restore" else "repeated_verifier_wall_seconds"
            replay[timing_name] = asyncio.get_running_loop().time() - phase_started
            replay["error"] = {"type": type(caught).__name__, "message": str(caught)}
        finally:
            replay["wall_seconds"] = asyncio.get_running_loop().time() - started
            self._replace_host_tree(original_directory, self.trial_paths.verifier_dir)
            self._replay_manifest["verifier_replay"] = replay
            if replay["status"] != "complete":
                self._replay_manifest["status"] = "incomplete"
            self._write_manifest()

    async def upload_dir(self, source_dir: Path | str, target_dir: str):
        result = await super().upload_dir(source_dir, target_dir)
        if PurePosixPath(target_dir).as_posix() == "/tests":
            self._tests_uploaded = True
            self._preparatory_verifier_commands = []
        return result

    async def exec(
        self,
        command: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_sec: int | None = None,
        user: str | int | None = None,
    ):
        if self._tests_uploaded and self._replay_manifest is None:
            await self._capture_environment("after_tests_upload_before_verifier")
        arguments = {"command": command, "cwd": cwd, "env": env, "timeout_sec": timeout_sec, "user": user}
        verifier_command = (
            self._tests_uploaded and not self._replay_started and self._verifier_test_command(command)
        )
        verifier_started = asyncio.get_running_loop().time() if verifier_command else None
        result = await super().exec(**arguments)
        if not self._tests_uploaded or self._replay_started:
            return result
        if self._verifier_test_command(command):
            self._replay_started = True
            self._pending_verifier_replay = {
                "command": command,
                "original_result": result,
                "cwd": cwd,
                "env": env,
                "timeout_sec": timeout_sec,
                "user": user,
                "original_verifier_wall_seconds": asyncio.get_running_loop().time() - verifier_started,
            }
        else:
            self._preparatory_verifier_commands.append(arguments)
        return result

    async def stop(self, delete: bool):
        manifest_path = (
            self.trial_paths.trial_dir
            / "workspace-replay"
            / self._safe_name(self.session_id)
            / "manifest.json"
        )
        try:
            if self._pending_verifier_replay is not None:
                pending = self._pending_verifier_replay
                self._pending_verifier_replay = None
                await self._repeat_verifier(**pending)
            elif not manifest_path.exists():
                await self._capture_environment("teardown_without_verifier")
        finally:
            await super().stop(delete=delete)
