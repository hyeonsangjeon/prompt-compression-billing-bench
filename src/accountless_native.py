"""Run one rights-cleared exact-answer task with an offline local model."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
ANSWER_RE = re.compile(r"#### (\-?[0-9\.\,]+)")
INVALID_ANSWER = "[invalid]"
EXIT_PASS = 0
EXIT_WRONG = 1
EXIT_PREFLIGHT = 2
EXIT_EXECUTION = 3
EXIT_COLLISION = 4


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def digest_file(path: Path) -> tuple[int, str]:
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            hasher.update(chunk)
    return size, hasher.hexdigest()


def write_json_x(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def repository_path(relative: str) -> Path:
    path = Path(relative)
    if not path.parts or path.is_absolute() or ".." in path.parts or path.as_posix() != relative:
        raise ValueError(f"Unsafe repository-relative path: {relative}")
    resolved = (ROOT / path).resolve()
    if not resolved.is_relative_to(ROOT.resolve()):
        raise ValueError(f"Repository path escapes the source root: {relative}")
    return resolved


def extract_answer(completion: str) -> str:
    match = ANSWER_RE.search(completion)
    if match is None:
        return INVALID_ANSWER
    return match.group(1).strip().replace(",", "")


def judge_output(output: str, reference: str) -> dict:
    expected = extract_answer(reference)
    if expected == INVALID_ANSWER:
        raise ValueError("The public fixture has no valid GSM8K reference marker")
    observed = extract_answer(output)
    if observed == INVALID_ANSWER:
        verdict = "wrong_format"
    elif observed == expected:
        verdict = "pass"
    else:
        verdict = "wrong_answer"
    return {
        "kind": "official_gsm8k_exact_answer",
        "source": "pinned_grade_school_math_dataset_py_equivalent",
        "verdict": verdict,
        "expected": expected,
        "observed": None if observed == INVALID_ANSWER else observed,
    }


def load_ledger(path: Path) -> tuple[dict, bytes]:
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT.resolve()):
        raise ValueError("The quickstart ledger must be inside the repository checkout")
    content = resolved.read_bytes()
    ledger = json.loads(content)
    required = {
        "schema_version", "record_type", "task", "prompt", "judge", "model",
        "runtime", "generation", "limits", "output", "source_files", "claim_limit",
    }
    if set(ledger) != required or ledger["schema_version"] != 1:
        raise ValueError("Unexpected quickstart ledger fields or schema version")
    if ledger["record_type"] != "accountless_native_quickstart_ledger":
        raise ValueError("Unexpected quickstart ledger record_type")
    if ledger["model"]["local_files_only"] is not True or ledger["model"]["trust_remote_code"] is not False:
        raise ValueError("The model must be local-only with remote code disabled")
    if ledger["generation"]["do_sample"] is not False or ledger["generation"]["retries"] != 0:
        raise ValueError("The quickstart uses greedy generation with zero retries")
    if ledger["limits"] != {"attempt_wall_seconds": 300, "no_progress_seconds": 120}:
        raise ValueError("The fixed 300/120 second limits differ")
    if ledger["judge"]["pattern"] != r"#### (\-?[0-9\.\,]+)":
        raise ValueError("The judge no longer matches the pinned official source")
    return ledger, content


def load_fixture(ledger: dict) -> tuple[dict, bytes]:
    path = repository_path(ledger["task"]["fixture"])
    content = path.read_bytes()
    fixture = json.loads(content)
    if fixture.get("schema_version") != 1 or fixture.get("local_id") != ledger["task"]["id"]:
        raise ValueError("The public task fixture identity differs from the ledger")
    for field in ("question", "answer"):
        expected = ledger["task"][field + "_sha256"]
        if digest_bytes(fixture[field].encode("utf-8")) != expected:
            raise ValueError(f"The fixture {field} differs from the ledger")
    if fixture["source_line_sha256"] != ledger["task"]["source_line_sha256"]:
        raise ValueError("The selected source-line pin differs")
    if extract_answer(fixture["answer"]) != ledger["task"]["reference_answer"]:
        raise ValueError("The fixture reference answer differs from the ledger")
    return fixture, content


def verify_file_set(root: Path, specifications: list[dict]) -> list[dict]:
    observed = []
    for specification in specifications:
        path = root / specification["name"]
        if not path.is_file():
            raise ValueError(f"Missing required model asset: {specification['name']}")
        size, sha256 = digest_file(path)
        if size != specification["bytes"] or sha256 != specification["sha256"]:
            raise ValueError(f"Model asset differs: {specification['name']}")
        observed.append({"name": specification["name"], "bytes": size, "sha256": sha256})
    return observed


def runtime_versions(ledger: dict) -> dict:
    observed = {"python": ".".join(map(str, sys.version_info[:3]))}
    for package in ledger["runtime"]["packages"]:
        observed[package] = importlib.metadata.version(package)
    if observed != ledger["runtime"]["expected"]:
        raise ValueError(f"Runtime versions differ: {observed}")
    return observed


def source_identity(ledger: dict) -> dict:
    files = []
    for relative in ledger["source_files"]:
        path = repository_path(relative)
        size, sha256 = digest_file(path)
        files.append({"path": relative, "bytes": size, "sha256": sha256})
    commit = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    status = subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"], text=True)
    return {
        "git_commit": commit,
        "git_clean": status == "",
        "files": files,
        "aggregate_sha256": digest_bytes(canonical(files)),
    }


def preflight(ledger_path: Path, ledger: dict, ledger_bytes: bytes) -> dict:
    model_root_value = os.environ.get(ledger["model"]["root_env"])
    if not model_root_value:
        raise ValueError(f"Missing model-root environment variable: {ledger['model']['root_env']}")
    model_root = Path(model_root_value).expanduser().resolve()
    if not model_root.is_dir():
        raise ValueError("The configured local model root is not a directory")
    fixture, fixture_bytes = load_fixture(ledger)
    assets = verify_file_set(model_root, ledger["model"]["files"])
    versions = runtime_versions(ledger)
    messages = [
        {"role": "system", "content": ledger["prompt"]["system"]},
        {"role": "user", "content": fixture["question"]},
    ]
    return {
        "ledger_sha256": digest_bytes(ledger_bytes),
        "fixture_sha256": digest_bytes(fixture_bytes),
        "task_input_sha256": digest_bytes(fixture["question"].encode("utf-8")),
        "message_sha256": digest_bytes(canonical(messages)),
        "model_asset_manifest_sha256": digest_bytes(canonical(assets)),
        "model_assets": assets,
        "runtime": versions,
        "source": source_identity(ledger),
        "model_root": model_root,
    }


def emit(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, "at_utc": now(), **fields}, ensure_ascii=False), flush=True)


def worker(ledger_path: Path) -> int:
    started = time.monotonic()
    try:
        ledger, _ = load_ledger(ledger_path)
        fixture, _ = load_fixture(ledger)
        model_root_value = os.environ.get(ledger["model"]["root_env"])
        if not model_root_value:
            raise ValueError("Missing model root")
        model_root = Path(model_root_value).expanduser().resolve()
        emit("runtime_import_started")
        import socket

        def blocked_connect(*_arguments: object, **_keywords: object) -> None:
            raise OSError("Network access is disabled for accountless native inference")

        socket.socket.connect = blocked_connect
        socket.create_connection = blocked_connect
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        import_seconds = time.monotonic() - started
        runtime_versions(ledger)
        torch.set_num_threads(ledger["runtime"]["torch_num_threads"])
        torch.set_num_interop_threads(1)
        torch.manual_seed(ledger["generation"]["seed"])
        emit("runtime_import_finished", elapsed_seconds=import_seconds)

        load_started = time.monotonic()
        emit("model_load_started")
        tokenizer = AutoTokenizer.from_pretrained(
            str(model_root), local_files_only=True, trust_remote_code=False,
        )
        model = AutoModelForCausalLM.from_pretrained(
            str(model_root), local_files_only=True, trust_remote_code=False, dtype=torch.float32,
        )
        model.to("cpu")
        model.eval()
        load_seconds = time.monotonic() - load_started
        emit("model_load_finished", elapsed_seconds=load_seconds)

        messages = [
            {"role": "system", "content": ledger["prompt"]["system"]},
            {"role": "user", "content": fixture["question"]},
        ]
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(prompt, return_tensors="pt")
        inference_started = time.monotonic()
        emit("inference_started", input_tokens=int(inputs["input_ids"].shape[-1]))
        with torch.inference_mode():
            generated = model.generate(
                **inputs,
                max_new_tokens=ledger["generation"]["max_new_tokens"],
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )
        new_tokens = generated[0, inputs["input_ids"].shape[-1]:]
        output = tokenizer.decode(new_tokens, skip_special_tokens=True)
        inference_seconds = time.monotonic() - inference_started
        emit(
            "inference_finished",
            elapsed_seconds=inference_seconds,
            input_tokens=int(inputs["input_ids"].shape[-1]),
            output_tokens=int(new_tokens.shape[-1]),
            model_visible_prompt_sha256=digest_bytes(prompt.encode("utf-8")),
            raw_output=output,
            runtime_import_seconds=import_seconds,
            model_load_seconds=load_seconds,
        )
        return 0
    except Exception as error:
        emit("worker_error", error_type=type(error).__name__, message=str(error))
        return EXIT_EXECUTION


def terminate(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def validate_finished_event(event: dict) -> dict:
    if event.get("event") != "inference_finished":
        raise ValueError("Worker result has an unexpected event type")
    for field in ("input_tokens", "output_tokens"):
        if not isinstance(event.get(field), int) or event[field] < 0:
            raise ValueError(f"Worker result has an invalid {field}")
    for field in ("runtime_import_seconds", "model_load_seconds", "elapsed_seconds"):
        if not isinstance(event.get(field), (int, float)) or event[field] < 0:
            raise ValueError(f"Worker result has an invalid {field}")
    if not isinstance(event.get("raw_output"), str):
        raise ValueError("Worker result has no raw output string")
    if not re.fullmatch(r"[0-9a-f]{64}", str(event.get("model_visible_prompt_sha256", ""))):
        raise ValueError("Worker result has an invalid prompt digest")
    return event


def output_root(ledger: dict) -> Path:
    configured = os.environ.get(ledger["output"]["root_env"])
    if configured:
        return Path(configured).expanduser().resolve()
    return repository_path(ledger["output"]["default_root"])


def base_result(run_id: str, ledger: dict, started_at: str, preflight_record: dict | None) -> dict:
    return {
        "schema_version": 1,
        "record_type": "accountless_native_attempt",
        "run_id": run_id,
        "attempt_id": run_id,
        "started_at": started_at,
        "finished_at": None,
        "status": "running",
        "exit_code": None,
        "native_verdict": None,
        "task": {
            "benchmark": ledger["task"]["benchmark"],
            "id": ledger["task"]["id"],
            "split": ledger["task"]["split"],
            "record_index": ledger["task"]["record_index"],
            "input_sha256": ledger["task"]["question_sha256"],
            "source_line_sha256": ledger["task"]["source_line_sha256"],
        },
        "model": {
            "provider": "local_transformers",
            "id": ledger["model"]["id"],
            "revision": ledger["model"]["revision"],
            "local_files_only": True,
            "device": ledger["model"]["device"],
            "dtype": ledger["model"]["dtype"],
        },
        "generation": ledger["generation"],
        "limits": ledger["limits"],
        "flags": {"measured": True, "synthetic": False, "projected": False},
        "counts": {"model_invocations": 0, "retries": 0, "native_verdicts": 0},
        "timings_seconds": {
            "prerequisite": None,
            "runtime_import": None,
            "model_load": None,
            "inference": None,
            "judge": None,
            "end_to_end": None,
        },
        "local_token_counts": None,
        "provider_usage": None,
        "calculated_cost_usd": None,
        "raw_output": None,
        "preflight": preflight_record,
        "error": None,
        "claim_limit": ledger["claim_limit"],
    }


def run_attempt(ledger_path: Path, run_id: str) -> tuple[Path, dict]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", run_id):
        raise ValueError("run_id must be a lowercase portable identifier")
    ledger, ledger_bytes = load_ledger(ledger_path)
    directory = output_root(ledger) / run_id
    directory.parent.mkdir(parents=True, exist_ok=True)
    directory.mkdir(exist_ok=False)
    started_at = now()
    started = time.monotonic()
    write_json_x(directory / "reservation.json", {"run_id": run_id, "reserved_at": started_at})
    result = base_result(run_id, ledger, started_at, None)

    prerequisite_started = time.monotonic()
    try:
        checked = preflight(ledger_path, ledger, ledger_bytes)
        model_root = checked.pop("model_root")
        checked["checked_at"] = now()
        result["preflight"] = checked
        result["timings_seconds"]["prerequisite"] = time.monotonic() - prerequisite_started
        write_json_x(directory / "preflight.json", checked)
    except Exception as error:
        result.update(
            finished_at=now(), status="preflight_failed", exit_code=EXIT_PREFLIGHT,
            error={"type": type(error).__name__, "message": str(error)},
        )
        result["timings_seconds"]["prerequisite"] = time.monotonic() - prerequisite_started
        result["timings_seconds"]["end_to_end"] = time.monotonic() - started
        write_json_x(directory / "diagnostic.json", result["error"])
        write_json_x(directory / "result.json", result)
        return directory, result

    environment = {
        **os.environ,
        ledger["model"]["root_env"]: str(model_root),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "CUDA_VISIBLE_DEVICES": "",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    command = [sys.executable, "-B", "-m", "src.accountless_native", "_worker", str(ledger_path.resolve())]
    events_path = directory / "events.jsonl"
    stderr_path = directory / "worker-stderr.log"
    final_event = None
    execution_error = None
    with events_path.open("xb") as event_stream, stderr_path.open("xb") as stderr_stream:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=stderr_stream,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        selector = selectors.DefaultSelector()
        if process.stdout is None:
            raise RuntimeError("Worker stdout is unavailable")
        selector.register(process.stdout, selectors.EVENT_READ)
        last_progress = time.monotonic()
        while True:
            current = time.monotonic()
            if current - started > ledger["limits"]["attempt_wall_seconds"]:
                execution_error = {"type": "AttemptTimeout", "message": "Attempt wall time exceeded"}
                terminate(process)
                break
            if current - last_progress > ledger["limits"]["no_progress_seconds"]:
                execution_error = {"type": "NoProgressTimeout", "message": "No progress event within the fixed limit"}
                terminate(process)
                break
            ready = selector.select(timeout=0.5)
            for key, _mask in ready:
                line = key.fileobj.readline()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    execution_error = {"type": "WorkerProtocolError", "message": "Worker emitted non-JSON output"}
                    terminate(process)
                    break
                stored_event = {key: value for key, value in event.items() if key != "raw_output"}
                event_stream.write(canonical(stored_event) + b"\n")
                event_stream.flush()
                last_progress = time.monotonic()
                if event.get("event") == "inference_finished":
                    final_event = event
                elif event.get("event") == "worker_error":
                    execution_error = {"type": event.get("error_type"), "message": event.get("message")}
            if execution_error:
                break
            if process.poll() is not None:
                break
        if process.poll() is None:
            terminate(process)
        worker_exit = process.wait()

    if execution_error or worker_exit != 0 or final_event is None:
        error = execution_error or {"type": "WorkerExit", "message": f"Worker exited {worker_exit} without a result"}
        result.update(finished_at=now(), status="execution_failed", exit_code=EXIT_EXECUTION, error=error)
        result["timings_seconds"]["end_to_end"] = time.monotonic() - started
        write_json_x(directory / "diagnostic.json", error)
        write_json_x(directory / "result.json", result)
        return directory, result

    try:
        final_event = validate_finished_event(final_event)
    except Exception as error:
        failure = {"type": "WorkerProtocolError", "message": str(error)}
        result.update(finished_at=now(), status="execution_failed", exit_code=EXIT_EXECUTION, error=failure)
        result["timings_seconds"]["end_to_end"] = time.monotonic() - started
        write_json_x(directory / "diagnostic.json", failure)
        write_json_x(directory / "result.json", result)
        return directory, result

    raw_output = final_event.pop("raw_output")
    raw_bytes = raw_output.encode("utf-8")
    with (directory / "raw-output.txt").open("xb") as stream:
        stream.write(raw_bytes)
    judge_started = time.monotonic()
    fixture, _ = load_fixture(ledger)
    judged = judge_output(raw_output, fixture["answer"])
    judge_seconds = time.monotonic() - judge_started
    exit_code = EXIT_PASS if judged["verdict"] == "pass" else EXIT_WRONG
    result.update(
        finished_at=now(), status="completed", exit_code=exit_code,
        native_verdict=judged, error=None,
    )
    result["counts"] = {"model_invocations": 1, "retries": 0, "native_verdicts": 1}
    result["timings_seconds"].update(
        runtime_import=final_event["runtime_import_seconds"],
        model_load=final_event["model_load_seconds"],
        inference=final_event["elapsed_seconds"],
        judge=judge_seconds,
        end_to_end=time.monotonic() - started,
    )
    result["local_token_counts"] = {
        "input": final_event["input_tokens"],
        "output": final_event["output_tokens"],
        "kind": "local_tokenizer_count",
    }
    result["model_visible_prompt_sha256"] = final_event["model_visible_prompt_sha256"]
    result["raw_output"] = {"bytes": len(raw_bytes), "sha256": digest_bytes(raw_bytes), "published": False}
    write_json_x(directory / "result.json", result)
    return directory, result


def verify_run(directory: Path) -> dict:
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("Run directory is missing or unsafe")
    result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    if result.get("record_type") != "accountless_native_attempt":
        raise ValueError("Unexpected result record_type")
    if result["counts"]["model_invocations"] == 1:
        content = (directory / "raw-output.txt").read_bytes()
        if len(content) != result["raw_output"]["bytes"] or digest_bytes(content) != result["raw_output"]["sha256"]:
            raise ValueError("Raw output differs from the result record")
        if result["counts"]["native_verdicts"] != 1 or result["native_verdict"]["verdict"] not in {
            "pass", "wrong_answer", "wrong_format",
        }:
            raise ValueError("Completed inference is missing a native verdict")
    if result["flags"] != {"measured": True, "synthetic": False, "projected": False}:
        raise ValueError("Result provenance flags differ")
    if result["counts"]["retries"] != 0:
        raise ValueError("The no-retry contract differs")
    return result


def check_command(ledger_path: Path) -> int:
    try:
        ledger, ledger_bytes = load_ledger(ledger_path)
        checked = preflight(ledger_path, ledger, ledger_bytes)
        checked.pop("model_root")
        print(json.dumps({"status": "ready", **checked}, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(json.dumps({"status": "not_ready", "error": {"type": type(error).__name__, "message": str(error)}}, indent=2))
        return EXIT_PREFLIGHT


def run_command(ledger_path: Path, run_id: str) -> int:
    try:
        directory, result = run_attempt(ledger_path, run_id)
    except FileExistsError:
        print(json.dumps({"status": "collision", "run_id": run_id, "exit_code": EXIT_COLLISION}))
        return EXIT_COLLISION
    except Exception as error:
        print(json.dumps({"status": "preflight_failed", "error": {"type": type(error).__name__, "message": str(error)}}))
        return EXIT_PREFLIGHT
    print(json.dumps({
        "run_id": run_id,
        "status": result["status"],
        "exit_code": result["exit_code"],
        "native_verdict": None if result["native_verdict"] is None else result["native_verdict"]["verdict"],
        "result": str(directory / "result.json"),
    }, indent=2))
    return result["exit_code"]


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("ledger", type=Path)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("ledger", type=Path)
    run_parser.add_argument("--run-id", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("directory", type=Path)
    worker_parser = subparsers.add_parser("_worker")
    worker_parser.add_argument("ledger", type=Path)
    parsed = parser.parse_args(arguments)
    if parsed.command == "check":
        return check_command(parsed.ledger)
    if parsed.command == "run":
        return run_command(parsed.ledger, parsed.run_id)
    if parsed.command == "verify":
        try:
            result = verify_run(parsed.directory)
            print(json.dumps({"verified": result["run_id"], "native_verdict": result["native_verdict"]}, indent=2))
            return 0
        except Exception as error:
            print(f"Verification failed: {error}", file=sys.stderr)
            return EXIT_PREFLIGHT
    return worker(parsed.ledger)


if __name__ == "__main__":
    raise SystemExit(main())
