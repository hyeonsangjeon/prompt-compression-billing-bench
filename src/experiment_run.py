"""Validate a public YAML request and delegate to the existing static or native runner."""

from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import secrets
import sys

import yaml

from .contracts import parse_ledger, validate
from .execution_safety import safety_failure, safety_policy_record
from .native_contract import load_native_ledger
from .protection import digest
from .provenance import ROOT


@dataclass(frozen=True)
class ResolvedRequest:
    request: dict
    request_path: Path
    ledger: dict
    ledger_path: Path
    config_sha256: str
    ledger_sha256: str
    source_commit: str


class LowerRunnerError(RuntimeError):
    pass


def _repository_file(root: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts or relative.as_posix() != value:
        raise ValueError("Paths must be normalized repository-relative names")
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or path.is_symlink() or not path.is_file():
        raise ValueError("A declared input escapes the source repository or is not a regular file")
    return path


def _source_commit(request: dict, environment: dict[str, str]) -> str:
    name = request["source"]["commit_env"]
    value = environment.get(name)
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError(f"Set {name} to the full 40-character execution commit")
    return value


def load_request(
    request_path: Path,
    *,
    root: Path = ROOT,
    environment: dict[str, str] | None = None,
) -> ResolvedRequest:
    path = request_path.resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError("Experiment YAML must be a regular file inside the source repository")
    content = path.read_bytes()
    try:
        request = yaml.safe_load(content)
    except yaml.YAMLError as error:
        raise ValueError("Experiment YAML could not be parsed safely") from error
    if not isinstance(request, dict):
        raise ValueError("Experiment YAML must contain one mapping")
    validate(request, "experiment-request.schema.json")
    ledger_path = _repository_file(root, request["low_level_ledger"]["path"])
    ledger_bytes = ledger_path.read_bytes()
    ledger_sha256 = digest(ledger_bytes)
    if ledger_sha256 != request["low_level_ledger"]["sha256"]:
        raise ValueError("Low-level ledger SHA-256 differs from the YAML request")
    experiment_type = request["experiment"]["type"]
    ledger = parse_ledger(ledger_bytes) if experiment_type == "static" else load_native_ledger(ledger_path)
    resolved = ResolvedRequest(
        request=request,
        request_path=path,
        ledger=ledger,
        ledger_path=ledger_path,
        config_sha256=digest(content),
        ledger_sha256=ledger_sha256,
        source_commit=_source_commit(request, environment or dict(os.environ)),
    )
    _reconcile(resolved, root)
    return resolved


def _reconcile(resolved: ResolvedRequest, root: Path) -> None:
    request, ledger = resolved.request, resolved.ledger
    experiment_type = request["experiment"]["type"]
    if request["condition"] != request["compressor"]["name"]:
        raise ValueError("Condition and compressor name must identify the same arm")
    if request["output"]["directory"] != ledger["output_dir"]:
        raise ValueError("YAML and low-level ledger output directories differ")
    if experiment_type == "static":
        _reconcile_static(request, ledger, root)
    else:
        _reconcile_native(request, ledger)


def _reconcile_static(request: dict, ledger: dict, root: Path) -> None:
    if request["provider"] != {"kind": "none", "endpoint_env": None}:
        raise ValueError("Static measurement has no provider endpoint")
    if request["model"] != {"name": None, "settings": {}}:
        raise ValueError("Static measurement does not run a model")
    name = ledger["compressor"]["name"]
    specification = ledger["compressor"]["tools"][name]
    if request["condition"] != name or request["compressor"] != {
        "name": name, "version": specification["version"]
    }:
        raise ValueError("Static compressor differs from the low-level ledger")
    input_request = request["input"]
    if input_request["kind"] != ledger["inputs"]["kind"] or input_request["root_env"] != ledger["inputs"]["root_env"]:
        raise ValueError("Static input kind or root environment differs from the low-level ledger")
    if input_request["manifest_path"] is None or input_request["manifest_sha256"] is None:
        raise ValueError("Static requests require a hash-bound manifest")
    manifest = _repository_file(root, input_request["manifest_path"])
    if digest(manifest.read_bytes()) != input_request["manifest_sha256"] or input_request["manifest_sha256"] != ledger["inputs"]["manifest_sha256"]:
        raise ValueError("Static manifest hash differs across the YAML, file and low-level ledger")
    if request["execution"] != {
        "repetitions": {"mode": "fixed", "count": ledger["execution"]["passes"]},
        "concurrency": ledger["execution"]["concurrency"],
        "stop_policy": "no_provider_calls",
        "provider_calls_approved": False,
        "baseline_env": None,
    }:
        raise ValueError("Static execution settings differ from the no-provider low-level contract")


def _reconcile_native(request: dict, ledger: dict) -> None:
    model = ledger["model"]
    if request["provider"] != {"kind": model["provider"], "endpoint_env": model["endpoint_env"]}:
        raise ValueError("Native provider metadata differs from the low-level ledger")
    if request["model"] != {
        "name": model["name"],
        "settings": {
            "reported_model": model["reported_model"],
            "temperature": model["temperature"],
            "reasoning_effort": model["reasoning_effort"],
        },
    }:
        raise ValueError("Native model settings differ from the low-level ledger")
    condition = request["condition"]
    if condition not in ledger["conditions"]:
        raise ValueError("Native condition is absent from the low-level ledger")
    specification = ledger["compressor"]["tools"][condition]
    if request["compressor"] != {"name": condition, "version": specification["version"]}:
        raise ValueError("Native compressor differs from the low-level ledger")
    baseline_env = request["execution"]["baseline_env"]
    if (condition == "none" and baseline_env is not None) or (condition != "none" and baseline_env is None):
        raise ValueError("Only compressed native conditions require a baseline environment name")
    if request["input"] != {
        "kind": "terminal_bench_checkout",
        "manifest_path": None,
        "root_env": ledger["benchmark"]["root_env"],
        "manifest_sha256": None,
    }:
        raise ValueError("Native input metadata differs from the pinned benchmark contract")
    expected_execution = {
        "repetitions": {
            "mode": "low_level_stop_rule",
            "minimum": ledger["stability"]["minimum_repetitions"],
            "maximum": ledger["stability"]["maximum_repetitions"],
        },
        "concurrency": ledger["runner"]["concurrency"],
        "stop_policy": "low_level_ledger",
        "provider_calls_approved": request["execution"]["provider_calls_approved"],
        "baseline_env": baseline_env,
    }
    if request["execution"] != expected_execution:
        raise ValueError("Native execution settings differ from the low-level ledger")


@contextmanager
def _static_input_environment(resolved: ResolvedRequest):
    name = resolved.request["input"]["root_env"]
    previous = os.environ.get(name)
    if previous is None:
        manifest = _repository_file(ROOT, resolved.request["input"]["manifest_path"])
        os.environ[name] = str(manifest.parent)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


def _invoke_lower(main, arguments: list[str]) -> dict:
    output, errors = io.StringIO(), io.StringIO()
    with redirect_stdout(output), redirect_stderr(errors):
        code = main(arguments)
    lines = [line for line in output.getvalue().splitlines() if line.strip()]
    if code == 3 and lines:
        try:
            return json.loads(lines[-1])
        except json.JSONDecodeError as error:
            raise LowerRunnerError("Lower-level runner returned invalid JSON") from error
    if code != 0:
        raise LowerRunnerError(errors.getvalue().strip() or f"Lower-level runner exited with status {code}")
    if not lines:
        raise LowerRunnerError("Lower-level runner returned no JSON result")
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as error:
        raise LowerRunnerError("Lower-level runner returned invalid JSON") from error


def _base_result(resolved: ResolvedRequest, started_at: str) -> dict:
    request = resolved.request
    endpoint_env = request["provider"]["endpoint_env"]
    native = request["experiment"]["type"] == "native"
    return {
        "schema_version": 1,
        "run_id": "experiment-check-" + secrets.token_hex(4),
        "started_at": started_at,
        "finished_at": _now(),
        "status": "checked",
        "outcome": "preflight_passed",
        "error": None,
        "labels": {
            "measured": False,
            "synthetic": request["input"]["kind"] == "synthetic_fixture",
            "projected": False,
        },
        "experiment_type": request["experiment"]["type"],
        "provider": {
            "kind": request["provider"]["kind"],
            "endpoint": {
                "source": "not_applicable" if endpoint_env is None else "environment_variable",
                "env_name": endpoint_env,
            },
        },
        "model": request["model"],
        "condition": request["condition"],
        "compressor": request["compressor"],
        "input": {
            "kind": request["input"]["kind"],
            "root_env": request["input"]["root_env"],
            "manifest_path": request["input"]["manifest_path"],
        },
        "output": request["output"],
        "lineage": {
            "source_commit": resolved.source_commit,
            "source_sha256": None,
            "config_path": resolved.request_path.relative_to(ROOT.resolve()).as_posix(),
            "config_sha256": resolved.config_sha256,
            "ledger_sha256": resolved.ledger_sha256,
            "manifest_sha256": request["input"]["manifest_sha256"],
        },
        "provider_usage": {
            "status": "not_applicable" if endpoint_env is None else "not_measured",
            "input_tokens": None,
            "cached_input_tokens": None,
            "output_tokens": None,
        },
        "local_measurement": {"status": "not_measured", "values": []},
        "cost": {
            "status": "not_applicable" if endpoint_env is None else "not_measured",
            "calculated_usd": None,
            "invoice_reconciled": None,
        },
        "quality": {"status": "not_measured", "judge": None},
        "completion": {"technical_status": "not_run", "operator_status": "not_applicable"},
        "execution_safety": safety_policy_record(resolved.ledger, applied=False) if native else None,
        "termination": None,
        "artifacts": {},
    }


def _static_result(result: dict, directory: Path) -> None:
    summary = json.loads((directory / "summary.json").read_bytes())
    measured = summary["measured_local"]
    values = []
    for stage in ("before", "after"):
        for name, value in measured[stage].items():
            values.append({"name": f"{name}_{stage}", "value": value, "unit": measured["units"][name]})
    result.update(
        run_id=summary["run_id"], status="completed", outcome="measurement_completed",
        labels={"measured": True, "synthetic": result["labels"]["synthetic"], "projected": False},
        local_measurement={"status": "measured", "values": values},
        completion={"technical_status": "complete", "operator_status": "not_stopped"},
        artifacts=summary["artifacts"],
    )
    result["lineage"]["source_sha256"] = summary["source_sha256"]


def _native_result(result: dict, directory: Path) -> None:
    summary = json.loads((directory / "summary.json").read_bytes())
    summary_status = summary["status"]
    termination = safety_failure(summary.get("stop_reason"))
    complete = summary_status in ("complete", "inconclusive")
    quality_measured = complete or (
        summary_status == "retrieval_pending"
        and summary.get("completion_status_before_retrieval") in ("complete", "inconclusive")
    )
    operator_status = (
        "not_stopped" if termination is not None
        else "stopped" if summary_status == "stopped"
        else "not_stopped" if complete
        else "not_recorded"
    )
    token_rows = [trial["metrics"]["provider_tokens"] for trial in summary.get("trials", [])]
    unknown = sum(row["unknown_usage_attempts"] for row in token_rows)
    subtotals = {
        name: sum(row["reported_subtotal"][name] for row in token_rows)
        for name in ("input_tokens", "output_tokens")
    }
    cache_known = [row["cached_input_tokens"] for row in token_rows]
    costs = [trial["metrics"]["cost"] for trial in summary.get("trials", [])]
    unknown_cost = sum(row["unknown_cost_attempts"] for row in costs)
    result.update(
        run_id=summary["run_id"],
        status="completed" if complete else "failed",
        outcome="measurement_completed" if complete else "technical_incomplete",
        labels={"measured": quality_measured, "synthetic": False, "projected": False},
        provider_usage={
            "status": "measured" if token_rows and unknown == 0 else "requires_review",
            "input_tokens": subtotals["input_tokens"] if token_rows and unknown == 0 else None,
            "cached_input_tokens": sum(cache_known) if token_rows and all(value is not None for value in cache_known) else None,
            "output_tokens": subtotals["output_tokens"] if token_rows and unknown == 0 else None,
        },
        cost={
            "status": "calculated" if costs and unknown_cost == 0 else "requires_review",
            "calculated_usd": sum(row["known_cost_subtotal_usd"] for row in costs) if costs and unknown_cost == 0 else None,
            "invoice_reconciled": False if costs else None,
        },
        quality={"status": "aggregate_measured" if quality_measured else "unknown", "judge": "terminal-bench-native"},
        completion={"technical_status": "complete" if complete else "incomplete", "operator_status": operator_status},
        execution_safety=summary.get("execution_safety", result.get("execution_safety")),
        termination=termination,
        artifacts={"artifacts.json": summary["artifact_manifest_sha256"]},
    )
    result["lineage"]["source_sha256"] = json.loads((directory / "provenance.json").read_bytes())["source_sha256"]
    if not complete:
        category = (
            termination["stop_kind"] if termination is not None
            else "operator_stopped" if summary_status == "stopped"
            else "native_incomplete"
        )
        result["error"] = {
            "category": category,
            "message": "Native run did not reach its verified technically complete state",
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitized_error(message: str, request: dict) -> str:
    sanitized = message
    names = [request["source"]["commit_env"], request["input"]["root_env"]]
    if request["provider"]["endpoint_env"] is not None:
        names.append(request["provider"]["endpoint_env"])
    if request["execution"]["baseline_env"] is not None:
        names.append(request["execution"]["baseline_env"])
    for section in request.values():
        if isinstance(section, dict):
            names.extend(
                value for key, value in section.items()
                if key.endswith("_env") and isinstance(value, str)
            )
    for name in names:
        value = os.environ.get(name)
        if value:
            sanitized = sanitized.replace(value, f"${name}")
    return sanitized or "Lower-level execution failed without a diagnostic message"


def run_request(request_path: Path, *, execute: bool = False) -> tuple[dict, int]:
    started_at = _now()
    resolved = load_request(request_path)
    request = resolved.request
    result = _base_result(resolved, started_at)
    try:
        if request["experiment"]["type"] == "static":
            from .static_run import main as lower_main

            arguments = [str(resolved.ledger_path), "--source-commit", resolved.source_commit]
            if not execute:
                arguments.append("--check")
            with _static_input_environment(resolved):
                payload = _invoke_lower(lower_main, arguments)
        else:
            from .native_run import main as lower_main

            endpoint_env = request["provider"]["endpoint_env"]
            if not os.environ.get(endpoint_env):
                raise LowerRunnerError(f"Set {endpoint_env} before native preflight")
            if execute and not request["execution"]["provider_calls_approved"]:
                raise LowerRunnerError("Native provider calls need approval in both YAML and the low-level ledger")
            if execute:
                result["execution_safety"] = safety_policy_record(resolved.ledger, applied=True)
            arguments = [
                str(resolved.ledger_path), "--source-commit", resolved.source_commit,
                "--condition", request["condition"],
            ]
            baseline_env = request["execution"]["baseline_env"]
            if baseline_env is not None:
                baseline = os.environ.get(baseline_env)
                if not baseline:
                    raise LowerRunnerError(f"Set {baseline_env} to the verified none baseline directory")
                arguments.extend(["--baseline", baseline])
            arguments.append("--execute" if execute else "--check")
            payload = _invoke_lower(lower_main, arguments)
        if execute:
            directory = Path(payload["directory"]).resolve(strict=True)
            (_static_result if request["experiment"]["type"] == "static" else _native_result)(result, directory)
            request_copy = directory / "experiment-request.yaml"
            request_copy.write_bytes(resolved.request_path.read_bytes())
            result["artifacts"].update({
                "experiment-request.yaml": resolved.config_sha256,
                "summary.json": digest((directory / "summary.json").read_bytes()),
            })
            result["finished_at"] = _now()
            validate(result, "experiment-result.schema.json")
            from .contracts import save_json

            save_json(directory / "experiment-result.json", result)
        else:
            result["finished_at"] = _now()
            validate(result, "experiment-result.schema.json")
        return result, 0 if result["status"] in ("checked", "completed") else 3
    except (LowerRunnerError, KeyError, OSError, ValueError) as error:
        result.update(
            finished_at=_now(), status="failed", outcome="technical_incomplete",
            error={"category": "preflight_error" if not execute else "execution_error", "message": _sanitized_error(str(error), request)},
            completion={"technical_status": "incomplete", "operator_status": "not_recorded"},
        )
        validate(result, "experiment-result.schema.json")
        return result, 3


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", nargs="?", type=Path)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--check", action="store_true", help="Validate and preflight without a provider call (default)")
    actions.add_argument("--execute", action="store_true", help="Run the delegated low-level execution")
    actions.add_argument("--verify-result", type=Path, help="Validate an existing common JSON result")
    args = parser.parse_args(arguments)
    try:
        if args.verify_result:
            value = json.loads(args.verify_result.read_bytes())
            validate(value, "experiment-result.schema.json")
            print(json.dumps({"status": "verified", "run_id": value["run_id"]}))
            return 0
        if args.request is None:
            raise ValueError("Choose an experiment YAML request")
        raw_request = yaml.safe_load(args.request.read_bytes())
        if isinstance(raw_request, dict) and raw_request.get("schema_version") == 2:
            from .benchmark_run import run_benchmark_request

            result, code = run_benchmark_request(args.request, execute=args.execute)
        else:
            result, code = run_request(args.request, execute=args.execute)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except (ValueError, OSError, json.JSONDecodeError, yaml.YAMLError) as error:
        message = (
            "Experiment request file could not be read"
            if isinstance(error, OSError)
            else str(error)
        )
        print(
            json.dumps(
                {
                    "status": "failed",
                    "outcome": "technical_incomplete",
                    "error": {
                        "category": "request_error",
                        "message": message,
                    },
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
