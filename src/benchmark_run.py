"""Resolve one simple benchmark YAML and delegate execution to screening_run."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import secrets
import subprocess

import yaml

from .contracts import validate
from .protection import digest
from .provenance import ROOT
from .screening_contract import load_screening_ledger, require_operational_screening


REFERENCE_LEDGER = "ledgers/screening.template.toml"
TASK_INDEX = "data/experiment/terminal-bench-2.1-task-types.json"
OPERATIONAL_LEDGER_ENV = "SCREENING_OPERATIONAL_LEDGER"
QUALITY_RESULTS = {"pass", "wrong_answer", "wrong_format"}
RUNTIME_FIELDS = (
    ("benchmark", "inventory_sha256"),
    ("queue", "limits_source_reference"),
    ("queue", "deployment_isolation_reference"),
    ("approval", "preregistered"),
    ("approval", "execution_authorized"),
    ("approval", "reference"),
)


@dataclass(frozen=True)
class BenchmarkRequest:
    request: dict
    request_path: Path
    config_sha256: str
    reference_ledger: dict
    reference_ledger_sha256: str
    task_index_sha256: str
    result_path: Path


class BenchmarkRunError(RuntimeError):
    pass


def _repository_file(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts or relative.as_posix() != value:
        raise ValueError("Paths must be normalized repository-relative names")
    candidate = ROOT / relative
    if candidate.is_symlink():
        raise ValueError("A declared input cannot be a symbolic link")
    path = candidate.resolve(strict=True)
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
        raise ValueError("A declared input is not a regular repository file")
    return path


def _result_path(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or relative.parts[0] != "runs" or ".." in relative.parts:
        raise ValueError("Benchmark JSON output must stay under runs/")
    path = (ROOT / relative).resolve()
    if not path.is_relative_to((ROOT / "runs").resolve()) or path.suffix != ".json":
        raise ValueError("Benchmark JSON output must be a .json file under runs/")
    return path


def load_benchmark_request(path: Path) -> BenchmarkRequest:
    if path.is_symlink():
        raise ValueError("Benchmark YAML cannot be a symbolic link")
    request_path = path.resolve(strict=True)
    if not request_path.is_relative_to(ROOT.resolve()) or not request_path.is_file():
        raise ValueError("Benchmark YAML must be a regular file inside the source checkout")
    content = request_path.read_bytes()
    try:
        request = yaml.safe_load(content)
    except yaml.YAMLError as error:
        raise ValueError("Benchmark YAML could not be parsed safely") from error
    if not isinstance(request, dict):
        raise ValueError("Benchmark YAML must contain one mapping")
    validate(request, "benchmark-request.schema.json")

    ledger_path = _repository_file(REFERENCE_LEDGER)
    ledger_bytes = ledger_path.read_bytes()
    ledger = load_screening_ledger(ledger_path)
    task_index_path = _repository_file(TASK_INDEX)
    task_index_bytes = task_index_path.read_bytes()
    task_index = json.loads(task_index_bytes)
    benchmark = request["benchmark"]
    if benchmark["name"] != ledger["benchmark"]["name"] or benchmark["revision"] != ledger["benchmark"]["revision"]:
        raise ValueError("Benchmark name or revision differs from the reference ledger")
    if request["endpoint_env"] != ledger["model"]["endpoint_env"] or request["model"] != ledger["model"]["name"]:
        raise ValueError("Endpoint environment name or model differs from the reference ledger")
    if request["condition"] != ledger["screening"]["condition"]:
        raise ValueError("The public single-task path currently supports only the none condition")
    if (
        task_index.get("benchmark_revision") != benchmark["revision"]
        or benchmark["task"] not in task_index.get("tasks", {})
    ):
        raise ValueError("Task is absent from the fixed Terminal-Bench 2.1 task index")
    return BenchmarkRequest(
        request=request,
        request_path=request_path,
        config_sha256=digest(content),
        reference_ledger=ledger,
        reference_ledger_sha256=digest(ledger_bytes),
        task_index_sha256=digest(task_index_bytes),
        result_path=_result_path(request["output"]),
    )


def _git(*arguments: str) -> bytes:
    result = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(ROOT), *arguments],
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1"},
        capture_output=True,
        timeout=30,
    )
    if result.returncode:
        raise BenchmarkRunError("Git could not verify the execution source")
    return result.stdout


def _source_commit() -> str:
    if _git("rev-parse", "--show-toplevel").decode().strip() != str(ROOT):
        raise BenchmarkRunError("Run the benchmark from the source checkout root")
    commit = _git("rev-parse", "--verify", "HEAD").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise BenchmarkRunError("The current HEAD is not a full Git commit")
    if _git("status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none"):
        raise BenchmarkRunError("The source checkout is not clean; review and commit source changes first")
    for relative in (REFERENCE_LEDGER, TASK_INDEX):
        if _repository_file(relative).read_bytes() != _git("show", f"{commit}:{relative}"):
            raise BenchmarkRunError("A benchmark reference file differs from the current HEAD")
    return commit


def _base_result(resolved: BenchmarkRequest, source_commit: str | None, started_at: str) -> dict:
    request = resolved.request
    ledger = resolved.reference_ledger
    result_relative = resolved.result_path.relative_to(ROOT).as_posix()
    return {
        "schema_version": 1,
        "run_id": "benchmark-check-" + secrets.token_hex(4),
        "started_at": started_at,
        "finished_at": _now(),
        "status": "checked",
        "outcome": "preflight_passed",
        "error": None,
        "labels": {"measured": False, "synthetic": False, "projected": False},
        "experiment_type": "native",
        "provider": {
            "kind": ledger["model"]["provider"],
            "endpoint": {"source": "environment_variable", "env_name": request["endpoint_env"]},
        },
        "model": {
            "name": request["model"],
            "settings": {
                "reported_model": ledger["model"]["reported_model"],
                "temperature": ledger["model"]["temperature"],
                "reasoning_effort": ledger["model"]["reasoning_effort"],
            },
        },
        "condition": request["condition"],
        "compressor": {"name": "none", "version": "unavailable"},
        "input": {
            "kind": "terminal_bench_checkout",
            "root_env": ledger["benchmark"]["root_env"],
            "manifest_path": None,
        },
        "output": {
            "directory": Path(result_relative).parent.as_posix(),
            "publication_tier": "aggregate_only",
            "result_json": result_relative,
        },
        "lineage": {
            "source_commit": source_commit,
            "source_sha256": None,
            "config_path": resolved.request_path.relative_to(ROOT).as_posix(),
            "config_sha256": resolved.config_sha256,
            "ledger_sha256": resolved.reference_ledger_sha256,
            "manifest_sha256": None,
        },
        "provider_usage": {
            "status": "not_measured",
            "input_tokens": None,
            "cached_input_tokens": None,
            "output_tokens": None,
        },
        "local_measurement": {"status": "not_measured", "values": []},
        "cost": {"status": "not_measured", "calculated_usd": None, "invoice_reconciled": None},
        "quality": {"status": "not_measured", "judge": None},
        "completion": {"technical_status": "not_run", "operator_status": "not_applicable"},
        "artifacts": {
            REFERENCE_LEDGER: resolved.reference_ledger_sha256,
            TASK_INDEX: resolved.task_index_sha256,
        },
        "benchmark": request["benchmark"],
        "resolved_contract": {
            "reference_ledger": {"path": REFERENCE_LEDGER, "sha256": resolved.reference_ledger_sha256},
            "execution_ledger_sha256": None,
            "runner": {"module": "src.screening_run", "action": "diagnose-task"},
            "protection": {
                "replay_required": ledger["replay"]["required"],
                "complete_capture_required": ledger["replay"]["require_complete_capture"],
                "bundle_revision": ledger["replay"]["bundle_revision"],
            },
            "retry": {
                "provider_transient_http_attempts": ledger["limits"]["transient_http_attempts"],
                "preparation_retry_maximum": ledger["screening"]["preparation_retry_maximum"],
            },
            "clean_checkout": source_commit is not None,
        },
    }


def _operational_ledger(resolved: BenchmarkRequest) -> tuple[Path, dict, str]:
    raw_path = os.environ.get(OPERATIONAL_LEDGER_ENV)
    if not raw_path:
        raise BenchmarkRunError(f"Set {OPERATIONAL_LEDGER_ENV} to the approved low-level ledger before --execute")
    candidate = Path(raw_path)
    if candidate.is_symlink():
        raise BenchmarkRunError("The approved low-level ledger cannot be a symbolic link")
    path = candidate.resolve(strict=True)
    if not path.is_file():
        raise BenchmarkRunError("The approved low-level ledger is not a regular file")
    runtime = load_screening_ledger(path)
    expected = deepcopy(resolved.reference_ledger)
    for section, field in RUNTIME_FIELDS:
        expected[section][field] = runtime[section][field]
    if runtime != expected:
        raise BenchmarkRunError("The approved low-level ledger changes a fixed reference setting")
    require_operational_screening(runtime)
    if runtime["model"]["endpoint_env"] != resolved.request["endpoint_env"]:
        raise BenchmarkRunError("The approved ledger uses a different endpoint environment name")
    return path, runtime, digest(path.read_bytes())


def _invoke_screening(arguments: list[str]) -> dict:
    from .screening_run import main as screening_main

    output, errors = io.StringIO(), io.StringIO()
    with redirect_stdout(output), redirect_stderr(errors):
        code = screening_main(arguments)
    lines = [line for line in output.getvalue().splitlines() if line.strip()]
    if code not in (0, 3):
        raise BenchmarkRunError(errors.getvalue().strip() or f"The single-task runner exited with status {code}")
    if not lines:
        raise BenchmarkRunError("The single-task runner returned no JSON result")
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as error:
        raise BenchmarkRunError("The single-task runner returned invalid JSON") from error


def _attempt_result(result: dict, directory: Path) -> None:
    summary_path = directory / "summary.json"
    summary = json.loads(summary_path.read_bytes())
    attempt_paths = sorted((directory / "attempts").glob("*/attempt.json"))
    if len(attempt_paths) != 1:
        raise BenchmarkRunError("The single-task run did not preserve exactly one attempt record")
    attempt_path = attempt_paths[0]
    attempt = json.loads(attempt_path.read_bytes())
    classification = attempt.get("classification") or {}
    metrics = classification.get("metrics") or {}
    quality = classification.get("result")
    complete = quality in QUALITY_RESULTS and attempt.get("evidence_disposition") == "quality_result_complete"

    provider_tokens = metrics.get("provider_tokens") or {}
    unknown_usage = provider_tokens.get("unknown_usage_attempts")
    usage_complete = type(unknown_usage) is int and unknown_usage == 0
    result["provider_usage"] = {
        "status": "measured" if usage_complete else "requires_review",
        "input_tokens": provider_tokens.get("input_tokens") if usage_complete else None,
        "cached_input_tokens": provider_tokens.get("cached_input_tokens") if usage_complete else None,
        "output_tokens": provider_tokens.get("output_tokens") if usage_complete else None,
    }
    local_tokens = metrics.get("local_tokens") or {}
    local_values = [
        {"name": name, "value": local_tokens[name], "unit": "tokens"}
        for name in ("input_tokens", "output_tokens")
        if type(local_tokens.get(name)) is int
    ]
    result["local_measurement"] = {
        "status": "measured" if len(local_values) == 2 else "requires_review",
        "values": local_values,
    }
    provider_cost = classification.get("provider_cost") or {}
    calculated_cost = provider_cost.get("calculated_cost_usd")
    result["cost"] = {
        "status": "calculated" if calculated_cost is not None else "requires_review",
        "calculated_usd": calculated_cost,
        "invoice_reconciled": False if calculated_cost is not None else None,
    }
    result.update(
        run_id=summary.get("run_id", result["run_id"]),
        status="completed" if complete else "failed",
        outcome="measurement_completed" if complete else "technical_incomplete",
        labels={"measured": complete, "synthetic": False, "projected": False},
        quality={
            "status": quality if complete else "unknown",
            "judge": "terminal-bench-native" if complete else None,
        },
        completion={
            "technical_status": "complete" if complete else "incomplete",
            "operator_status": "stopped" if summary.get("status") == "stopped" else "not_stopped",
        },
        artifacts={
            **result["artifacts"],
            "summary.json": digest(summary_path.read_bytes()),
            "attempt.json": digest(attempt_path.read_bytes()),
        },
    )
    provenance_path = directory / "inputs" / "provenance.json"
    if provenance_path.is_file():
        result["lineage"]["source_sha256"] = json.loads(provenance_path.read_bytes()).get("source_sha256")
        result["artifacts"]["provenance.json"] = digest(provenance_path.read_bytes())
    if not complete:
        result["error"] = {
            "category": "single_task_incomplete",
            "message": "The delegated run did not reach a verified quality result",
        }


def _environment_names(ledger: dict) -> set[str]:
    names = {OPERATIONAL_LEDGER_ENV}
    for section in ledger.values():
        if isinstance(section, dict):
            names.update(
                value for key, value in section.items()
                if key.endswith("_env") and isinstance(value, str)
            )
    return names


def _sanitize(message: str, ledger: dict) -> str:
    sanitized = message.replace(str(ROOT), "$REPOSITORY_ROOT")
    for name in _environment_names(ledger):
        value = os.environ.get(name)
        if value:
            sanitized = sanitized.replace(value, f"${name}")
    return sanitized or "Benchmark execution failed without a diagnostic message"


def _write_result(path: Path, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != ROOT.parent):
        raise ValueError("Benchmark JSON output cannot use symlinks")
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_benchmark_request(request_path: Path, *, execute: bool = False) -> tuple[dict, int]:
    started_at = _now()
    resolved = load_benchmark_request(request_path)
    source_commit = None
    result = _base_result(resolved, source_commit, started_at)
    try:
        source_commit = _source_commit()
        result["lineage"]["source_commit"] = source_commit
        result["resolved_contract"]["clean_checkout"] = True
        if execute:
            endpoint_env = resolved.request["endpoint_env"]
            if not os.environ.get(endpoint_env):
                raise BenchmarkRunError(f"Set {endpoint_env} before --execute")
            ledger_path, ledger, ledger_sha256 = _operational_ledger(resolved)
            result["resolved_contract"]["execution_ledger_sha256"] = ledger_sha256
            payload = _invoke_screening([
                str(ledger_path),
                "--source-commit",
                source_commit,
                "--diagnose-task",
                resolved.request["benchmark"]["task"],
            ])
            directory_value = payload.get("directory")
            if not isinstance(directory_value, str):
                raise BenchmarkRunError("The single-task runner omitted its result directory")
            directory = Path(directory_value).resolve(strict=True)
            if not directory.is_relative_to((ROOT / "runs").resolve()):
                raise BenchmarkRunError("The single-task runner returned an unexpected result directory")
            _attempt_result(result, directory)
            result["resolved_contract"]["execution_ledger_sha256"] = ledger_sha256
        result["finished_at"] = _now()
        validate(result, "experiment-result.schema.json")
        _write_result(resolved.result_path, result)
        return result, 0 if result["status"] in ("checked", "completed") else 3
    except (BenchmarkRunError, KeyError, OSError, subprocess.SubprocessError, ValueError) as error:
        result.update(
            finished_at=_now(),
            status="failed",
            outcome="technical_incomplete",
            error={
                "category": "execution_error" if execute else "preflight_error",
                "message": _sanitize(str(error), resolved.reference_ledger),
            },
            completion={"technical_status": "incomplete", "operator_status": "not_recorded"},
        )
        validate(result, "experiment-result.schema.json")
        _write_result(resolved.result_path, result)
        return result, 3
