"""Bind static runs to an existing clean commit and an exact ledger snapshot."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess

from .protection import digest


ROOT = Path(__file__).resolve().parents[1]


def source_files(root: Path) -> tuple[str, ...]:
    return (
        "run.py", "accounting.py", "pyproject.toml", "uv.lock",
        *sorted(path.relative_to(root).as_posix() for path in (root / "src").glob("*.py")),
        *sorted(path.relative_to(root).as_posix() for path in (root / "schemas").glob("*.json")),
    )


def git(root: Path, *arguments: str) -> bytes:
    environment = {**os.environ, "GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1"}
    result = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(root), *arguments],
        env=environment, capture_output=True, timeout=30,
    )
    if result.returncode:
        raise ValueError("Source Git verification failed; the designated commit and its blobs must be available locally")
    return result.stdout


def require_sha(commit: str | None) -> str:
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("--source-commit requires the full 40-character execution SHA")
    return commit


def committed_source_files(root: Path, commit: str) -> set[str]:
    names = git(root, "ls-tree", "-r", "--name-only", commit, "--", "src", "schemas").decode().splitlines()
    return {
        "run.py", "accounting.py", "pyproject.toml", "uv.lock",
        *(name for name in names if name.count("/") == 1 and (name.endswith(".py") or name.endswith(".json"))),
    }


def capture(ledger_path: Path, commit: str | None, root: Path = ROOT) -> tuple[dict, dict[str, bytes]]:
    commit = require_sha(commit)
    if git(root, "rev-parse", "--show-toplevel").decode().strip() != str(root):
        raise ValueError("Execution must use the source checkout root")
    if git(root, "cat-file", "-t", commit).strip() != b"commit":
        raise ValueError("Designated SHA is not a commit")
    if git(root, "rev-parse", "--verify", "HEAD").decode().strip() != commit:
        raise ValueError("Checkout HEAD differs from the designated source_commit")
    if git(root, "status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none"):
        raise ValueError("Execution source checkout is dirty; commit reviewed changes before measurement")
    sources = {}
    if set(source_files(root)) != committed_source_files(root, commit):
        raise ValueError("Execution source inventory differs from the designated commit")
    for name in source_files(root):
        content = (root / name).read_bytes()
        if content != git(root, "show", f"{commit}:{name}"):
            raise ValueError(f"Source file differs from designated commit: {name}")
        sources[name] = content
    ledger_bytes = ledger_path.read_bytes()
    ledger_origin = "external_snapshot"
    ledger_source_path = None
    try:
        relative = ledger_path.resolve().relative_to(root).as_posix()
    except ValueError:
        relative = None
    if relative and git(root, "ls-files", "--", relative).strip():
        if ledger_bytes != git(root, "show", f"{commit}:{relative}"):
            raise ValueError("Tracked ledger differs from designated source_commit")
        ledger_origin, ledger_source_path = "committed", relative
    hashes = {name: digest(content) for name, content in sources.items()}
    provenance = {
        "kind": "verified_source_snapshot", "source_commit": commit,
        "source_files": hashes, "source_sha256": digest(json.dumps(hashes, sort_keys=True).encode()),
        "ledger_sha256": digest(ledger_bytes), "ledger_origin": ledger_origin,
        "ledger_source_path": ledger_source_path,
    }
    return provenance, {"ledger.toml": ledger_bytes, **{f"source/{name}": content for name, content in sources.items()}}


def verify_snapshot(directory: Path, root: Path = ROOT) -> dict:
    provenance = json.loads((directory / "provenance.json").read_bytes())
    commit = require_sha(provenance["source_commit"])
    if git(root, "cat-file", "-t", commit).strip() != b"commit":
        raise ValueError("Recorded source SHA is not a commit")
    hashes = provenance["source_files"]
    if set(hashes) != committed_source_files(root, commit):
        raise ValueError("Source snapshot inventory differs from its recorded commit")
    for name, expected in hashes.items():
        content = (directory / "source" / name).read_bytes()
        if digest(content) != expected or content != git(root, "show", f"{commit}:{name}"):
            raise ValueError(f"Source snapshot differs from its recorded commit: {name}")
    if digest(json.dumps(hashes, sort_keys=True).encode()) != provenance["source_sha256"]:
        raise ValueError("Source aggregate hash differs")
    ledger_bytes = (directory / "ledger.toml").read_bytes()
    if digest(ledger_bytes) != provenance["ledger_sha256"]:
        raise ValueError("Ledger snapshot hash differs")
    if provenance["ledger_origin"] == "committed":
        if ledger_bytes != git(root, "show", f"{commit}:{provenance['ledger_source_path']}"):
            raise ValueError("Ledger snapshot differs from recorded commit")
    elif provenance["ledger_origin"] != "external_snapshot" or provenance["ledger_source_path"] is not None:
        raise ValueError("Unknown ledger provenance")
    return provenance
