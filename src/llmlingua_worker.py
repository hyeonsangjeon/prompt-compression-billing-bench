"""Isolated JSON-lines worker for the pinned local LLMLingua-2 classifier."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import re
import sys
import time
import traceback


def digest_file(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, allow_nan=False), flush=True)


def receive() -> dict:
    line = sys.stdin.readline()
    if not line:
        raise EOFError("Worker input closed")
    payload = json.loads(line)
    if not isinstance(payload, dict):
        raise ValueError("Worker messages must be JSON objects")
    return payload


def package_versions(path: Path, expected_sha256: str) -> dict[str, str]:
    if digest_file(path) != expected_sha256:
        raise ValueError("Pinned requirements file changed")
    expected = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s]+)", value)
        if not match:
            raise ValueError("Requirements must contain exact package pins only")
        expected[match[1]] = match[2]
    actual = {name: importlib.metadata.version(name) for name in expected}
    if actual != expected:
        differences = sorted(name for name in expected if actual.get(name) != expected[name])
        raise ValueError(f"Installed package versions differ: {differences}")
    return actual


def model_files(path: Path, expected: dict[str, dict]) -> list[dict]:
    if not path.is_dir() or path.is_symlink():
        raise ValueError("Model root must be a real directory")
    records = []
    for name, record in expected.items():
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise ValueError("Unsafe model filename")
        if not isinstance(record, dict) or set(record) != {"bytes", "sha256"}:
            raise ValueError("Invalid model file record")
        source = path / name
        if not source.is_file():
            raise ValueError(f"Pinned model file is missing: {name}")
        actual = digest_file(source)
        if actual != record["sha256"] or source.stat().st_size != record["bytes"]:
            raise ValueError(f"Pinned model file changed: {name}")
        records.append({"name": name, "bytes": source.stat().st_size, "sha256": actual})
    return records


def install_offline_guard() -> None:
    def reject(event: str, _arguments) -> None:
        if event.startswith("socket.") or event in {"subprocess.Popen", "os.system", "os.posix_spawn"}:
            raise RuntimeError(f"Offline LLMLingua worker blocked {event}")

    sys.addaudithook(reject)


def initialize(payload: dict):
    if set(payload) != {"operation", "model_path", "specification"} or payload["operation"] != "initialize":
        raise ValueError("First worker message must be an exact initialization request")
    specification = payload["specification"]
    required = {
        "python_version", "requirements_path", "requirements_sha256", "model_id", "model_revision",
        "model_files", "tokenizer_cache_path", "tokenizer_cache_files", "profile",
    }
    if not isinstance(specification, dict) or set(specification) != required:
        raise ValueError("Unexpected LLMLingua worker specification")
    if platform.python_version() != specification["python_version"]:
        raise ValueError("Worker Python version differs from the ledger")
    packages = package_versions(Path(specification["requirements_path"]), specification["requirements_sha256"])
    verified_model = model_files(Path(payload["model_path"]), specification["model_files"])
    verified_tokenizer_cache = model_files(
        Path(specification["tokenizer_cache_path"]), specification["tokenizer_cache_files"]
    )
    profile = specification["profile"]
    expected_profile = {
        "method", "rate", "target_token", "force_tokens", "force_reserve_digit", "drop_consecutive",
        "chunk_end_tokens", "device", "torch_dtype", "seed", "torch_threads", "torch_interop_threads",
        "deterministic_algorithms",
    }
    if not isinstance(profile, dict) or set(profile) != expected_profile:
        raise ValueError("Unexpected LLMLingua profile")
    if profile["method"] != "PromptCompressor.compress_prompt_llmlingua2" or profile["device"] != "cpu" or profile["torch_dtype"] != "float32":
        raise ValueError("Only the reviewed CPU LLMLingua-2 path is supported")

    import torch
    from llmlingua import PromptCompressor

    runtime_platform = platform.platform()
    install_offline_guard()
    torch.manual_seed(profile["seed"])
    torch.set_num_threads(profile["torch_threads"])
    torch.set_num_interop_threads(profile["torch_interop_threads"])
    torch.use_deterministic_algorithms(profile["deterministic_algorithms"])
    started = time.perf_counter()
    compressor = PromptCompressor(
        model_name=str(Path(payload["model_path"])),
        use_llmlingua2=True,
        device_map="cpu",
        model_config={"local_files_only": True, "torch_dtype": torch.float32},
    )
    load_seconds = time.perf_counter() - started
    if compressor.model.training:
        raise ValueError("Pinned token classifier did not load in eval mode")
    runtime = {
        "python": platform.python_version(),
        "platform": runtime_platform,
        "packages": packages,
        "torch_threads": torch.get_num_threads(),
        "torch_interop_threads": torch.get_num_interop_threads(),
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
    }
    emit({
        "operation": "initialized", "ok": True, "runtime": runtime, "model_files": verified_model,
        "tokenizer_cache_files": verified_tokenizer_cache,
        "model_id": specification["model_id"], "model_revision": specification["model_revision"],
        "profile": profile, "load_seconds": load_seconds,
    })
    return compressor, profile


def compress(compressor, profile: dict, payload: dict) -> dict:
    if set(payload) != {"operation", "id", "text"} or payload["operation"] != "compress" or not isinstance(payload["text"], str):
        raise ValueError("Invalid compression request")
    started = time.perf_counter()
    result = compressor.compress_prompt_llmlingua2(
        payload["text"],
        rate=profile["rate"],
        target_token=profile["target_token"],
        force_tokens=list(profile["force_tokens"]),
        force_reserve_digit=profile["force_reserve_digit"],
        drop_consecutive=profile["drop_consecutive"],
        chunk_end_tokens=list(profile["chunk_end_tokens"]),
    )
    elapsed = time.perf_counter() - started
    transformed = result["compressed_prompt"]
    if not isinstance(transformed, str) or not math.isfinite(elapsed) or elapsed < 0:
        raise ValueError("LLMLingua returned an invalid result")
    return {
        "operation": "compressed", "ok": True, "id": payload["id"], "text": transformed,
        "inference_seconds": elapsed,
        "tool_reported": {
            "kind": "tool_reported", "status": "reported", "not_provider_usage": True,
            "origin_tokens": result["origin_tokens"], "compressed_tokens": result["compressed_tokens"],
            "rate": result["rate"], "ratio": result["ratio"],
            "unit": "LLMLingua internal OpenAI tokenizer; not provider billed usage",
        },
    }


def main() -> int:
    try:
        compressor, profile = initialize(receive())
        while True:
            payload = receive()
            if payload == {"operation": "close"}:
                emit({"operation": "closed", "ok": True})
                return 0
            emit(compress(compressor, profile, payload))
    except BaseException as error:
        traceback.print_exc(file=sys.stderr)
        emit({"operation": "error", "ok": False, "error_type": type(error).__name__, "message": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
