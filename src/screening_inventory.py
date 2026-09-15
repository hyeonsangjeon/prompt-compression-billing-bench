"""Build a hash-bound Terminal-Bench 2.1 screening inventory."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import tomllib
import urllib.parse
import urllib.request

from .protection import digest
from .verifier_revisions import VERIFIER_SPECS, apply_verifier_revision


REVISION = "7131e4375048a0e408a8fb404b5f499d726b695b"
TASK_TYPES = Path(__file__).resolve().parents[1] / "data/experiment/terminal-bench-2.1-task-types.json"
LOCK_NAMES = {
    "Cargo.lock", "Gemfile.lock", "Pipfile.lock", "poetry.lock", "uv.lock",
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "go.sum",
}
LOCK_PATTERNS = (
    re.compile(r"(?:^|/)requirements(?:-[^/]*)?\.txt$"),
    re.compile(r"(?:^|/)pyproject\.toml$"),
)
MANIFEST_ACCEPT = ", ".join((
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
))


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def git(root: Path, *arguments: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *arguments])


def _task_files(root: Path, task_id: str) -> dict[str, bytes]:
    prefix = f"tasks/{task_id}/"
    names = git(root, "ls-tree", "-r", "--name-only", "-z", REVISION, "--", prefix).split(b"\0")
    files = {}
    for raw_name in names:
        if not raw_name:
            continue
        name = raw_name.decode()
        files[name.removeprefix(prefix)] = git(root, "show", f"{REVISION}:{name}")
    return files


def _tree_records(root: Path, task_id: str, files: dict[str, bytes]) -> list[dict]:
    prefix = f"tasks/{task_id}/"
    raw = git(root, "ls-tree", "-r", "-z", REVISION, "--", prefix)
    records = []
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        metadata, raw_name = entry.split(b"\t", 1)
        mode, kind, object_id = metadata.decode().split()
        name = raw_name.decode().removeprefix(prefix)
        content = files[name]
        records.append({
            "path": name,
            "git_mode": mode,
            "git_kind": kind,
            "git_object": object_id,
            "entry_kind": "symlink" if mode == "120000" else "file",
            "bytes": len(content),
            "sha256": digest(content),
        })
    return sorted(records, key=lambda record: record["path"])


def _tree_hash(records: list[dict]) -> str:
    return digest(canonical_json({"files": records}))


def _direct_dependency_pins(command: str) -> list[str]:
    patterns = (
        r"(?<![A-Za-z0-9_.-])[A-Za-z0-9_.-]+==[^\s'\";]+",
        r"(?<![A-Za-z0-9_.-])[A-Za-z0-9_.-]+@[0-9a-f]{7,40}(?![A-Za-z0-9])",
    )
    return sorted({match.group(0) for pattern in patterns for match in re.finditer(pattern, command)})


def _task_types() -> tuple[dict[str, str], str]:
    source = TASK_TYPES.read_bytes()
    value = json.loads(source)
    if value.get("schema_version") != 1 or value.get("benchmark_revision") != REVISION:
        raise ValueError("Task classification does not match the benchmark revision")
    tasks = value.get("tasks")
    if not isinstance(tasks, dict) or any(
        not isinstance(task_id, str) or task_type not in {"feature", "bugfix", "review", "refactor", "test", "setup", "other"}
        for task_id, task_type in tasks.items()
    ):
        raise ValueError("Task classification is malformed")
    return tasks, digest(source)


def _registry_request(repository: str, reference: str, token: str, method: str = "GET"):
    request = urllib.request.Request(
        f"https://registry-1.docker.io/v2/{repository}/manifests/{reference}",
        method=method,
        headers={"Authorization": "Bearer " + token, "Accept": MANIFEST_ACCEPT},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.headers, response.read()


def resolve_docker_hub_image(reference: str, platform: str = "linux/amd64") -> dict:
    if "@" in reference or reference.count(":") != 1 or "/" not in reference:
        raise ValueError("Expected a tagged Docker Hub image")
    repository, tag = reference.rsplit(":", 1)
    if repository.startswith("docker.io/"):
        repository = repository.removeprefix("docker.io/")
    query = urllib.parse.urlencode({"service": "registry.docker.io", "scope": f"repository:{repository}:pull"})
    with urllib.request.urlopen("https://auth.docker.io/token?" + query, timeout=60) as response:
        token = json.load(response)["token"]
    headers, body = _registry_request(repository, tag, token)
    source_digest = headers.get("Docker-Content-Digest")
    document = json.loads(body)
    os_name, architecture = platform.split("/", 1)
    manifests = document.get("manifests")
    if isinstance(manifests, list):
        matches = [entry for entry in manifests if entry.get("platform", {}).get("os") == os_name
                   and entry.get("platform", {}).get("architecture") == architecture
                   and not entry.get("annotations", {}).get("vnd.docker.reference.type")]
        if len(matches) != 1:
            raise ValueError(f"Image {reference} does not have one unambiguous {platform} manifest")
        manifest_digest = matches[0]["digest"]
        child_headers, _ = _registry_request(repository, manifest_digest, token, method="HEAD")
        if child_headers.get("Docker-Content-Digest") != manifest_digest:
            raise ValueError("Registry child manifest digest changed during resolution")
    else:
        manifest_digest = source_digest
    if not isinstance(source_digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", source_digest):
        raise ValueError("Registry did not return an immutable source digest")
    if not isinstance(manifest_digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", manifest_digest):
        raise ValueError("Registry did not return an immutable platform digest")
    return {
        "tagged_reference": reference,
        "index_or_source_digest": source_digest,
        "platform": platform,
        "platform_digest": manifest_digest,
        "pinned_reference": f"{repository}@{manifest_digest}",
    }


def build_inventory(root: Path, *, resolve_images: bool) -> dict:
    root = root.resolve(strict=True)
    if git(root, "rev-parse", "HEAD").decode().strip() != REVISION:
        raise ValueError("Benchmark checkout is not at the fixed revision")
    task_types, classification_sha256 = _task_types()
    names = sorted(git(root, "ls-tree", "-d", "--name-only", f"{REVISION}:tasks").decode().splitlines())
    if len(names) != 89 or set(names) != set(task_types):
        raise ValueError("Benchmark task set and fixed classification must both contain the same 89 tasks")
    tasks = []
    for task_id in names:
        files = _task_files(root, task_id)
        required = {"instruction.md", "task.toml", "tests/test.sh", "tests/test_outputs.py"}
        if not required <= files.keys():
            raise ValueError(f"Task {task_id} lacks a required instruction or verifier file")
        records = _tree_records(root, task_id, files)
        task_config = tomllib.loads(files["task.toml"].decode())
        tagged_image = task_config["environment"]["docker_image"]
        verifier_source = {name: content for name, content in files.items() if name.startswith("tests/")}
        effective_verifier, verifier_revision = apply_verifier_revision(task_id, verifier_source, VERIFIER_SPECS)
        verifier_records = [{
            "path": name,
            "bytes": len(content),
            "sha256": digest(content),
        } for name, content in sorted(effective_verifier.items())]
        locks = [{"path": record["path"], "sha256": record["sha256"]} for record in records if
                 Path(record["path"]).name in LOCK_NAMES or any(pattern.search(record["path"]) for pattern in LOCK_PATTERNS)]
        image = resolve_docker_hub_image(tagged_image) if resolve_images else {
            "tagged_reference": tagged_image,
            "index_or_source_digest": None,
            "platform": "linux/amd64",
            "platform_digest": None,
            "pinned_reference": None,
        }
        tasks.append({
            "task_id": task_id,
            "primary_type": task_types[task_id],
            "task_tree_sha256": _tree_hash(records),
            "task_files": records,
            "instruction_sha256": digest(files["instruction.md"]),
            "task_toml_sha256": digest(files["task.toml"]),
            "image": image,
            "verifier_source_tree_sha256": digest(canonical_json({"files": verifier_records})),
            "verifier_files": verifier_records,
            "verifier_revision": verifier_revision,
            "verifier_command": files["tests/test.sh"].decode(),
            "verifier_command_sha256": digest(files["tests/test.sh"]),
            "dependency_locks": locks,
            "dependency_lock_status": "recorded" if locks else "absent",
            "direct_dependency_pins": _direct_dependency_pins(files["tests/test.sh"].decode()),
            "exclusion": None,
        })
    payload = {
        "schema_version": 1,
        "kind": "terminal_bench_screening_inventory",
        "benchmark": {"name": "terminal-bench-2.1", "revision": REVISION, "task_count": 89},
        "classification": {
            "revision": "instruction_and_required_deliverable_review_v2",
            "source_sha256": classification_sha256,
        },
        "image_resolution": {
            "registry": "registry-1.docker.io",
            "platform": "linux/amd64",
            "resolved": resolve_images,
        },
        "tasks": tasks,
    }
    return {**payload, "inventory_sha256": digest(canonical_json(payload))}


def verify_inventory(value: dict, *, require_images: bool = True) -> dict:
    payload = {key: item for key, item in value.items() if key != "inventory_sha256"}
    if value.get("inventory_sha256") != digest(canonical_json(payload)):
        raise ValueError("Screening inventory hash does not match its canonical payload")
    tasks = value.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 89 or [task["task_id"] for task in tasks] != sorted(task["task_id"] for task in tasks):
        raise ValueError("Screening inventory must contain 89 sorted tasks")
    if require_images and any(not re.fullmatch(r"[a-z0-9_./-]+@sha256:[0-9a-f]{64}", task["image"].get("pinned_reference") or "") for task in tasks):
        raise ValueError("Every screening image must have a platform-specific immutable digest")
    return value


def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--resolve-images", action="store_true")
    args = parser.parse_args(arguments)
    inventory = build_inventory(args.benchmark_root, resolve_images=args.resolve_images)
    verify_inventory(inventory, require_images=args.resolve_images)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(json.dumps(inventory, ensure_ascii=False, indent=2, allow_nan=False).encode() + b"\n")
    print(json.dumps({"tasks": len(inventory["tasks"]), "inventory_sha256": inventory["inventory_sha256"],
                      "images_resolved": args.resolve_images}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
