"""Archive untracked root prompt attachments, never grade them as measurements."""

from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile


PROMPT_NAME = re.compile(r"prompt_[A-Za-z0-9][A-Za-z0-9_. ()-]*\.md\Z")


def archive_prompts(root: Path) -> list[dict]:
    root = root.resolve()
    candidates = sorted(path for path in root.iterdir() if PROMPT_NAME.fullmatch(path.name))
    if not candidates:
        return []
    tracked = set(subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "-z"]
    ).decode().strip("\0").split("\0"))
    candidates = [path for path in candidates if path.name not in tracked]
    if not candidates:
        return []
    directory = root / "_work/prompts"
    for ancestor in (root / "_work", directory):
        if ancestor.is_symlink():
            raise ValueError("Private prompt destination must not be a symlink")
    ignored = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "-q", "--", "_work/prompts/manifest.json"],
        check=False, capture_output=True,
    )
    if ignored.returncode != 0:
        raise ValueError("Ignore /_work/ before archiving private attachments")
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / ".intake.lock"
    if lock_path.is_symlink():
        raise ValueError("Prompt intake lock must not be a symlink")
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        manifest_path = directory / "manifest.json"
        if manifest_path.is_symlink():
            raise ValueError("Prompt manifest must not be a symlink")
        manifest = json.loads(manifest_path.read_bytes()) if manifest_path.exists() else {
            "schema_version": 1, "kind": "private_user_request_inventory", "entries": [],
        }
        if manifest.get("kind") != "private_user_request_inventory" or not isinstance(manifest.get("entries"), list):
            raise ValueError("Unexpected prompt inventory")
        imported = []
        for source in candidates:
            if not source.exists() and not source.is_symlink():
                continue
            source_stat = source.lstat()
            if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_nlink != 1:
                raise ValueError("Prompt attachments must be regular, unlinked files")
            content = source.read_bytes()
            content.decode("utf-8")
            checksum = hashlib.sha256(content).hexdigest()
            target = directory / source.name
            if target.exists() or target.is_symlink():
                if target.is_symlink() or not target.is_file():
                    raise ValueError("Prompt archive target must be a regular file")
                if target.read_bytes() != content:
                    target = directory / f"{source.stem}--{checksum}.md"
            if target.is_symlink():
                raise ValueError("Prompt archive target must not be a symlink")
            if target.exists():
                if target.read_bytes() != content:
                    raise ValueError("Refusing to overwrite a different archived prompt")
            else:
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
            if source.read_bytes() != content:
                raise ValueError("Prompt changed during intake; original retained")
            entry = {
                "original_path": source.name, "archive_path": target.relative_to(root).as_posix(),
                "sha256": checksum, "utf8_bytes": len(content),
                "kind": "user_request_not_measurement", "disclosure": "private",
                "imported_at": datetime.now(timezone.utc).isoformat(),
            }
            manifest["entries"].append(entry)
            descriptor, temporary_name = tempfile.mkstemp(prefix=".manifest-", suffix=".tmp", dir=directory)
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(manifest, handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                temporary.replace(manifest_path)
            finally:
                temporary.unlink(missing_ok=True)
            current = source.lstat()
            if (current.st_dev, current.st_ino) != (source_stat.st_dev, source_stat.st_ino) or source.read_bytes() != content:
                raise ValueError("Prompt changed during intake; original retained")
            source.unlink()
            imported.append(entry)
        return imported
