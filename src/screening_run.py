"""Run the hash-bound Terminal-Bench 2.1 screening plan."""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
from datetime import datetime, timezone
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time

from accounting import now
from .blob_retrieval import (
    atomic_json,
    file_digest,
    make_blob_spool,
    resume_blob_spool,
    retrieval_settings,
)
from .compressors import NoOpCompressor, make_compressor
from .contracts import safe_child, save_json
from .harbor_no_time_limits import apply_no_time_limit_policy, command as harbor_command
from .live_observations import POLICY
from .live_transport import DeploymentQueue, FoundrySender, LiveRecorder, ManagedIdentity, start_live_proxy
from .measurement import load_encoder
from .native_judge import collect_native_outcome
from .native_run import prepare_task, runtime_environment, runtime_versions, supervise
from .protection import digest
from .provenance import ROOT, capture, git, verify_snapshot
from .replay_environment import replay_bundle_manifest
from .screening_contract import load_screening_ledger, require_operational_screening
from .runtime_limits import public_queue_record, runtime_queue_limits
from .screening_cost import allocate_active_vm_cost, blob_operation_cost, combined_direct_cost, provider_cost
from .screening_inventory import REVISION, _task_files, canonical_json, verify_inventory
from .screening_scheduler import QUALITY_RESULTS, ScreeningState, make_screening_manifest, verify_screening_manifest
from .task_metrics import collect_trial_metrics, read_events


def screening_harbor_config(
    ledger: dict,
    task_paths: list[Path],
    jobs: Path,
    job_name: str,
    api_base: str,
    *,
    preserve_for_replay: bool,
    install_only: bool = False,
) -> dict:
    runner, model = ledger["runner"], ledger["model"]
    environment = {
        "force_build": False,
        "delete": True,
    }
    if preserve_for_replay:
        environment["import_path"] = runner["environment_import_path"]
    else:
        environment["type"] = "docker"
    concurrency = min(runner["concurrency"], len(task_paths))
    return {
        "job_name": job_name,
        "jobs_dir": str(jobs),
        "n_attempts": 1,
        "n_concurrent_trials": concurrency,
        "install_only": install_only,
        "retry": {"max_retries": 0},
        "quiet": True,
        "environment": environment,
        "verifier": {"disable": False},
        "tasks": [{"path": str(path)} for path in task_paths],
        "agents": [{
            "import_path": runner["agent_import_path"],
            "model_name": "openai/" + model["name"],
            "n_concurrent": concurrency,
            "kwargs": {
                "api_base": api_base,
                "enable_summarize": False,
                "use_responses_api": False,
                "store_all_messages": True,
                "temperature": model["temperature"],
                "reasoning_effort": model["reasoning_effort"],
                "llm_kwargs": {"num_retries": 0},
            },
        }],
    }


def _load_inventory(ledger: dict) -> tuple[Path, dict, dict[str, dict[str, bytes]]]:
    root_value = os.environ.get(ledger["benchmark"]["root_env"])
    inventory_value = os.environ.get(ledger["benchmark"]["inventory_env"])
    if not root_value or not inventory_value:
        raise ValueError("Set the fixed benchmark root and resolved inventory environment variables")
    root = Path(root_value).resolve(strict=True)
    inventory_path = Path(inventory_value).resolve(strict=True)
    if git(root, "rev-parse", "--show-toplevel").decode().strip() != str(root):
        raise ValueError("Benchmark root is not a Git checkout root")
    if git(root, "rev-parse", "HEAD").decode().strip() != REVISION:
        raise ValueError("Benchmark checkout differs from the fixed revision")
    inventory = verify_inventory(json.loads(inventory_path.read_bytes()))
    if inventory["inventory_sha256"] != ledger["benchmark"]["inventory_sha256"]:
        raise ValueError("Resolved inventory hash differs from the execution ledger")
    task_files = {}
    for task in inventory["tasks"]:
        files = _task_files(root, task["task_id"])
        expected = {record["path"]: record for record in task["task_files"]}
        if set(files) != set(expected):
            raise ValueError(f"Task tree differs from inventory: {task['task_id']}")
        for name, content in files.items():
            if len(content) != expected[name]["bytes"] or digest(content) != expected[name]["sha256"]:
                raise ValueError(f"Task file differs from inventory: {task['task_id']}/{name}")
        task_files[task["task_id"]] = files
    return inventory_path, inventory, task_files


def _queue_path(ledger: dict) -> Path:
    value = os.environ.get(ledger["queue"]["state_path_env"])
    if not value or not Path(value).is_absolute():
        raise ValueError("Use one absolute deployment queue path for all callers")
    path = Path(value).resolve()
    if path.is_relative_to(ROOT / "runs"):
        raise ValueError("The deployment queue cannot be private to one run")
    return path


def screening_preflight(ledger_path: Path, source_commit: str) -> dict:
    reporting_target = require_operational_screening(load_screening_ledger(ledger_path))
    ledger = load_screening_ledger(ledger_path)
    provenance, snapshots = capture(ledger_path, source_commit)
    inventory_path, inventory, task_files = _load_inventory(ledger)
    versions = runtime_versions()
    from harbor.models.job.config import JobConfig

    harbor_limit_policy = apply_no_time_limit_policy()
    first_task = Path("/screening/task")
    JobConfig.model_validate(screening_harbor_config(
        ledger, [first_task], Path("/screening/jobs"), "screening-check",
        "http://127.0.0.1:1/check/v1", preserve_for_replay=True,
    ))
    encoder = load_encoder(ledger["measurement"])
    retrieval = retrieval_settings(ledger, ROOT)
    endpoint = os.environ.get(ledger["model"]["endpoint_env"], "")
    sender = FoundrySender(endpoint, ManagedIdentity())
    queue_path = _queue_path(ledger)
    return {
        "ledger": ledger,
        "reporting_target": reporting_target,
        "provenance": provenance,
        "snapshots": snapshots,
        "inventory_path": inventory_path,
        "inventory": inventory,
        "task_files": task_files,
        "runtime_versions": versions,
        "encoder": encoder,
        "retrieval": retrieval,
        "sender": sender,
        "queue_path": queue_path,
        "queue_limits": runtime_queue_limits(ledger["queue"], ledger["schema_version"]),
        "harbor_limit_policy": harbor_limit_policy,
    }


def _task_artifact(
    task: dict,
    ledger: dict,
    source_commit: str,
    intervention: dict | None = None,
) -> dict:
    payload = {
        "schema_version": 1,
        "kind": "screening_attempt_immutable_artifact",
        "source_commit": source_commit,
        "task": task,
        "model": ledger["model"],
        "runner": ledger["runner"],
        "measurement": ledger["measurement"],
        "verifiers": ledger["benchmark"]["verifiers"],
    }
    if ledger.get("schema_version") == 2:
        payload["limits"] = ledger["limits"]
    if intervention is not None:
        payload["intervention"] = intervention
    return {**payload, "artifact_manifest_sha256": digest(canonical_json(payload))}


def _prepare_inputs(
    directory: Path,
    setup: dict,
    source_commit: str,
    run_id: str,
    *,
    execution_scope: dict | None = None,
    condition: str = "none",
    intervention: dict | None = None,
    preliminary_manifest: dict | None = None,
    compressor_ledger_bytes: bytes | None = None,
) -> tuple[dict, dict]:
    inputs = directory / "inputs"
    inputs.mkdir(parents=True, exist_ok=False)
    for name, content in setup["snapshots"].items():
        path = safe_child(inputs, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    save_json(inputs / "provenance.json", setup["provenance"])
    (inputs / "inventory.json").write_bytes(setup["inventory_path"].read_bytes())
    manifest = make_screening_manifest(
        setup["inventory"], source_commit, run_id, condition=condition
    )
    verify_screening_manifest(manifest, setup["inventory"])
    save_json(inputs / "screening-manifest.json", manifest)
    artifacts = {}
    sources = {}
    inventory_by_task = {task["task_id"]: task for task in setup["inventory"]["tasks"]}
    for task_id in sorted(inventory_by_task):
        task = inventory_by_task[task_id]
        if task["exclusion"] is not None:
            continue
        target = inputs / "tasks" / task_id
        sources[task_id] = prepare_task(
            task_id,
            setup["task_files"][task_id],
            target,
            task["image"]["pinned_reference"],
            setup["ledger"]["benchmark"]["verifiers"],
        )
        artifacts[task_id] = _task_artifact(
            task, setup["ledger"], source_commit, intervention
        )
    save_json(inputs / "task-sources.json", sources)
    save_json(inputs / "task-artifacts.json", artifacts)
    if (preliminary_manifest is None) != (compressor_ledger_bytes is None):
        raise ValueError("Preliminary comparison inputs must be supplied together")
    if preliminary_manifest is not None:
        save_json(inputs / "preliminary-comparison-manifest.json", preliminary_manifest)
        (inputs / "compressor-ledger.toml").write_bytes(compressor_ledger_bytes)
    execution = {
        "schema_version": 1,
        "kind": "terminal_bench_screening_execution",
        "run_id": run_id,
        "source_commit": source_commit,
        "ledger_sha256": setup["provenance"]["ledger_sha256"],
        "inventory_sha256": setup["inventory"]["inventory_sha256"],
        "manifest_sha256": manifest["manifest_sha256"],
        "condition": condition,
        "runtime_versions": setup["runtime_versions"],
        "python": sys.version,
        "concurrency": setup["ledger"]["runner"]["concurrency"],
        "deployment_limits": public_queue_record(
            setup["ledger"]["queue"], setup["ledger"]["schema_version"]
        ),
        "harness_stop_policy": setup["ledger"]["limits"],
        "harbor_limit_policy": setup["harbor_limit_policy"],
        "verifier_replay": "same_preserved_state_one_additional_verifier_execution_no_model_call",
        "execution_scope": execution_scope or {
            "kind": "formal_terminal_bench_screening",
            "included_in_formal_screening_denominator": True,
        },
        "started_at": now(),
    }
    if intervention is not None:
        execution["intervention"] = intervention
    save_json(inputs / "execution.json", execution)
    return manifest, artifacts


def _transport_events(transport: Path) -> list[dict]:
    path = transport / "events.jsonl"
    return read_events(path) if path.is_file() else []


def _copy_transport_evidence(transport: Path, attempt_directory: Path, attempt_id: str) -> None:
    target = attempt_directory / "transport"
    target.mkdir()
    lines = []
    events_path = transport / "events.jsonl"
    if events_path.is_file():
        for line in events_path.read_text().splitlines():
            event = json.loads(line)
            if event.get("trial_id") == attempt_id:
                lines.append(line)
    (target / "events.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""))
    for request in sorted(transport.glob("request-*")):
        manifest = request / "manifest.json"
        if manifest.is_file() and json.loads(manifest.read_bytes()).get("trial_id") == attempt_id:
            shutil.copytree(request, target / request.name)


def _attempt_replay(job: Path) -> tuple[dict | None, str | None]:
    paths = list(job.glob("*/workspace-replay/*/manifest.json"))
    if len(paths) != 1:
        return None, "replay_manifest_missing_or_duplicated"
    try:
        replay = replay_bundle_manifest(paths[0])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        return None, type(error).__name__
    if replay.get("capture_phase") != "after_tests_upload_before_verifier":
        return replay, "replay_capture_phase_invalid"
    repeated = replay.get("verifier_replay") or {}
    if (
        replay.get("status") != "complete"
        or repeated.get("status") != "complete"
        or repeated.get("state_restored") is not True
        or repeated.get("same_judgement") is not True
    ):
        return replay, "replay_mismatch_or_incomplete"
    return replay, None


def _explicit_provider_rejection(provider: dict, request_failure: dict | None, replay: dict | None) -> bool:
    requests = provider.get("requests") or []
    rejected = [
        request for request in requests
        if type(request.get("http_status")) is int
        and 400 <= request["http_status"] < 500
        and request["http_status"] not in {408, 409, 429}
    ]
    return bool(
        request_failure
        and rejected
        and replay is not None
        and replay.get("capture_phase") == "teardown_without_verifier"
    )


def _terminal_session_exit_evidence(
    job: Path,
    replay: dict | None,
    request_failure: dict | None,
) -> dict | None:
    if (
        request_failure is not None
        or replay is None
        or replay.get("status") != "complete"
        or replay.get("capture_phase") != "teardown_without_verifier"
    ):
        return None
    result_paths = list(job.glob("*/result.json"))
    trace_paths = list(job.glob("*/agent/command-trace/events.jsonl"))
    if len(result_paths) != 1 or len(trace_paths) != 1:
        return None
    try:
        result_bytes = result_paths[0].read_bytes()
        trace_bytes = trace_paths[0].read_bytes()
        result = json.loads(result_bytes)
        trace = read_events(trace_paths[0])
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    exception = result.get("exception_info") or {}
    message = exception.get("exception_message")
    if (
        exception.get("exception_type") != "RuntimeError"
        or not isinstance(message, str)
        or not re.search(
            r"failed to send (?:non-blocking )?keys:.*no server running on /tmp/tmux-",
            message,
            re.DOTALL,
        )
    ):
        return None
    started = {
        event.get("command_id"): event
        for event in trace
        if event.get("event") == "submission_started"
        and type(event.get("command_id")) is int
    }
    finished = {
        event.get("command_id"): event
        for event in trace
        if event.get("event") == "submission_finished"
        and type(event.get("command_id")) is int
    }
    started_events = [
        event for event in trace
        if event.get("event") == "submission_started"
        and type(event.get("command_id")) is int
    ]
    finished_events = [
        event for event in trace
        if event.get("event") == "submission_finished"
        and type(event.get("command_id")) is int
    ]
    if (
        len(started) != len(started_events)
        or len(finished) != len(finished_events)
        or any(
            not isinstance(event.get("keystrokes"), str)
            or event.get("command_sha256") != digest(event["keystrokes"].encode())
            or type(event.get("batch")) is not int
            for event in started_events
        )
    ):
        return None
    failed = [
        identifier for identifier, event in finished.items()
        if event.get("status") in {"uncertain", "rejected_terminal_session_ended"}
        and event.get("error_type") == "RuntimeError"
        and identifier in started
    ]
    if len(failed) != 1:
        return None
    failed_id = failed[0]
    failed_batch = started[failed_id]["batch"]
    accepted_exit_commands = [
        identifier for identifier, event in started.items()
        if identifier < failed_id
        and event["batch"] == failed_batch
        and finished.get(identifier, {}).get("status") == "accepted_by_terminal"
        and re.search(r"(?:^|[;&|]\s*)exit(?:\s|$)", event.get("keystrokes", ""), re.MULTILINE)
    ]
    if not accepted_exit_commands:
        return None
    return {
        "kind": "terminal_session_ended_after_accepted_exit_command",
        "batch": failed_batch,
        "failed_command_id": failed_id,
        "accepted_exit_command_ids": accepted_exit_commands,
        "native_result_sha256": digest(result_bytes),
        "command_trace_sha256": digest(trace_bytes),
    }


def _evidence_timing_status(
    timing: dict,
    *,
    pre_verifier_exclusion_reason: str | None,
) -> dict:
    unexecuted = {
        "first_verifier_wall_seconds",
        "state_restore_wall_seconds",
        "repeated_verifier_wall_seconds",
        "restore_and_repeated_verifier_wall_seconds",
    }
    result = {}
    for name, value in timing.items():
        if _measured_seconds(value):
            result[name] = {"status": "measured", "reason": None}
        elif pre_verifier_exclusion_reason is not None and name in unexecuted:
            result[name] = {
                "status": "not_applicable",
                "reason": pre_verifier_exclusion_reason,
            }
        else:
            result[name] = {"status": "missing", "reason": "required_stage_not_measured"}
    return result


def _classify_attempt(attempt: dict, process: dict, recorder: LiveRecorder, transport: Path) -> dict:
    attempt_id = attempt["attempt_id"]
    job = attempt["attempt_directory"] / "jobs" / attempt_id
    events = _transport_events(transport)
    provider = provider_cost(events, attempt_id)
    dispatched = provider["http_attempts"] > 0
    with recorder.lock:
        request_failure = recorder.trials[attempt_id]["failure"]
    outcome = collect_native_outcome(job, process=process, transport_failure=None)
    completed_process = not process["timed_out"] and not process["stopped_by_guard"] and process["returncode"] == 0
    metrics = collect_trial_metrics(job, transport, attempt_id, process_complete=completed_process)
    replay, replay_error = _attempt_replay(job)
    terminal_session_exit = _terminal_session_exit_evidence(job, replay, request_failure)
    log_text = (attempt["attempt_directory"] / "harbor.log").read_text(errors="replace")
    native_timeout = any(
        failure.get("reason") in {"native_execution_timeout", "test_timeout_evidence"}
        for failure in outcome["failures"]
        if isinstance(failure, dict)
    )
    result = None
    if not dispatched:
        image_markers = r"(?:manifest unknown|pull access denied|No such image|failed to pull|ImagePull)"
        result = "image_error" if re.search(image_markers, log_text, re.IGNORECASE) else "setup_error"
    elif process["timed_out"]:
        result = "timeout"
    elif native_timeout:
        result = "timeout"
    elif request_failure is not None:
        reason = request_failure["reason"]
        result = "network_error" if reason in {
            "TimeoutError", "ConnectionError", "OSError", "ClientDisconnectedAfterDispatch",
        } else "provider_error"
    elif any(failure.get("reason") == "native_exception" and re.search(
        r"Verifier|Reward", failure.get("exception_type") or ""
    ) for failure in outcome["failures"]):
        result = "verifier_crash"
    elif replay_error is not None:
        result = "replay_mismatch" if replay is not None else "evidence_missing"
    elif not outcome["quality_valid"] or not metrics["measurement_complete"]:
        result = "evidence_missing"
    elif outcome["native_reward"] == 1:
        result = "pass"
    elif "wrong_format" in outcome["failure_categories"]:
        result = "wrong_format"
    else:
        result = "wrong_answer"
    test_ids = sorted({
        failure["test"] for failure in outcome["failures"]
        if isinstance(failure, dict) and isinstance(failure.get("test"), str)
    })
    evidence_timing = {
        "task_process_wall_seconds": process.get("elapsed_seconds"),
        "state_save_wall_seconds": None if replay is None else replay.get("capture_wall_seconds"),
        "first_verifier_wall_seconds": (
            None if replay is None else (replay.get("verifier_replay") or {}).get(
                "original_verifier_wall_seconds"
            )
        ),
        "state_restore_wall_seconds": (
            None if replay is None else (replay.get("verifier_replay") or {}).get("restore_wall_seconds")
        ),
        "repeated_verifier_wall_seconds": (
            None if replay is None else (replay.get("verifier_replay") or {}).get(
                "repeated_verifier_wall_seconds"
            )
        ),
        "restore_and_repeated_verifier_wall_seconds": (
            None if replay is None else (replay.get("verifier_replay") or {}).get("wall_seconds")
        ),
    }
    provider_rejected_before_verifier = (
        result == "provider_error" and _explicit_provider_rejection(provider, request_failure, replay)
    )
    pre_verifier_exclusion_reason = (
        "explicit_provider_rejection_before_first_verifier"
        if provider_rejected_before_verifier else
        "terminal_session_ended_before_first_verifier"
        if result == "replay_mismatch" and terminal_session_exit is not None else None
    )
    return {
        "result": result,
        "provider_dispatched": dispatched,
        "provider_cost": provider,
        "native_outcome": outcome,
        "metrics": metrics,
        "replay_manifest_sha256": None if replay is None else replay.get("manifest_sha256"),
        "replay_error": replay_error,
        "replay_checks": None if replay is None else {
            "capture_status": replay.get("status"),
            "capture_phase": replay.get("capture_phase"),
            "state_restored": (replay.get("verifier_replay") or {}).get("state_restored"),
            "same_judgement": (replay.get("verifier_replay") or {}).get("same_judgement"),
        },
        "evidence_timing": evidence_timing,
        "evidence_timing_status": _evidence_timing_status(
            evidence_timing,
            pre_verifier_exclusion_reason=pre_verifier_exclusion_reason,
        ),
        "technical_exclusion_basis": {
            "kind": pre_verifier_exclusion_reason,
            "original_error_recorded": (
                request_failure is not None or terminal_session_exit is not None
            ),
            "provider_accounting_recorded": len(provider.get("requests") or []) == provider.get("http_attempts"),
            "terminal_session_exit": terminal_session_exit,
        },
        "verifier_test_ids": test_ids,
        "request_failure": request_failure,
    }


def _run_attempt(
    attempt: dict,
    ledger: dict,
    recorder: LiveRecorder,
    server,
    key: str,
    state_path: Path,
    vm_cost_tracker,
) -> dict:
    attempt_directory = attempt["attempt_directory"]
    config = screening_harbor_config(
        ledger,
        [attempt["task_path"]],
        attempt_directory / "jobs",
        attempt["attempt_id"],
        f"http://127.0.0.1:{server.server_port}/{attempt['attempt_id']}/v1",
        preserve_for_replay=True,
    )
    save_json(attempt_directory / "harbor-config.json", config)
    command = harbor_command("run", "--config", str(attempt_directory / "harbor-config.json"))

    def started(process_id: int) -> None:
        state = ScreeningState(state_path)
        try:
            state.mark_attempt_runtime(
                attempt["attempt_id"],
                process_id=process_id,
                artifact_manifest_hash=attempt["artifact_manifest_hash"],
                container_instance_id=attempt["container_instance_id"],
                workspace_instance_id=attempt["workspace_instance_id"],
            )
        finally:
            state.close()

    started_at = now()
    process_started_at = None
    started_monotonic = time.monotonic()
    process = {
        "returncode": None,
        "timed_out": False,
        "stopped_by_guard": False,
        "started_at": started_at,
    }

    def timing_started(value: str) -> None:
        nonlocal process_started_at
        process_started_at = value
        vm_cost_tracker.mark_started(attempt["attempt_id"], value)

    try:
        process = supervise(
            command,
            attempt_directory / "harbor.log",
            recorder,
            runtime_environment(key),
            on_start=started,
            on_timing_start=timing_started,
        )
    except BaseException as error:
        process.update(
            started_at=process_started_at or started_at,
            stopped_by_guard=recorder.stopped.is_set(),
            error_type=type(error).__name__,
            error_message=str(error),
            finished_at=now(),
            elapsed_seconds=time.monotonic() - started_monotonic,
        )
    finally:
        try:
            vm_cost_tracker.mark_finished(attempt["attempt_id"], process)
        finally:
            recorder.close_trial(attempt["attempt_id"])
    return {"attempt": attempt, "process": process}


def _record_provider_requests(state: ScreeningState, attempt_id: str, provider: dict) -> None:
    for request in provider["requests"]:
        tokens = request.get("tokens") or {}
        state.mark_provider_dispatch(
            attempt_id,
            request.get("provider_request_id"),
            request.get("calculated_cost_usd"),
            request.get("billing_unknown", False),
            logical_request=request["logical_request"],
            http_attempt=request["http_attempt"],
            http_status=request.get("http_status"),
            response_sha256=request.get("response_sha256"),
            input_tokens=tokens.get("input_tokens"),
            cached_input_tokens=tokens.get("cached_input_tokens"),
            output_tokens=tokens.get("output_tokens"),
            input_cost_estimate_usd=request.get("unconfirmed_cost_estimate_usd"),
        )


def _finalize_attempt(
    completed: dict,
    classification: dict,
    vm_record: dict,
    state: ScreeningState,
    spool,
    transport: Path,
    *,
    complete_state: bool = True,
) -> dict:
    attempt = completed["attempt"]
    attempt_directory = attempt["attempt_directory"]
    evidence_kind = attempt.get("evidence_kind", "terminal_bench_screening")
    condition = attempt.get("condition_name", "none")
    _copy_transport_evidence(transport, attempt_directory, attempt["attempt_id"])
    _record_provider_requests(state, attempt["attempt_id"], classification["provider_cost"])
    vm = {
        "kind": "equal_share_of_each_concurrent_active_vm_segment",
        "currency": "USD",
        **vm_record,
    }
    direct = combined_direct_cost(
        classification["provider_cost"],
        vm,
        {
            "kind": "blob_cost_pending_until_upload_operations_are_recorded",
            "calculated_cost_usd": None,
            "confirmed_cost_usd": 0.0,
        },
    )
    record = {
        "schema_version": 1,
        "kind": evidence_kind + "_attempt",
        "trial_id": attempt["trial_id"],
        "attempt_id": attempt["attempt_id"],
        "attempt_number": attempt["attempt_number"],
        "task_id": attempt["task_id"],
        "repetition": attempt["repetition"],
        "condition": condition,
        "artifact_manifest_sha256": attempt["artifact_manifest_hash"],
        "container_instance_id": attempt["container_instance_id"],
        "workspace_instance_id": attempt["workspace_instance_id"],
        "process": completed["process"],
        "classification": classification,
        "active_vm_cost": vm,
        "direct_cost_before_blob": direct,
        "finished_at": now(),
    }
    save_json(attempt_directory / "attempt.json", record)
    staged = spool.stage_directory(
        attempt_directory,
        attempt["attempt_id"],
        kind=evidence_kind + "_attempt",
        metadata={
            "trial_id": attempt["trial_id"],
            "attempt_id": attempt["attempt_id"],
            "task_id": attempt["task_id"],
            "repetition": attempt["repetition"],
            "condition": condition,
            "result": classification["result"],
        },
    )
    finalized = {"record": record, "retrieval": staged}
    if complete_state:
        _complete_finalized_attempt(finalized, state)
    return finalized


def _complete_finalized_attempt(finalized: dict, state: ScreeningState) -> None:
    record = finalized["record"]
    classification = record["classification"]
    state.complete_attempt(
        record["attempt_id"],
        classification["result"],
        provider_dispatched=classification["provider_dispatched"],
        evidence_sha256=finalized["retrieval"]["metadata"]["source_tree_sha256"],
        cost_usd=record["direct_cost_before_blob"]["calculated_cost_usd"],
        verifier_test_ids=classification["verifier_test_ids"],
    )


def _attempt_intervals(completed: list[dict]) -> list[dict]:
    intervals = []
    for item in completed:
        process = item["process"]
        try:
            started = datetime.fromisoformat(process["started_at"]).timestamp()
            finished = datetime.fromisoformat(process["finished_at"]).timestamp()
        except (KeyError, ValueError, TypeError) as error:
            raise ValueError("Attempt timing is missing or invalid; VM cost cannot be replaced with zero") from error
        if finished < started:
            raise ValueError("Attempt timing finishes before it starts")
        intervals.append({
            "attempt_id": item["attempt"]["attempt_id"],
            "started_epoch": started,
            "finished_epoch": finished,
        })
    return intervals


class _ActiveVmCostTracker:
    def __init__(self, hourly_rate_usd: float):
        self.hourly_rate_usd = hourly_rate_usd
        self.lock = threading.Lock()
        self.intervals = {}

    @staticmethod
    def _epoch(value: object) -> float:
        if not isinstance(value, str):
            raise ValueError("Attempt timing is missing or invalid; VM cost cannot be replaced with zero")
        try:
            return datetime.fromisoformat(value).timestamp()
        except ValueError as error:
            raise ValueError(
                "Attempt timing is missing or invalid; VM cost cannot be replaced with zero"
            ) from error

    def mark_started(self, attempt_id: str, started_at: str) -> None:
        started_epoch = self._epoch(started_at)
        with self.lock:
            if attempt_id in self.intervals:
                raise ValueError("Attempt VM timing start is duplicated")
            self.intervals[attempt_id] = {
                "attempt_id": attempt_id,
                "started_epoch": started_epoch,
                "finished_epoch": None,
            }

    def mark_finished(self, attempt_id: str, process: dict) -> None:
        started_epoch = self._epoch(process.get("started_at"))
        finished_epoch = self._epoch(process.get("finished_at"))
        if finished_epoch < started_epoch:
            raise ValueError("Attempt timing finishes before it starts")
        with self.lock:
            interval = self.intervals.get(attempt_id)
            if interval is None:
                interval = {
                    "attempt_id": attempt_id,
                    "started_epoch": started_epoch,
                    "finished_epoch": None,
                }
                self.intervals[attempt_id] = interval
            if interval["started_epoch"] != started_epoch:
                raise ValueError("Attempt VM timing start changed during execution")
            if interval["finished_epoch"] is not None:
                raise ValueError("Attempt VM timing finish is duplicated")
            interval["finished_epoch"] = finished_epoch

    def allocation_for(self, attempt_id: str) -> dict:
        with self.lock:
            target = self.intervals.get(attempt_id)
            if target is None or target["finished_epoch"] is None:
                raise ValueError("Completed attempt VM timing is unavailable")
            target_finished = target["finished_epoch"]
            intervals = []
            for interval in self.intervals.values():
                if interval["started_epoch"] > target_finished:
                    continue
                finished = interval["finished_epoch"]
                intervals.append({
                    "attempt_id": interval["attempt_id"],
                    "started_epoch": interval["started_epoch"],
                    "finished_epoch": (
                        target_finished if finished is None else min(finished, target_finished)
                    ),
                })
        allocation = allocate_active_vm_cost(intervals, self.hourly_rate_usd)
        if attempt_id not in allocation["attempts"] or not allocation["reconciles"]:
            raise ValueError("Completed attempt VM cost allocation is incomplete")
        return allocation["attempts"][attempt_id]


def _run_completion_driven(max_workers: int, next_item, run_item, complete_item) -> bool:
    if type(max_workers) is not int or max_workers < 1:
        raise ValueError("Completion-driven worker count must be positive")
    accepting_new = True
    available_workers = max_workers
    sequence = 0
    with ThreadPoolExecutor(
        max_workers=max_workers, thread_name_prefix="screening-trial"
    ) as executor:
        active = {}

        def fill_open_workers() -> None:
            nonlocal available_workers, sequence
            while accepting_new and available_workers:
                item = next_item()
                if item is None:
                    break
                future = executor.submit(run_item, item)
                active[future] = sequence
                available_workers -= 1
                sequence += 1

        fill_open_workers()
        while active:
            completed_futures, _pending = wait(active, return_when=FIRST_COMPLETED)
            completed = []
            for future in completed_futures:
                submitted_at = active.pop(future)
                completed.append((submitted_at, future.result()))
            for _submitted_at, result in sorted(completed, key=lambda item: item[0]):
                replace_worker, stop_new = complete_item(result)
                if type(replace_worker) is not bool or type(stop_new) is not bool:
                    raise ValueError("Completed work decision must contain two booleans")
                if replace_worker:
                    available_workers += 1
                if stop_new:
                    accepting_new = False
            fill_open_workers()
    return accepting_new


def _run_cost_summary(directory: Path, state: ScreeningState, retrieval: dict, ledger: dict) -> dict:
    provider_state = state.all_provider_cost_state()
    continuation_cost = state.continuation_cost_state()
    provider = {
        "kind": "provider_usage_times_fixed_rates_not_invoice_reconciliation",
        "currency": "USD",
        "requests": provider_state["requests"],
        "known_cost_usd": provider_state["known_cost_usd"],
        "unknown_attempts": provider_state["unknown_requests"],
        "unconfirmed_input_cost_estimate_usd": provider_state[
            "unconfirmed_input_cost_estimate_usd"
        ],
        "unknown_attempts_without_input_estimate": provider_state[
            "unknown_requests_without_input_estimate"
        ],
        "calculated_cost_usd": (
            provider_state["known_cost_usd"] if provider_state["unknown_requests"] == 0 else None
        ),
    }
    vm_values = []
    missing_vm_records = 0
    for path in sorted((directory / "attempts").glob("*/attempt.json")):
        record = json.loads(path.read_bytes()).get("active_vm_cost") or {}
        value = record.get("calculated_cost_usd")
        if (
            type(value) not in (int, float)
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
        ):
            missing_vm_records += 1
        else:
            vm_values.append(value)
    local_vm_cost = sum(vm_values) if missing_vm_records == 0 else None
    vm = {
        "kind": "sum_of_attempt_active_vm_allocations",
        "currency": "USD",
        "attempts_with_cost": len(vm_values) + continuation_cost["attempts"],
        "attempts_missing_cost": missing_vm_records,
        "linked_prior_attempts": continuation_cost["attempts"],
        "linked_prior_cost_usd": continuation_cost["active_vm_cost_usd"],
        "calculated_cost_usd": (
            None if local_vm_cost is None
            else local_vm_cost + continuation_cost["active_vm_cost_usd"]
        ),
    }
    local_blob = blob_operation_cost(
        retrieval["items"],
        ledger["cost"]["blob_write_per_10000_operations_usd"],
        ledger["cost"]["blob_read_per_10000_operations_usd"],
        ledger["cost"]["same_region_network_per_gb_usd"],
    )
    blob = {
        **local_blob,
        "kind": "current_spool_plus_linked_prior_blob_and_network_cost",
        "current_run": local_blob,
        "linked_prior_attempts": continuation_cost["attempts"],
        "linked_prior_calculated_cost_usd": continuation_cost["blob_network_cost_usd"],
        "calculated_cost_usd": (
            None if local_blob["calculated_cost_usd"] is None
            else local_blob["calculated_cost_usd"] + continuation_cost["blob_network_cost_usd"]
        ),
        "confirmed_cost_usd": (
            local_blob["confirmed_cost_usd"] + continuation_cost["blob_network_cost_usd"]
        ),
    }
    return {
        "kind": "screening_direct_attributable_variable_cost",
        "provider": provider,
        "active_vm": vm,
        "blob_and_network": blob,
        "combined": combined_direct_cost(provider, vm, blob),
        "linked_prior_attempts_with_unknown_direct_cost": continuation_cost[
            "attempts_with_unknown_direct_cost"
        ],
        "shared_idle_approval_wait_and_one_time_setup_included": False,
    }


def _new_attempt_context(claimed: dict, directory: Path, artifacts: dict) -> dict:
    attempt_directory = directory / "attempts" / claimed["attempt_id"]
    attempt_directory.mkdir(parents=True, exist_ok=False)
    return {
        **claimed,
        "attempt_directory": attempt_directory,
        "task_path": directory / "inputs" / "tasks" / claimed["task_id"],
        "artifact_manifest_hash": artifacts[claimed["task_id"]]["artifact_manifest_sha256"],
        "container_instance_id": "container-" + secrets.token_hex(16),
        "workspace_instance_id": "workspace-" + secrets.token_hex(16),
    }


def _write_checkpoint(directory: Path, state: ScreeningState, summary: dict) -> Path:
    checkpoint = directory / "checkpoint"
    if checkpoint.exists():
        shutil.rmtree(checkpoint)
    checkpoint.mkdir()
    state.backup(checkpoint / "state.sqlite3")
    save_json(checkpoint / "summary.json", summary)
    return checkpoint


def _stage_checkpoint(directory: Path, state: ScreeningState, summary: dict, spool) -> dict:
    existing = []
    for record in spool.report()["items"]:
        match = re.fullmatch(r"run-state-([0-9]{6})", record["item_id"])
        if match:
            existing.append(int(match[1]))
    sequence = max([summary.get("checkpoint_sequence", 0), *existing]) + 1
    summary["checkpoint_sequence"] = sequence
    summary["state"] = state.summary()
    summary["last_checkpoint_at"] = now()
    checkpoint = _write_checkpoint(directory, state, summary)
    staged = spool.stage_directory(
        checkpoint,
        f"run-state-{sequence:06d}",
        kind="terminal_bench_screening_state",
        metadata={
            "status": summary["status"],
            "completed_attempts": summary["state"]["completed_attempts"],
            "checkpoint_sequence": sequence,
        },
    )
    summary["latest_checkpoint"] = staged
    atomic_json(directory / "summary.json", summary)
    return staged


def _measured_seconds(value: object) -> bool:
    return type(value) in (int, float) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _completed_attempt_evidence(record: dict, retrieval_record: dict | None, ledger: dict) -> dict:
    classification = record["classification"]
    timing = classification["evidence_timing"]
    full_replay_timings = [
        name for name in (
            "task_process_wall_seconds",
            "state_save_wall_seconds",
            "first_verifier_wall_seconds",
            "state_restore_wall_seconds",
            "repeated_verifier_wall_seconds",
        )
        if not _measured_seconds(timing.get(name))
    ]
    upload_seconds = None if retrieval_record is None else retrieval_record.get("upload_wall_seconds")
    exclusion_basis = classification.get("technical_exclusion_basis") or {}
    exclusion_kind = exclusion_basis.get("kind")
    explicit_rejection = exclusion_kind == "explicit_provider_rejection_before_first_verifier"
    terminal_session_exit = exclusion_kind == "terminal_session_ended_before_first_verifier"
    pre_verifier_technical_exclusion = explicit_rejection or terminal_session_exit
    required_timings = [
        name for name in ("task_process_wall_seconds", "state_save_wall_seconds")
        if not _measured_seconds(timing.get(name))
    ] if pre_verifier_technical_exclusion else list(full_replay_timings)
    if not _measured_seconds(upload_seconds):
        required_timings.append("upload_wall_seconds")
    timing_status = classification.get("evidence_timing_status") or {}
    not_applicable_timings = sorted(
        name for name, status in timing_status.items()
        if status.get("status") == "not_applicable"
    )
    replay_checks = classification.get("replay_checks") or {}
    remote_hash_verified = (
        retrieval_record is not None
        and retrieval_record.get("upload_state") == "uploaded"
        and retrieval_record.get("remote_verified_at") is not None
    )
    provider = classification.get("provider_cost") or {}
    provider_accounting_complete = (
        type(provider.get("http_attempts")) is int
        and provider["http_attempts"] >= 0
        and len(provider.get("requests") or []) == provider["http_attempts"]
    )
    vm = record.get("active_vm_cost") or {}
    active_vm_cost_complete = _measured_seconds(vm.get("calculated_cost_usd"))
    blob = None
    if retrieval_record is not None:
        try:
            blob = blob_operation_cost(
                [retrieval_record],
                ledger["cost"]["blob_write_per_10000_operations_usd"],
                ledger["cost"]["blob_read_per_10000_operations_usd"],
                ledger["cost"]["same_region_network_per_gb_usd"],
            )
        except (KeyError, TypeError, ValueError):
            blob = None
    blob_cost_complete = blob is not None and blob.get("calculated_cost_usd") is not None
    cost_accounting_complete = provider_accounting_complete and active_vm_cost_complete and blob_cost_complete
    strict_replay_complete = (
        classification.get("replay_error") is None
        and replay_checks.get("capture_status") == "complete"
        and replay_checks.get("state_restored") is True
        and replay_checks.get("same_judgement") is True
    )
    explicit_rejection_complete = (
        explicit_rejection
        and classification["result"] == "provider_error"
        and replay_checks.get("capture_status") == "complete"
        and replay_checks.get("capture_phase") == "teardown_without_verifier"
        and (classification.get("technical_exclusion_basis") or {}).get("original_error_recorded") is True
        and not required_timings
        and set(not_applicable_timings) == {
            "first_verifier_wall_seconds",
            "repeated_verifier_wall_seconds",
            "restore_and_repeated_verifier_wall_seconds",
            "state_restore_wall_seconds",
        }
    )
    terminal_session_exit_complete = (
        terminal_session_exit
        and classification["result"] == "replay_mismatch"
        and replay_checks.get("capture_status") == "complete"
        and replay_checks.get("capture_phase") == "teardown_without_verifier"
        and exclusion_basis.get("original_error_recorded") is True
        and (exclusion_basis.get("terminal_session_exit") or {}).get("kind")
            == "terminal_session_ended_after_accepted_exit_command"
        and not required_timings
        and set(not_applicable_timings) == {
            "first_verifier_wall_seconds",
            "repeated_verifier_wall_seconds",
            "restore_and_repeated_verifier_wall_seconds",
            "state_restore_wall_seconds",
        }
    )
    result = classification["result"]
    quality_result = result in QUALITY_RESULTS
    completed_evidence = (
        remote_hash_verified
        and cost_accounting_complete
        and (
            (strict_replay_complete and not required_timings)
            or explicit_rejection_complete
            or terminal_session_exit_complete
        )
    )
    disposition = (
        "quality_result_complete" if completed_evidence and quality_result
        else "technical_exclusion_complete" if completed_evidence
        else "incomplete"
    )
    return {
        "attempt_id": record["attempt_id"],
        "task_id": record["task_id"],
        "result": result,
        "quality_result": quality_result,
        "evidence_disposition": disposition,
        "strict_replay_complete": strict_replay_complete,
        "explicit_provider_rejection_complete": explicit_rejection_complete,
        "terminal_session_exit_complete": terminal_session_exit_complete,
        "remote_hash_verified": remote_hash_verified,
        "timing": {**timing, "upload_wall_seconds": upload_seconds},
        "missing_timing_fields": required_timings,
        "not_applicable_timing_fields": not_applicable_timings,
        "cost_accounting_complete": cost_accounting_complete,
        "cost": {
            "provider_calculated_cost_usd": provider.get("calculated_cost_usd"),
            "provider_known_cost_usd": provider.get("known_cost_usd"),
            "provider_unconfirmed_cost_estimate_usd": provider.get(
                "unconfirmed_cost_estimate_usd"
            ),
            "active_vm_calculated_cost_usd": vm.get("calculated_cost_usd"),
            "blob_and_network_calculated_cost_usd": (
                None if blob is None else blob.get("calculated_cost_usd")
            ),
        },
        "evidence_complete": completed_evidence,
    }


def _verify_completed_batch(
    finalized: list[dict],
    checkpoint: dict,
    spool,
    wait_seconds: float,
    batch_number: int,
    ledger: dict,
) -> dict:
    attempt_ids = [item["record"]["attempt_id"] for item in finalized]
    item_ids = [*attempt_ids, checkpoint["item_id"]]
    started = time.monotonic()
    try:
        retrieval = spool.wait_for_upload(item_ids, wait_seconds)
        wait_error = None
    except (OSError, RuntimeError, ValueError) as error:
        retrieval = {"status": "retrieval_pending", "items": []}
        wait_error = {"type": type(error).__name__, "message": str(error)}
    indexed = {item["item_id"]: item for item in retrieval["items"]}
    attempts = [
        _completed_attempt_evidence(
            finalized_attempt["record"],
            indexed.get(finalized_attempt["record"]["attempt_id"]),
            ledger,
        )
        for finalized_attempt in finalized
    ]
    checkpoint_record = indexed.get(checkpoint["item_id"])
    checkpoint_verified = (
        checkpoint_record is not None
        and checkpoint_record.get("upload_state") == "uploaded"
        and checkpoint_record.get("remote_verified_at") is not None
    )
    complete = (
        retrieval["status"] == "uploaded"
        and checkpoint_verified
        and bool(attempts)
        and all(item["evidence_complete"] for item in attempts)
    )
    return {
        "kind": "screening_batch_evidence_verification",
        "batch_number": batch_number,
        "attempt_count": len(attempts),
        "attempts": attempts,
        "checkpoint_item_id": checkpoint["item_id"],
        "checkpoint_remote_hash_verified": checkpoint_verified,
        "retrieval_status": retrieval["status"],
        "retrieval_wait_wall_seconds": time.monotonic() - started,
        "retrieval_error": wait_error,
        "additional_claims_allowed": complete,
    }


def _verify_finalized_attempt(finalized: dict, spool, wait_seconds: float, ledger: dict) -> dict:
    attempt_id = finalized["record"]["attempt_id"]
    started = time.monotonic()
    try:
        retrieval = spool.wait_for_upload([attempt_id], wait_seconds)
        wait_error = None
    except (OSError, RuntimeError, ValueError) as error:
        retrieval = {"status": "retrieval_pending", "items": []}
        wait_error = {"type": type(error).__name__, "message": str(error)}
    indexed = {item["item_id"]: item for item in retrieval["items"]}
    evidence = _completed_attempt_evidence(
        finalized["record"], indexed.get(attempt_id), ledger
    )
    return {
        "kind": "screening_completed_attempt_evidence_verification",
        "attempt": evidence,
        "retrieval_status": retrieval["status"],
        "retrieval_wait_wall_seconds": time.monotonic() - started,
        "retrieval_error": wait_error,
        "completed_evidence_recording_allowed": evidence["evidence_complete"],
    }


def _continuation_file(directory: Path, relative: str) -> Path:
    path = directory / relative
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(directory):
        raise ValueError(f"Continuation evidence file is missing or unsafe: {relative}")
    return path


_PUBLIC_BLOB_STATE_FIELDS = (
    "kind", "item_id", "metadata", "destination", "payload", "manifest_blob",
    "manifest_uploaded_last", "upload_state", "attempts", "first_attempt_at",
    "last_attempt_at", "last_error_category", "uploaded_at", "payload_etag",
    "manifest_etag", "remote_verified_at", "payload_verify_request_id",
    "manifest_verify_request_id", "manifest_bytes", "operations",
)


def _verified_prior_blob_spool(
    directory: Path,
    setup: dict,
    *,
    run_id: str,
    source_commit: str,
    ledger_sha256: str,
) -> tuple[dict, dict]:
    if directory.is_symlink():
        raise ValueError("Continuation Blob spool cannot be a symlink")
    directory = directory.resolve(strict=True)
    if not directory.is_dir() or directory.name != run_id:
        raise ValueError("Continuation Blob spool does not match the prior run")
    state_paths = sorted(directory.glob("*/state.json"))
    if not state_paths:
        raise ValueError("Continuation Blob spool has no staged items")
    client = setup["retrieval"]["client"]
    prefix = setup["retrieval"]["prefix"]
    destination = {
        "account_url_sha256": digest(client.account_url.encode()),
        "container": client.container,
        "prefix": prefix,
    }
    items = []
    inventory = []
    seen = set()
    for state_path in state_paths:
        item_directory = state_path.parent
        if (
            item_directory.is_symlink()
            or state_path.is_symlink()
            or not state_path.is_file()
            or item_directory.parent != directory
        ):
            raise ValueError("Continuation Blob spool item path is unsafe")
        try:
            state_bytes = state_path.read_bytes()
            state = json.loads(state_bytes)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("Continuation Blob spool state is unreadable") from error
        item_id = state.get("item_id")
        if (
            not isinstance(item_id, str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", item_id)
            or item_id != item_directory.name
            or item_id in seen
        ):
            raise ValueError("Continuation Blob spool item identity is invalid or duplicated")
        seen.add(item_id)
        if (
            state.get("run_id") != run_id
            or state.get("source_commit") != source_commit
            or state.get("ledger_sha256") != ledger_sha256
            or state.get("condition") != "none"
            or state.get("destination") != destination
        ):
            raise ValueError("Continuation Blob spool lineage or destination differs")
        remote = f"{prefix}/{source_commit}/{run_id}/none/{item_id}"
        payload_record = state.get("payload") or {}
        payload = item_directory / payload_record.get("name", "")
        if (
            payload_record.get("name") != "payload.tar"
            or payload_record.get("blob") != remote + "/payload.tar"
            or state.get("manifest_blob") != remote + "/manifest.json"
            or payload.is_symlink()
            or not payload.is_file()
            or payload.parent != item_directory
        ):
            raise ValueError("Continuation Blob spool payload boundary differs")
        payload_bytes = payload_record.get("bytes")
        payload_sha256 = payload_record.get("sha256")
        if (
            type(payload_bytes) is not int
            or payload_bytes < 0
            or not re.fullmatch(r"[0-9a-f]{64}", payload_sha256 or "")
            or payload.stat().st_size != payload_bytes
            or file_digest(payload) != payload_sha256
        ):
            raise ValueError("Continuation Blob spool payload differs from its recorded hash")
        operations = state.get("operations") or {}
        if (
            state.get("manifest_uploaded_last") is not True
            or state.get("upload_state") != "uploaded"
            or not state.get("remote_verified_at")
            or not state.get("payload_verify_request_id")
            or not state.get("manifest_verify_request_id")
            or any(
                type((operations.get(name) or {}).get("succeeded")) is not int
                or operations[name]["succeeded"] < 1
                for name in (
                    "payload_write", "manifest_write",
                    "payload_verify_read", "manifest_verify_read",
                )
            )
        ):
            raise ValueError("Continuation Blob spool item lacks completed remote verification")
        try:
            public = {name: state[name] for name in _PUBLIC_BLOB_STATE_FIELDS}
        except KeyError as error:
            raise ValueError("Continuation Blob spool state is incomplete") from error
        public["upload_wall_seconds"] = state.get("upload_wall_seconds")
        items.append(public)
        inventory.append({
            "item_id": item_id,
            "state_sha256": digest(state_bytes),
            "payload_bytes": payload_bytes,
            "payload_sha256": payload_sha256,
        })
    report = {
        "schema_version": 1,
        "kind": "native_blob_retrieval",
        **destination,
        "run_id": run_id,
        "source_commit": source_commit,
        "ledger_sha256": ledger_sha256,
        "condition": "none",
        "upload_state": "uploaded",
        "items": sorted(items, key=lambda item: item["item_id"]),
        "nas_read_verification": "pending_external",
        "credentials_recorded": False,
    }
    inventory_record = {
        "kind": "read_only_verified_blob_spool_inventory",
        "run_id": run_id,
        "source_commit": source_commit,
        "ledger_sha256": ledger_sha256,
        "condition": "none",
        "items": inventory,
    }
    recovery = {
        "kind": "read_only_local_spool_payload_and_remote_verification_state",
        "item_count": len(items),
        "inventory_sha256": digest(canonical_json(inventory_record)),
    }
    return report, recovery


def _merge_prior_retrieval(persisted: dict, spool: dict) -> tuple[dict, dict]:
    lineage_fields = (
        "schema_version", "kind", "account_url_sha256", "container", "prefix",
        "run_id", "source_commit", "ledger_sha256", "condition", "credentials_recorded",
    )
    if any(persisted.get(name) != spool.get(name) for name in lineage_fields):
        raise ValueError("Persisted retrieval and continuation Blob spool lineage differ")
    persisted_items = persisted.get("items")
    spool_items = spool.get("items")
    if not isinstance(persisted_items, list) or not isinstance(spool_items, list):
        raise ValueError("Continuation retrieval items are invalid")
    persisted_by_id = {item.get("item_id"): item for item in persisted_items}
    spool_by_id = {item.get("item_id"): item for item in spool_items}
    if (
        None in persisted_by_id
        or None in spool_by_id
        or len(persisted_by_id) != len(persisted_items)
        or len(spool_by_id) != len(spool_items)
    ):
        raise ValueError("Continuation retrieval repeats or omits an item identity")
    if set(persisted_by_id) - set(spool_by_id):
        raise ValueError("Continuation Blob spool omits a persisted retrieval item")
    if any(spool_by_id[item_id] != item for item_id, item in persisted_by_id.items()):
        raise ValueError("Continuation Blob spool changed a persisted retrieval item")
    recovered = sorted(set(spool_by_id) - set(persisted_by_id))
    return spool, {
        "persisted_item_count": len(persisted_items),
        "effective_item_count": len(spool_items),
        "recovered_item_count": len(recovered),
        "recovered_item_ids": recovered,
    }


def _continuation_state_costs(connection: sqlite3.Connection) -> dict:
    local_provider = dict(connection.execute(
        """SELECT COUNT(*) AS requests,
                  COALESCE(SUM(calculated_cost_usd),0) AS known_cost_usd,
                  COALESCE(SUM(billing_unknown),0) AS unknown_requests,
                  COALESCE(SUM(CASE WHEN billing_unknown THEN input_cost_estimate_usd ELSE 0 END),0)
                    AS unconfirmed_input_cost_estimate_usd,
                  COALESCE(SUM(CASE WHEN billing_unknown AND input_cost_estimate_usd IS NULL
                                    THEN 1 ELSE 0 END),0)
                    AS unknown_requests_without_input_estimate,
                  COALESCE(SUM(CASE WHEN NOT billing_unknown AND calculated_cost_usd IS NULL
                                    THEN 1 ELSE 0 END),0)
                    AS invalid_known_requests
           FROM provider_requests"""
    ).fetchone())
    if local_provider.pop("invalid_known_requests"):
        raise ValueError("Continuation state has a provider cost missing without an unknown marker")
    has_continuation_runs = connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='continuation_runs'"
    ).fetchone()[0]
    if has_continuation_runs:
        linked = dict(connection.execute(
            """SELECT COUNT(*) AS runs,
                      COALESCE(SUM(prior_active_vm_cost_usd),0) AS active_vm_cost_usd,
                      COALESCE(SUM(prior_blob_network_cost_usd),0) AS blob_network_cost_usd,
                      COALESCE(SUM(prior_provider_known_cost_usd),0) AS provider_known_cost_usd,
                      COALESCE(SUM(prior_provider_unknown_requests),0) AS provider_unknown_requests,
                      COALESCE(SUM(prior_provider_unconfirmed_estimate_usd),0)
                        AS provider_unconfirmed_estimate_usd,
                      COALESCE(SUM(prior_provider_unknown_without_estimate),0)
                        AS provider_unknown_without_estimate
               FROM continuation_runs"""
        ).fetchone())
    else:
        linked = {
            "runs": 0,
            "active_vm_cost_usd": 0,
            "blob_network_cost_usd": 0,
            "provider_known_cost_usd": 0,
            "provider_unknown_requests": 0,
            "provider_unconfirmed_estimate_usd": 0,
            "provider_unknown_without_estimate": 0,
        }
    return {"local_provider": local_provider, "linked_runs": linked}


def _recovered_continuation_cost(
    local_provider: dict,
    linked_runs: dict,
    local_active_vm_costs: list[float],
    retrieval: dict,
    ledger: dict,
) -> tuple[dict, dict]:
    for name in (
        "requests", "unknown_requests", "unknown_requests_without_input_estimate",
    ):
        if type(local_provider.get(name)) is not int or local_provider[name] < 0:
            raise ValueError("Continuation provider count is invalid")
    for name in ("known_cost_usd", "unconfirmed_input_cost_estimate_usd"):
        if not _measured_seconds(local_provider.get(name)):
            raise ValueError("Continuation provider cost is invalid")
    for name in (
        "active_vm_cost_usd", "blob_network_cost_usd", "provider_known_cost_usd",
        "provider_unconfirmed_estimate_usd",
    ):
        if not _measured_seconds(linked_runs.get(name)):
            raise ValueError("Linked continuation cost is invalid")
    for name in ("runs", "provider_unknown_requests", "provider_unknown_without_estimate"):
        if type(linked_runs.get(name)) is not int or linked_runs[name] < 0:
            raise ValueError("Linked continuation count is invalid")
    if any(not _measured_seconds(value) for value in local_active_vm_costs):
        raise ValueError("Continuation attempt VM cost is missing; it cannot be replaced with zero")
    local_blob = blob_operation_cost(
        retrieval["items"],
        ledger["cost"]["blob_write_per_10000_operations_usd"],
        ledger["cost"]["blob_read_per_10000_operations_usd"],
        ledger["cost"]["same_region_network_per_gb_usd"],
    )
    if local_blob["calculated_cost_usd"] is None:
        raise ValueError("Continuation Blob or network cost is not fully determined")
    provider_known = (
        local_provider["known_cost_usd"] + linked_runs["provider_known_cost_usd"]
    )
    provider_unknown = (
        local_provider["unknown_requests"] + linked_runs["provider_unknown_requests"]
    )
    provider_estimate = (
        local_provider["unconfirmed_input_cost_estimate_usd"]
        + linked_runs["provider_unconfirmed_estimate_usd"]
    )
    provider_unknown_without_estimate = (
        local_provider["unknown_requests_without_input_estimate"]
        + linked_runs["provider_unknown_without_estimate"]
    )
    active_vm = sum(local_active_vm_costs) + linked_runs["active_vm_cost_usd"]
    blob_network = local_blob["calculated_cost_usd"] + linked_runs["blob_network_cost_usd"]
    values = {
        "prior_active_vm_cost_usd": active_vm,
        "prior_blob_network_cost_usd": blob_network,
        "prior_provider_known_cost_usd": provider_known,
        "prior_provider_unknown_requests": provider_unknown,
        "prior_provider_unconfirmed_estimate_usd": provider_estimate,
        "prior_provider_unknown_without_estimate": provider_unknown_without_estimate,
    }
    record = {
        "kind": "read_only_cost_recalculation_from_state_attempts_and_verified_blob_spool",
        "local_provider_request_count": local_provider["requests"],
        "linked_prior_run_count": linked_runs["runs"],
        "local_attempts_with_vm_cost": len(local_active_vm_costs),
        "local_blob_item_count": len(retrieval["items"]),
        "local_blob_and_network_cost": local_blob,
        **values,
    }
    return values, record


def _embedded_continuation(inputs: Path, execution: dict) -> dict | None:
    claimed = execution.get("continuation_sha256")
    if claimed is None:
        return None
    continuation = json.loads(_continuation_file(inputs, "continuation.json").read_bytes())
    continuation_payload = {
        key: value for key, value in continuation.items() if key != "continuation_sha256"
    }
    valid = (
        not re.fullmatch(r"[0-9a-f]{64}", claimed)
        or continuation.get("continuation_sha256") != claimed
        or digest(canonical_json(continuation_payload)) != claimed
        or not isinstance(continuation.get("records"), list)
        or len(continuation["records"]) != continuation.get("linked_completed_attempts")
    )
    legacy_budget_hash = continuation.get("provider_budget_record_sha256")
    if legacy_budget_hash is not None:
        provider_budget = json.loads(
            _continuation_file(inputs, "provider-budget-continuation.json").read_bytes()
        )
        provider_payload = {
            key: value for key, value in provider_budget.items() if key != "record_sha256"
        }
        valid = valid or (
            execution.get("provider_budget_record_sha256") != legacy_budget_hash
            or provider_budget.get("record_sha256") != legacy_budget_hash
            or digest(canonical_json(provider_payload)) != legacy_budget_hash
        )
    elif execution.get("provider_budget_record_sha256") is not None:
        valid = True
    if valid:
        raise ValueError("Embedded screening continuation record differs")
    return continuation


def _carried_continuation_records(
    connection: sqlite3.Connection,
    embedded: dict | None,
) -> list[dict]:
    has_table = connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='continuation_links'"
    ).fetchone()[0]
    if not has_table:
        if embedded is not None:
            raise ValueError("Embedded continuation lacks linked state tables")
        return []
    rows = connection.execute(
        """SELECT cl.*,tr.state AS trial_state,tr.quality_result,tr.failure_category,
                  tr.verifier_test_ids,tr.finished_at,tr.evidence_sha256 AS trial_evidence_sha256,
                  tr.plan_index
           FROM continuation_links cl JOIN trials tr ON tr.trial_id=cl.current_trial_id
           ORDER BY tr.plan_index"""
    ).fetchall()
    if embedded is None:
        if rows:
            raise ValueError("Linked continuation state lacks its embedded record")
        return []
    records = embedded["records"]
    if len(rows) != len(records):
        raise ValueError("Embedded continuation count differs from linked state")
    indexed = {(record["task_id"], record["repetition"]): record for record in records}
    if len(indexed) != len(records):
        raise ValueError("Embedded continuation repeats a task and repetition")
    checked = []
    for row_value in rows:
        row = dict(row_value)
        record = indexed.get((row["task_id"], row["repetition"]))
        if record is None or json.loads(row["record_json"]) != record:
            raise ValueError("Embedded continuation record differs from linked state")
        expected_state = (
            "linked_quality_result" if record["result"] in QUALITY_RESULTS
            else "linked_technical_exclusion"
        )
        estimate_column = (
            "provider_unconfirmed_estimate_usd"
            if "provider_unconfirmed_estimate_usd" in row
            else "provider_reserved_unknown_usd"
        )
        fields = {
            "prior_trial_id": "prior_trial_id",
            "prior_attempt_id": "prior_attempt_id",
            "result": "result",
            "evidence_disposition": "evidence_disposition",
            "evidence_sha256": "evidence_sha256",
            "provider_request_count": "provider_request_count",
            "provider_known_cost_usd": "provider_known_cost_usd",
            "provider_unknown_requests": "provider_unknown_requests",
            estimate_column: estimate_column,
            "active_vm_cost_usd": "active_vm_cost_usd",
            "blob_network_cost_usd": "blob_network_cost_usd",
            "direct_cost_usd": "direct_cost_usd",
        }
        if any(row[column] != record[name] for column, name in fields.items()):
            raise ValueError("Embedded continuation values differ from linked state")
        expected_quality = record["result"] if record["result"] in QUALITY_RESULTS else None
        expected_failure = None if record["result"] == "pass" else record["result"]
        if (
            row["trial_state"] != expected_state
            or row["quality_result"] != expected_quality
            or row["failure_category"] != expected_failure
            or row["trial_evidence_sha256"] != record["evidence_sha256"]
            or row["plan_index"] != record["plan_index"]
        ):
            raise ValueError("Embedded continuation trial state differs")
        checked.append(record)
    return checked


def _legacy_policy_transition(prior: dict, current: dict) -> dict:
    if prior["schema_version"] == current["schema_version"] == 2:
        if prior != current:
            raise ValueError("Continuation changes the fixed no-harness-limit screening ledger")
        return {"max_completion_tokens": None, "max_calls_per_trial": None}
    if prior["schema_version"] != 1 or current["schema_version"] != 2:
        raise ValueError("Unsupported screening ledger transition")
    for name in (
        "mode", "output_dir", "raw_retrieval", "benchmark", "measurement", "queue",
        "retrieval", "prices", "screening", "replay", "cost", "approval",
    ):
        if prior[name] != current[name]:
            raise ValueError(f"Continuation changes the fixed screening {name}")
    prior_model = {key: value for key, value in prior["model"].items() if key != "max_completion_tokens"}
    if prior_model != current["model"] or prior["model"]["max_completion_tokens"] != 2048:
        raise ValueError("Continuation changes model settings beyond removing the output-token cap")
    removed_runner_limits = {
        "max_turns": 60,
        "agent_timeout_seconds": 900,
        "verifier_timeout_seconds": 900,
        "setup_timeout_seconds": 600,
        "trial_timeout_seconds": 2400,
    }
    prior_runner = {key: value for key, value in prior["runner"].items() if key not in removed_runner_limits}
    if prior_runner != current["runner"] or any(
        prior["runner"].get(key) != value for key, value in removed_runner_limits.items()
    ):
        raise ValueError("Continuation changes runner settings beyond removing harness limits")
    limits = prior["limits"]
    if (
        limits.get("max_calls_per_trial") != 60
        or limits.get("request_timeout_seconds") != 300
        or limits.get("max_request_bytes") != 8_000_000
        or limits.get("max_attempts_per_call") != current["limits"]["transient_http_attempts"]
        or limits.get("max_retry_wait_seconds") != 120
        or limits.get("protocol_token_allowance") != 4096
        or type(limits.get("api_cost_usd")) not in (int, float)
        or limits["api_cost_usd"] < 0
        or type(limits.get("max_wall_seconds")) is not int
        or limits["max_wall_seconds"] < 1
        or not isinstance(limits.get("deadline_utc"), str)
    ):
        raise ValueError("Legacy screening limits differ from the reviewed removal boundary")
    return {
        "max_completion_tokens": prior["model"]["max_completion_tokens"],
        "max_calls_per_trial": limits["max_calls_per_trial"],
    }


def _no_limit_reuse_decision(record: dict, legacy_limits: dict) -> dict:
    reasons = []
    requests = record.get("provider_requests") or []
    logical_calls = {
        request.get("logical_request") for request in requests
        if type(request.get("logical_request")) is int
    }
    call_boundary = legacy_limits.get("max_calls_per_trial")
    output_boundary = legacy_limits.get("max_completion_tokens")
    if call_boundary is not None and logical_calls and max(logical_calls) >= call_boundary:
        reasons.append("legacy_provider_call_boundary_reached")
    if output_boundary is not None and any(
        request.get("finish_reason") == "length"
        or (
            isinstance(request.get("tokens"), dict)
            and type(request["tokens"].get("output_tokens")) is int
            and request["tokens"]["output_tokens"] >= output_boundary
        )
        for request in requests
    ):
        reasons.append("legacy_output_token_boundary_reached")
    result = record.get("result")
    if result in {"timeout", "setup_error", "image_error", "network_error"}:
        reasons.append("legacy_time_limit_may_have_changed_the_technical_result")
    if record.get("provider_call_limit_reached") is True:
        reasons.append("legacy_provider_call_stop_recorded")
    explicit_rejection = (
        result == "provider_error"
        and (
            (record.get("technical_exclusion_basis") or {}).get("kind")
                == "explicit_provider_rejection_before_first_verifier"
            or any(
                type(request.get("http_status")) is int
                and 400 <= request["http_status"] < 500
                and request["http_status"] not in {408, 409, 429}
                for request in requests
            )
        )
    )
    reusable_result = result in QUALITY_RESULTS or explicit_rejection
    if not reusable_result:
        reasons.append("result_is_not_an_unaffected_quality_result_or_explicit_provider_rejection")
    return {
        "reusable": not reasons,
        "reasons": sorted(set(reasons)),
        "logical_provider_calls": len(logical_calls),
        "legacy_limit_impact_observed_or_possible": bool(reasons),
    }


def _normalize_continuation_record(record: dict) -> dict:
    normalized = json.loads(json.dumps(record))
    if "provider_unconfirmed_estimate_usd" not in normalized:
        normalized["provider_unconfirmed_estimate_usd"] = normalized.pop(
            "provider_reserved_unknown_usd", None
        )
    return normalized


def _prepare_continuation(
    directory: Path,
    setup: dict,
    source_commit: str,
    manifest: dict,
    prior_directory: Path,
    prior_spool_directory: Path | None = None,
) -> dict:
    if prior_directory.is_symlink():
        raise ValueError("Continuation source directory cannot be a symlink")
    prior_directory = prior_directory.resolve(strict=True)
    if not prior_directory.name.startswith("screening-"):
        raise ValueError("Continuation source is not a screening run")
    prior_inputs = prior_directory / "inputs"
    if prior_inputs.is_symlink() or not prior_inputs.is_dir():
        raise ValueError("Continuation source inputs are missing or unsafe")
    prior_provenance = verify_snapshot(prior_inputs)
    prior_commit = prior_provenance["source_commit"]
    if prior_commit == source_commit:
        raise ValueError("Use ordinary resume when the screening source commit has not changed")
    git(ROOT, "merge-base", "--is-ancestor", prior_commit, source_commit)
    prior_ledger = load_screening_ledger(_continuation_file(prior_inputs, "ledger.toml"))
    legacy_limits = _legacy_policy_transition(prior_ledger, setup["ledger"])
    prior_inventory_bytes = _continuation_file(prior_inputs, "inventory.json").read_bytes()
    if prior_inventory_bytes != setup["inventory_path"].read_bytes():
        raise ValueError("Continuation changes the fixed task inventory")
    prior_inventory = verify_inventory(json.loads(prior_inventory_bytes))
    prior_manifest = verify_screening_manifest(
        json.loads(_continuation_file(prior_inputs, "screening-manifest.json").read_bytes()),
        prior_inventory,
    )
    if prior_manifest["run_id"] != prior_directory.name or prior_manifest["source_commit"] != prior_commit:
        raise ValueError("Continuation source manifest lineage differs")
    prior_execution = json.loads(_continuation_file(prior_inputs, "execution.json").read_bytes())
    expected_execution = {
        "run_id": prior_manifest["run_id"],
        "source_commit": prior_commit,
        "ledger_sha256": prior_provenance["ledger_sha256"],
        "inventory_sha256": prior_inventory["inventory_sha256"],
        "manifest_sha256": prior_manifest["manifest_sha256"],
    }
    if any(prior_execution.get(name) != value for name, value in expected_execution.items()):
        raise ValueError("Continuation source execution record differs")
    if (prior_execution.get("execution_scope") or {}).get("included_in_formal_screening_denominator") is not True:
        raise ValueError("A diagnostic run cannot seed the formal screening denominator")

    prior_artifacts = json.loads(_continuation_file(prior_inputs, "task-artifacts.json").read_bytes())
    expected_artifacts = {
        task["task_id"]: _task_artifact(task, prior_ledger, prior_commit)
        for task in prior_inventory["tasks"] if task["exclusion"] is None
    }
    if prior_artifacts != expected_artifacts:
        raise ValueError("Continuation source task artifacts differ")
    prior_summary_path = _continuation_file(prior_directory, "summary.json")
    prior_retrieval_path = _continuation_file(prior_directory, "retrieval.json")
    prior_state_path = _continuation_file(prior_directory, "state.sqlite3")
    prior_summary = json.loads(prior_summary_path.read_bytes())
    persisted_retrieval = json.loads(prior_retrieval_path.read_bytes())
    persisted_retrieval_ids = {
        item.get("item_id") for item in persisted_retrieval.get("items", [])
    }
    prior_retrieval = persisted_retrieval
    retrieval_recovery = None
    if prior_spool_directory is not None:
        spool_retrieval, spool_recovery = _verified_prior_blob_spool(
            prior_spool_directory,
            setup,
            run_id=prior_manifest["run_id"],
            source_commit=prior_commit,
            ledger_sha256=prior_provenance["ledger_sha256"],
        )
        prior_retrieval, merge_recovery = _merge_prior_retrieval(
            persisted_retrieval, spool_retrieval
        )
        retrieval_recovery = {
            "kind": "persisted_retrieval_plus_read_only_verified_blob_spool",
            "persisted_retrieval_sha256": digest(prior_retrieval_path.read_bytes()),
            "effective_retrieval_sha256": digest(canonical_json(prior_retrieval)),
            **spool_recovery,
            **merge_recovery,
        }
    if prior_retrieval.get("upload_state") != "uploaded":
        raise ValueError("Continuation source Blob evidence is not fully uploaded")
    embedded = _embedded_continuation(prior_inputs, prior_execution)
    if embedded is not None:
        if (
            (prior_summary.get("continuation") or {}).get("continuation_sha256")
                != embedded["continuation_sha256"]
            or embedded.get("current_run_id") != prior_manifest["run_id"]
            or embedded.get("current_source_commit") != prior_commit
        ):
            raise ValueError("Continuation source summary or lineage differs")
        input_records = [
            item for item in prior_retrieval.get("items", [])
            if item.get("item_id") == "run-inputs"
        ]
        if (
            len(input_records) != 1
            or input_records[0].get("upload_state") != "uploaded"
            or input_records[0].get("remote_verified_at") is None
            or (input_records[0].get("metadata") or {}).get("continuation_sha256")
                != embedded["continuation_sha256"]
        ):
            raise ValueError("Embedded continuation inputs lack matching remote evidence")
    retrieval_by_attempt = {
        item["item_id"]: item for item in prior_retrieval.get("items", [])
        if re.fullmatch(r"[0-9a-f]{64}", item.get("item_id", ""))
    }
    batch_by_attempt = {}
    for batch in prior_summary.get("batch_evidence_verifications") or []:
        for attempt in batch.get("attempts") or []:
            attempt_id = attempt.get("attempt_id")
            if attempt_id in batch_by_attempt:
                raise ValueError("Continuation source repeats an attempt in batch evidence")
            batch_by_attempt[attempt_id] = attempt

    connection = sqlite3.connect(f"file:{prior_state_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        carried_records = _carried_continuation_records(connection, embedded)
        rows = connection.execute(
            """SELECT tr.trial_id,tr.task_id,tr.repetition,tr.condition_name,tr.plan_index,
                      tr.state AS trial_state,tr.quality_result,tr.failure_category,
                      tr.verifier_test_ids,tr.finished_at,tr.evidence_sha256 AS trial_evidence_sha256,
                      a.attempt_id,a.attempt_number,a.state AS attempt_state,a.provider_dispatched,
                      a.artifact_manifest_hash,a.container_instance_id,a.workspace_instance_id,
                      a.error_category,a.evidence_sha256 AS attempt_evidence_sha256
               FROM attempts a JOIN trials tr USING(trial_id)
               WHERE a.state='completed'
               ORDER BY tr.plan_index,a.attempt_number"""
        ).fetchall()
        unfinished = connection.execute(
            "SELECT COUNT(*) FROM attempts WHERE state!='completed'"
        ).fetchone()[0]
        prior_cost_state = _continuation_state_costs(connection)
    finally:
        connection.close()
    if unfinished:
        raise ValueError("Continuation source has unresolved attempts; do not rewrite their state")
    if len(rows) + len(carried_records) != prior_summary.get("state", {}).get("completed_attempts"):
        raise ValueError("Continuation completed-attempt count differs from its summary")

    tasks = {task["task_id"]: task for task in prior_inventory["tasks"]}
    records = []
    not_reused = []
    local_active_vm_costs = []
    for carried in carried_records:
        normalized = _normalize_continuation_record(carried)
        decision = _no_limit_reuse_decision(normalized, legacy_limits)
        normalized["no_limit_policy_reuse"] = decision
        if decision["reusable"]:
            records.append(normalized)
        else:
            not_reused.append({
                "prior_trial_id": normalized["prior_trial_id"],
                "prior_attempt_id": normalized["prior_attempt_id"],
                "task_id": normalized["task_id"],
                "repetition": normalized["repetition"],
                "result": normalized["result"],
                "evidence_sha256": normalized["evidence_sha256"],
                "reasons": decision["reasons"],
            })
    for row in rows:
        row = dict(row)
        attempt_id = row["attempt_id"]
        attempt_path = _continuation_file(
            prior_directory, f"attempts/{attempt_id}/attempt.json"
        )
        attempt = json.loads(attempt_path.read_bytes())
        if any(attempt.get(name) != row[name] for name in ("attempt_id", "trial_id", "task_id", "repetition")):
            raise ValueError("Continuation attempt identity differs from its state database")
        if row["attempt_number"] != attempt.get("attempt_number") or row["attempt_state"] != "completed":
            raise ValueError("Continuation attempt state differs")
        if row["attempt_evidence_sha256"] != row["trial_evidence_sha256"]:
            raise ValueError("Continuation trial and attempt evidence hashes differ")
        if attempt.get("artifact_manifest_sha256") != row["artifact_manifest_hash"]:
            raise ValueError("Continuation attempt artifact hash differs from its state database")
        if attempt["artifact_manifest_sha256"] != prior_artifacts[row["task_id"]]["artifact_manifest_sha256"]:
            raise ValueError("Continuation attempt artifact differs from the frozen task artifact")
        local_active_vm_costs.append(
            (attempt.get("active_vm_cost") or {}).get("calculated_cost_usd")
        )
        retrieval_record = retrieval_by_attempt.get(attempt_id)
        if (
            retrieval_record is None
            or retrieval_record.get("upload_state") != "uploaded"
            or retrieval_record.get("remote_verified_at") is None
            or (retrieval_record.get("metadata") or {}).get("source_tree_sha256")
                != row["attempt_evidence_sha256"]
        ):
            raise ValueError("Continuation attempt lacks matching remotely verified Blob evidence")
        batch_record = batch_by_attempt.get(attempt_id)
        if batch_record is not None and (
            batch_record.get("result") != (attempt.get("classification") or {}).get("result")
            or batch_record.get("remote_hash_verified") is not True
        ):
            raise ValueError("Continuation batch evidence differs from the attempt record")
        persisted_individual_verification = (
            batch_record is None and attempt_id in persisted_retrieval_ids
        )
        prior_verification_source = (
            "recorded_batch_evidence_verification"
            if batch_record is not None else
            "persisted_retrieval_and_read_only_individual_evidence_verification"
            if persisted_individual_verification else
            "missing_recorded_batch_evidence_verification"
        )

        events = read_events(_continuation_file(
            prior_directory, f"attempts/{attempt_id}/transport/events.jsonl"
        ))
        enriched_provider = provider_cost(events, attempt_id)
        recorded_provider = attempt["classification"]["provider_cost"]
        for name in ("http_attempts", "known_attempts", "unknown_attempts", "known_cost_usd", "calculated_cost_usd"):
            if recorded_provider.get(name) != enriched_provider.get(name):
                raise ValueError("Continuation provider accounting differs from recorded evidence")
        job = prior_directory / "attempts" / attempt_id / "jobs" / attempt_id
        replay, _replay_error = _attempt_replay(job)
        classification = json.loads(json.dumps(attempt["classification"]))
        classification["provider_cost"] = enriched_provider
        replay_checks = classification.get("replay_checks") or {}
        if replay is not None:
            replay_checks["capture_status"] = replay.get("status")
            replay_checks["capture_phase"] = replay.get("capture_phase")
        classification["replay_checks"] = replay_checks
        explicit_rejection = (
            classification["result"] == "provider_error"
            and _explicit_provider_rejection(
                enriched_provider, classification.get("request_failure"), replay
            )
        )
        terminal_session_exit = _terminal_session_exit_evidence(
            job, replay, classification.get("request_failure")
        )
        pre_verifier_exclusion_reason = (
            "explicit_provider_rejection_before_first_verifier"
            if explicit_rejection else
            "terminal_session_ended_before_first_verifier"
            if classification["result"] == "replay_mismatch"
            and terminal_session_exit is not None else None
        )
        classification["evidence_timing_status"] = _evidence_timing_status(
            classification["evidence_timing"],
            pre_verifier_exclusion_reason=pre_verifier_exclusion_reason,
        )
        classification["technical_exclusion_basis"] = {
            "kind": pre_verifier_exclusion_reason,
            "original_error_recorded": (
                classification.get("request_failure") is not None
                or terminal_session_exit is not None
            ),
            "provider_accounting_recorded": (
                len(enriched_provider["requests"]) == enriched_provider["http_attempts"]
            ),
            "terminal_session_exit": terminal_session_exit,
        }
        checked_record = {**attempt, "classification": classification}
        checked = _completed_attempt_evidence(checked_record, retrieval_record, setup["ledger"])
        blob = blob_operation_cost(
            [retrieval_record],
            setup["ledger"]["cost"]["blob_write_per_10000_operations_usd"],
            setup["ledger"]["cost"]["blob_read_per_10000_operations_usd"],
            setup["ledger"]["cost"]["same_region_network_per_gb_usd"],
        )
        vm_cost = attempt["active_vm_cost"]["calculated_cost_usd"]
        direct = combined_direct_cost(enriched_provider, attempt["active_vm_cost"], blob)
        candidate = {
            "prior_trial_id": row["trial_id"],
            "prior_attempt_id": attempt_id,
            "task_id": row["task_id"],
            "repetition": row["repetition"],
            "plan_index": row["plan_index"],
            "result": classification["result"],
            "evidence_disposition": checked["evidence_disposition"],
            "evidence_sha256": row["attempt_evidence_sha256"],
            "artifact_manifest_sha256": attempt["artifact_manifest_sha256"],
            "image_platform_digest": tasks[row["task_id"]]["image"]["platform_digest"],
            "verifier_test_ids": json.loads(row["verifier_test_ids"] or "[]"),
            "finished_at": row["finished_at"],
            "provider_request_count": enriched_provider["http_attempts"],
            "provider_known_cost_usd": enriched_provider["known_cost_usd"],
            "provider_unknown_requests": enriched_provider["unknown_attempts"],
            "provider_unconfirmed_estimate_usd": enriched_provider[
                "unconfirmed_cost_estimate_usd"
            ],
            "provider_requests": enriched_provider["requests"],
            "active_vm_cost_usd": vm_cost,
            "blob_network_cost_usd": blob["calculated_cost_usd"],
            "direct_cost_usd": direct["calculated_cost_usd"],
            "blob_payload_sha256": retrieval_record["payload"]["sha256"],
            "blob_remote_verified_at": retrieval_record["remote_verified_at"],
            "technical_exclusion_basis": classification["technical_exclusion_basis"],
            "prior_verification_source": prior_verification_source,
            "provider_call_limit_reached": attempt["classification"].get(
                "provider_call_limit_reached", False
            ),
        }
        decision = _no_limit_reuse_decision(candidate, legacy_limits)
        candidate["no_limit_policy_reuse"] = decision
        verification_reusable = batch_record is not None or persisted_individual_verification
        if checked["evidence_complete"] and decision["reusable"] and verification_reusable:
            records.append(candidate)
        else:
            reasons = list(decision["reasons"])
            if not checked["evidence_complete"]:
                reasons.append("prior_evidence_incomplete")
            if not verification_reusable:
                reasons.append("prior_batch_evidence_missing_outside_persisted_retrieval")
            not_reused.append({
                "prior_trial_id": candidate["prior_trial_id"],
                "prior_attempt_id": candidate["prior_attempt_id"],
                "task_id": candidate["task_id"],
                "repetition": candidate["repetition"],
                "result": candidate["result"],
                "evidence_sha256": candidate["evidence_sha256"],
                "reasons": sorted(set(reasons)),
            })

    changed_source_files = git(
        ROOT, "diff", "--name-only", prior_commit, source_commit, "--", "src", "schemas",
        "requirements", "fixtures/llmlingua2", "run.py", "accounting.py", "pyproject.toml", "uv.lock",
    ).decode().splitlines()
    source_diff = git(
        ROOT, "diff", "--binary", prior_commit, source_commit, "--", "src", "schemas",
        "requirements", "fixtures/llmlingua2", "run.py", "accounting.py", "pyproject.toml", "uv.lock",
    )
    recovered_costs, cost_recovery = _recovered_continuation_cost(
        prior_cost_state["local_provider"],
        prior_cost_state["linked_runs"],
        local_active_vm_costs,
        prior_retrieval,
        setup["ledger"],
    )
    lineage = {
        "kind": "screening_read_only_continuation",
        "prior_run_id": prior_manifest["run_id"],
        "prior_source_commit": prior_commit,
        "prior_ledger_sha256": prior_provenance["ledger_sha256"],
        "prior_inventory_sha256": prior_inventory["inventory_sha256"],
        "prior_manifest_sha256": prior_manifest["manifest_sha256"],
        "prior_summary_sha256": digest(prior_summary_path.read_bytes()),
        "prior_retrieval_sha256": digest(prior_retrieval_path.read_bytes()),
        "prior_effective_retrieval_sha256": digest(canonical_json(prior_retrieval)),
        "prior_state_sha256": digest(prior_state_path.read_bytes()),
        "current_run_id": manifest["run_id"],
        "current_source_commit": source_commit,
        "current_manifest_sha256": manifest["manifest_sha256"],
        "source_diff_sha256": digest(source_diff),
        **recovered_costs,
        "retrieval_recovery": retrieval_recovery,
        "cost_recovery": cost_recovery,
        "changed_source_files": changed_source_files,
        "prior_completed_attempts": len(rows) + len(carried_records),
        "linked_completed_attempts": len(records),
        "linked_quality_results": sum(record["result"] in QUALITY_RESULTS for record in records),
        "linked_technical_exclusions": sum(record["result"] not in QUALITY_RESULTS for record in records),
        "not_reused_attempts": not_reused,
        "link_basis": (
            "only_complete_results_without_observed_or_possible_binding_from_the_removed_"
            "call_output_or_time_limits_are_linked_once"
        ),
        "records": records,
    }
    payload = {**lineage, "continuation_sha256": digest(canonical_json(lineage))}
    save_json(directory / "inputs" / "continuation.json", payload)
    execution_path = directory / "inputs" / "execution.json"
    execution = json.loads(execution_path.read_bytes())
    execution["continuation_sha256"] = payload["continuation_sha256"]
    execution["prior_run_id"] = prior_manifest["run_id"]
    atomic_json(execution_path, execution)
    return payload


def _resume_inputs(directory: Path, setup: dict, source_commit: str) -> tuple[dict, dict, ScreeningState, object, dict]:
    if directory.is_symlink():
        raise ValueError("Screening resume directory cannot be a symlink")
    directory = directory.resolve(strict=True)
    runs_root = (ROOT / setup["ledger"]["output_dir"]).resolve()
    if directory.parent != runs_root or not directory.name.startswith("screening-"):
        raise ValueError("Screening resume directory is outside the fixed run root")
    inputs = directory / "inputs"
    provenance = verify_snapshot(inputs)
    if provenance != setup["provenance"]:
        raise ValueError("Screening resume source snapshot differs from the current preflight")
    if (inputs / "inventory.json").read_bytes() != setup["inventory_path"].read_bytes():
        raise ValueError("Screening resume inventory bytes differ")
    manifest = verify_screening_manifest(
        json.loads((inputs / "screening-manifest.json").read_bytes()), setup["inventory"]
    )
    if manifest["source_commit"] != source_commit or manifest["run_id"] != directory.name:
        raise ValueError("Screening resume manifest lineage differs")
    execution = json.loads((inputs / "execution.json").read_bytes())
    expected_execution = {
        "run_id": manifest["run_id"],
        "source_commit": source_commit,
        "ledger_sha256": setup["provenance"]["ledger_sha256"],
        "inventory_sha256": setup["inventory"]["inventory_sha256"],
        "manifest_sha256": manifest["manifest_sha256"],
    }
    if any(execution.get(name) != value for name, value in expected_execution.items()):
        raise ValueError("Screening resume execution record differs")
    artifacts = json.loads((inputs / "task-artifacts.json").read_bytes())
    expected_artifacts = {
        task["task_id"]: _task_artifact(task, setup["ledger"], source_commit)
        for task in setup["inventory"]["tasks"]
        if task["exclusion"] is None
    }
    if artifacts != expected_artifacts:
        raise ValueError("Screening resume immutable task artifacts differ")
    state = ScreeningState(directory / "state.sqlite3")
    spool = None
    try:
        state.initialize(manifest)
        continuation_sha256 = execution.get("continuation_sha256")
        if continuation_sha256 is not None:
            continuation = _embedded_continuation(inputs, execution)
            if (
                continuation is None
                or state.summary()["linked_completed_attempts"]
                    != continuation.get("linked_completed_attempts")
            ):
                raise ValueError("Screening continuation record or linked state differs")
        elif state.summary()["linked_completed_attempts"]:
            raise ValueError("Screening state has continuation links without an execution record")
        state.pause_interrupted()
        paused = state.paused_attempts()
        if paused:
            save_json(directory / "paused-attempts.json", {
                "kind": "screening_paused_attempts_requiring_static_resolution",
                "run_id": manifest["run_id"],
                "attempts": paused,
            })
            raise ValueError(
                "Interrupted attempts require static evidence resolution before resume; no trial was rerun"
            )
        spool = resume_blob_spool(
            setup["retrieval"], setup["retrieval"]["spool_root"] / manifest["run_id"], accepting=True
        )
        if (
            spool.run_id != manifest["run_id"]
            or spool.source_commit != source_commit
            or spool.ledger_sha256 != setup["provenance"]["ledger_sha256"]
            or spool.condition != "none"
        ):
            raise ValueError("Screening resume Blob spool lineage differs")
        uploaded = spool.wait_for_upload(
            ["run-inputs"], setup["ledger"]["retrieval"]["upload_timeout_seconds"]
        )
        if uploaded["status"] != "uploaded":
            raise RuntimeError("Screening inputs are not remotely verified; provider execution remains blocked")
        summary_path = directory / "summary.json"
        summary = json.loads(summary_path.read_bytes()) if summary_path.is_file() else {
            "schema_version": 1,
            "kind": "terminal_bench_screening",
            "run_id": manifest["run_id"],
            "source_commit": source_commit,
            "ledger_sha256": setup["provenance"]["ledger_sha256"],
            "inventory_sha256": manifest["inventory_sha256"],
            "manifest_sha256": manifest["manifest_sha256"],
            "started_at": execution["started_at"],
            "classification_policy": POLICY,
        }
        for name, value in expected_execution.items():
            if summary.get(name) != value:
                raise ValueError(f"Screening resume summary differs: {name}")
        if continuation_sha256 is not None and (
            summary.get("continuation") or {}
        ).get("continuation_sha256") != continuation_sha256:
            raise ValueError("Screening resume continuation summary differs")
        previous_status = summary.get("status")
        previous_reason = (summary.get("stop_reason") or {}).get("reason")
        previous_error = (summary.get("error") or {}).get("type")
        if previous_status == "stopped" and previous_reason not in {
            "KeyboardInterrupt", "NativeSupervisorInterrupted"
        } and previous_error not in {"KeyboardInterrupt", "SystemExit"}:
            raise ValueError("A non-interruption stop requires a new reviewed revision, not automatic resume")
        summary.setdefault("sessions", []).append({
            "kind": "resume",
            "started_at": now(),
            "previous_status": previous_status,
            "completed_attempts_before_resume": state.summary()["completed_attempts"],
        })
        summary["status"] = "running"
        summary["completed_attempts"] = state.summary()["completed_attempts"]
        summary.pop("error", None)
        summary.pop("stop_reason", None)
        return manifest, artifacts, state, spool, summary
    except BaseException:
        if spool is not None:
            spool.finish(0)
        state.close()
        raise


def execute_screening(
    ledger_path: Path,
    source_commit: str,
    *,
    resume_directory: Path | None = None,
    diagnostic_task_id: str | None = None,
    continuation_directory: Path | None = None,
    continuation_spool_directory: Path | None = None,
    condition: str = "none",
    compressor_configuration: dict | None = None,
    compressor_ledger_bytes: bytes | None = None,
    preliminary_manifest: dict | None = None,
) -> Path:
    setup = screening_preflight(ledger_path, source_commit)
    ledger = setup["ledger"]
    if sum(value is not None for value in (
        resume_directory, diagnostic_task_id, continuation_directory
    )) > 1:
        raise ValueError("Resume, diagnostic, and read-only continuation modes are mutually exclusive")
    if continuation_spool_directory is not None and continuation_directory is None:
        raise ValueError("A continuation Blob spool requires --continue-from")
    preliminary = preliminary_manifest is not None
    if preliminary:
        if (
            diagnostic_task_id is None
            or resume_directory is not None
            or continuation_directory is not None
            or compressor_configuration is None
            or compressor_ledger_bytes is None
        ):
            raise ValueError("A preliminary comparison needs one fresh diagnostic task and compressor inputs")
        if preliminary_manifest.get("selected_task", {}).get("task_id") != diagnostic_task_id:
            raise ValueError("Preliminary comparison task differs from its immutable manifest")
        if condition not in preliminary_manifest.get("condition_order", []):
            raise ValueError("Preliminary comparison condition differs from its immutable manifest")
    elif (
        condition != "none"
        or compressor_configuration is not None
        or compressor_ledger_bytes is not None
    ):
        raise ValueError("Compression conditions are allowed only in the separate preliminary comparison")
    eligible_task_ids = {
        task["task_id"] for task in setup["inventory"]["tasks"] if task["exclusion"] is None
    }
    if diagnostic_task_id is not None and diagnostic_task_id not in eligible_task_ids:
        raise ValueError("The diagnostic task is absent from the fixed eligible inventory")
    execution_scope = (
        {
            "kind": "single_task_preliminary_comparison_condition",
            "comparison_id": preliminary_manifest["comparison_id"],
            "comparison_manifest_sha256": preliminary_manifest["manifest_sha256"],
            "task_id": diagnostic_task_id,
            "condition": condition,
            "logical_trials": 1,
            "maximum_attempts": 2,
            "preparation_retry_only": True,
            "included_in_formal_screening_denominator": False,
        }
        if preliminary
        else
        {
            "kind": "single_task_full_path_diagnostic",
            "task_id": diagnostic_task_id,
            "maximum_attempts": 1,
            "included_in_formal_screening_denominator": False,
        }
        if diagnostic_task_id is not None
        else {
            "kind": "formal_terminal_bench_screening_continuation",
            "included_in_formal_screening_denominator": True,
            "prior_evidence_linked_read_only": True,
        }
        if continuation_directory is not None
        else {
            "kind": "formal_terminal_bench_screening",
            "included_in_formal_screening_denominator": True,
        }
    )
    if resume_directory is None:
        prefix = (
            f"preliminary-{condition}"
            if preliminary else
            "screening-diagnostic"
            if diagnostic_task_id is not None else
            "screening"
        )
        run_id = f"{prefix}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{secrets.token_hex(4)}"
        directory = ROOT / ledger["output_dir"] / run_id
        directory.mkdir(parents=True, exist_ok=False)
        os.chmod(directory, 0o700)
        manifest, artifacts = _prepare_inputs(
            directory,
            setup,
            source_commit,
            run_id,
            execution_scope=execution_scope,
            condition=condition,
            intervention=(
                None if not preliminary else {
                    "kind": "candidate_log_compression",
                    "condition": condition,
                    "target": compressor_configuration["target"],
                    "compressor": {
                        **compressor_configuration,
                        "name": condition,
                    },
                    "compressor_ledger_sha256": digest(compressor_ledger_bytes),
                    "comparison_manifest_sha256": preliminary_manifest["manifest_sha256"],
                }
            ),
            preliminary_manifest=preliminary_manifest,
            compressor_ledger_bytes=compressor_ledger_bytes,
        )
        state = ScreeningState(directory / "state.sqlite3")
        state.initialize(manifest)
        continuation = None
        if continuation_directory is not None:
            continuation = _prepare_continuation(
                directory,
                setup,
                source_commit,
                manifest,
                continuation_directory,
                continuation_spool_directory,
            )
            state.link_continuation(continuation, continuation["records"])
        spool = make_blob_spool(
            setup["retrieval"],
            run_id,
            source_commit,
            setup["provenance"]["ledger_sha256"],
            condition,
        )
        inputs_retrieval = spool.stage_directory(
            directory / "inputs", "run-inputs", kind=(
                "terminal_bench_preliminary_comparison_inputs"
                if preliminary else "terminal_bench_screening_inputs"
            ),
            metadata={
                "manifest_sha256": manifest["manifest_sha256"],
                "inventory_sha256": manifest["inventory_sha256"],
                "condition": condition,
                "continuation_sha256": (
                    None if continuation is None else continuation["continuation_sha256"]
                ),
            },
        )
        if spool.wait_for_upload(
            ["run-inputs"], ledger["retrieval"]["upload_timeout_seconds"]
        )["status"] != "uploaded":
            spool.finish(ledger["retrieval"]["final_flush_seconds"])
            state.close()
            raise RuntimeError("Screening inputs were not verified in Blob before provider execution")
        summary = {
            "schema_version": 1,
            "kind": (
                "terminal_bench_preliminary_comparison"
                if preliminary else "terminal_bench_screening"
            ),
            "run_id": run_id,
            "source_commit": source_commit,
            "ledger_sha256": setup["provenance"]["ledger_sha256"],
            "inventory_sha256": manifest["inventory_sha256"],
            "manifest_sha256": manifest["manifest_sha256"],
            "condition": condition,
            "status": "running",
            "started_at": now(),
            "completed_attempts": state.summary()["completed_attempts"],
            "retrieval_inputs": inputs_retrieval,
            "classification_policy": POLICY,
            "execution_scope": execution_scope,
            "sessions": [{"kind": "initial", "started_at": now()}],
        }
        if continuation is not None:
            summary["continuation"] = {
                key: continuation[key] for key in (
                    "continuation_sha256", "prior_run_id", "prior_source_commit",
                    "prior_ledger_sha256", "prior_inventory_sha256", "prior_manifest_sha256",
                    "prior_summary_sha256", "prior_retrieval_sha256",
                    "prior_effective_retrieval_sha256", "prior_state_sha256",
                    "source_diff_sha256", "prior_active_vm_cost_usd",
                    "prior_blob_network_cost_usd", "linked_completed_attempts", "linked_quality_results",
                    "linked_technical_exclusions",
                    "prior_provider_known_cost_usd", "prior_provider_unknown_requests",
                    "prior_provider_unconfirmed_estimate_usd",
                    "prior_provider_unknown_without_estimate", "retrieval_recovery",
                    "cost_recovery", "link_basis",
                )
            }
    else:
        directory = resume_directory
        manifest, artifacts, state, spool, summary = _resume_inputs(directory, setup, source_commit)
        directory = directory.resolve(strict=True)
        run_id = manifest["run_id"]
    deployment = digest((setup["sender"].endpoint + "/" + ledger["model"]["name"]).encode())
    queue = DeploymentQueue(setup["queue_path"], deployment, *setup["queue_limits"])
    compressor = (
        make_compressor(
            {**compressor_configuration, "name": condition},
            directory / "compressor",
        )
        if preliminary else
        NoOpCompressor({"options": {}}, directory / "compressor")
    )
    summary["compressor"] = compressor.metadata
    session = f"session-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{secrets.token_hex(3)}"
    transport = directory / "transport" / session
    recorder = LiveRecorder(
        transport, ledger, source_commit, compressor, setup["encoder"], queue, setup["sender"],
        condition=condition,
        evidence_kind=summary["kind"],
        request_error_scope="trial",
    )
    key = secrets.token_urlsafe(32)
    server = start_live_proxy(recorder, key)
    batch_number = 0
    claimed_attempts = 0
    evidence_stop = None
    incomplete_attempts = []
    vm_cost_tracker = _ActiveVmCostTracker(ledger["cost"]["vm_hourly_usd"])
    try:
        def next_attempt():
            nonlocal claimed_attempts
            recorder.check()
            if diagnostic_task_id is not None and claimed_attempts >= 1:
                if not preliminary or claimed_attempts >= 2:
                    return None
                retry_pending = state.connection.execute(
                    "SELECT COUNT(*) FROM trials WHERE task_id=? AND state='retry_pending'",
                    (diagnostic_task_id,),
                ).fetchone()[0]
                if retry_pending != 1:
                    return None
            claimed = state.claim(1, task_id=diagnostic_task_id)
            if not claimed:
                return None
            attempt = _new_attempt_context(claimed[0], directory, artifacts)
            attempt["evidence_kind"] = summary["kind"]
            state.mark_attempt_runtime(
                attempt["attempt_id"],
                process_id=None,
                artifact_manifest_hash=attempt["artifact_manifest_hash"],
                container_instance_id=attempt["container_instance_id"],
                workspace_instance_id=attempt["workspace_instance_id"],
            )
            recorder.register_trial(
                attempt["attempt_id"], attempt["task_id"], attempt["repetition"]
            )
            claimed_attempts += 1
            return attempt

        def run_attempt(attempt):
            return _run_attempt(
                attempt, ledger, recorder, server, key, state.path, vm_cost_tracker
            )

        def complete_attempt(item):
            nonlocal batch_number, evidence_stop
            batch_number += 1
            classification = _classify_attempt(
                item["attempt"], item["process"], recorder, transport
            )
            finalized = _finalize_attempt(
                item,
                classification,
                vm_cost_tracker.allocation_for(item["attempt"]["attempt_id"]),
                state,
                spool,
                transport,
                complete_state=False,
            )
            attempt_verification = _verify_finalized_attempt(
                finalized,
                spool,
                ledger["retrieval"]["upload_timeout_seconds"],
                ledger,
            )
            summary.setdefault("attempt_evidence_verifications", []).append(
                attempt_verification
            )
            summary["latest_attempt_evidence_verification"] = attempt_verification
            if not attempt_verification["completed_evidence_recording_allowed"]:
                incomplete_attempts.append({
                    "completion_number": batch_number,
                    "attempt_id": item["attempt"]["attempt_id"],
                    "task_id": item["attempt"]["task_id"],
                    "verification": attempt_verification,
                })
                summary["state"] = state.summary()
                summary["last_progress_at"] = now()
                atomic_json(directory / "summary.json", summary)
                print(json.dumps({
                    "run_id": run_id,
                    "completed_attempts": summary["completed_attempts"],
                    "state": summary["state"],
                    "attempt_evidence": attempt_verification,
                    "replacement_scheduled": False,
                }, ensure_ascii=False), flush=True)
                return False, False
            _complete_finalized_attempt(finalized, state)
            summary["completed_attempts"] += 1
            summary["state"] = state.summary()
            summary["last_progress_at"] = now()
            checkpoint = _stage_checkpoint(directory, state, summary, spool)
            batch_verification = _verify_completed_batch(
                [finalized],
                checkpoint,
                spool,
                ledger["retrieval"]["upload_timeout_seconds"],
                batch_number,
                ledger,
            )
            summary.setdefault("batch_evidence_verifications", []).append(batch_verification)
            summary["latest_batch_evidence_verification"] = batch_verification
            atomic_json(directory / "summary.json", summary)
            print(json.dumps({
                "run_id": run_id,
                "completed_attempts": summary["completed_attempts"],
                "state": summary["state"],
                "known_provider_cost_usd": summary["state"]["provider"]["known_cost_usd"],
                "batch_evidence": batch_verification,
            }, ensure_ascii=False), flush=True)
            if not batch_verification["additional_claims_allowed"]:
                if evidence_stop is None:
                    evidence_stop = {
                        "reason": "post_commit_evidence_verification_incomplete",
                        "details": {
                            "completion_number": batch_number,
                            "attempt_id": item["attempt"]["attempt_id"],
                            "additional_claims": 0,
                            "running_attempts_preserved": True,
                        },
                    }
                return False, True
            return True, False

        _run_completion_driven(
            ledger["runner"]["concurrency"], next_attempt, run_attempt, complete_attempt
        )
        if incomplete_attempts:
            state.pause_interrupted()
            if evidence_stop is None:
                evidence_stop = {
                    "reason": "completed_attempt_evidence_incomplete",
                    "details": {
                        "attempts": incomplete_attempts,
                        "quality_results_recorded": 0,
                        "additional_claims_for_incomplete_slots": 0,
                    },
                }
            else:
                evidence_stop["details"]["incomplete_attempts"] = incomplete_attempts
        if evidence_stop is not None:
            summary["status"] = "stopped"
            summary["stop_reason"] = evidence_stop
        if summary.get("status") == "running":
            summary["status"] = "complete"
    except BaseException as error:
        summary["status"] = "stopped"
        summary["error"] = {"type": type(error).__name__, "message": str(error)}
        recorder.stop(type(error).__name__, {"message": str(error)})
        state.pause_interrupted()
    finally:
        server.shutdown()
        server.server_close()
        try:
            compressor.close()
        except BaseException as compressor_error:
            summary["compressor_close_error"] = {
                "type": type(compressor_error).__name__,
                "message": str(compressor_error),
            }
            summary["status"] = "stopped"
        queue.close()
        summary["state"] = state.summary()
        if recorder.failure is not None:
            summary["stop_reason"] = recorder.failure
        summary["finished_at"] = now()
        try:
            _stage_checkpoint(directory, state, summary, spool)
        except (OSError, ValueError, RuntimeError) as checkpoint_error:
            summary["checkpoint_error"] = {
                "type": type(checkpoint_error).__name__, "message": str(checkpoint_error),
            }
            if summary["status"] == "complete":
                summary["status"] = "retrieval_pending"
        retrieval = spool.finish(ledger["retrieval"]["final_flush_seconds"])
        summary["cost"] = _run_cost_summary(directory, state, retrieval, ledger)
        save_json(directory / "retrieval.json", retrieval)
        summary["retrieval"] = retrieval
        if retrieval["upload_state"] != "uploaded" and summary["status"] == "complete":
            summary["status"] = "retrieval_pending"
        atomic_json(directory / "summary.json", summary)
        state.close()
    return directory


def _reported_task_id(reported: str, expected: set[str]) -> str:
    if not isinstance(reported, str) or not reported:
        raise ValueError("Harbor install preflight omitted the task name")
    matches = [task_id for task_id in expected if reported == task_id or reported.endswith("/" + task_id)]
    if len(matches) != 1:
        raise ValueError(f"Harbor install preflight task name is not an unambiguous inventory task: {reported}")
    return matches[0]


def run_install_preflight(ledger_path: Path, source_commit: str, output: Path) -> dict:
    setup = screening_preflight(ledger_path, source_commit)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    run_id = "screening-install-preflight"
    _manifest, _artifacts = _prepare_inputs(output, setup, source_commit, run_id)
    task_paths = [output / "inputs" / "tasks" / task["task_id"] for task in setup["inventory"]["tasks"] if task["exclusion"] is None]
    config = screening_harbor_config(
        setup["ledger"], task_paths, output / "jobs", "install-preflight",
        "http://127.0.0.1:1/no-provider/v1", preserve_for_replay=False, install_only=True,
    )
    save_json(output / "harbor-config.json", config)
    command = harbor_command("run", "--config", str(output / "harbor-config.json"))
    started = time.monotonic()
    process = subprocess.run(
        command,
        cwd=ROOT,
        env=runtime_environment("preflight-no-provider"),
        stdout=(output / "harbor.log").open("wb"),
        stderr=subprocess.STDOUT,
    )
    expected = {task["task_id"] for task in setup["inventory"]["tasks"] if task["exclusion"] is None}
    results = {}
    for path in sorted((output / "jobs" / "install-preflight").glob("*/result.json")):
        result = json.loads(path.read_bytes())
        reported_task_name = result["task_name"]
        task_id = _reported_task_id(reported_task_name, expected)
        if task_id in results:
            raise ValueError(f"Harbor install preflight recorded a duplicate task: {task_id}")
        results[task_id] = {
            "result_path": path.relative_to(output).as_posix(),
            "reported_task_name": reported_task_name,
            "exception_type": (result.get("exception_info") or {}).get("exception_type"),
            "environment_setup": result.get("environment_setup"),
            "agent_setup": result.get("agent_setup"),
        }
    failures = sorted(task for task in expected if task not in results or results[task]["exception_type"])
    record = {
        "schema_version": 1,
        "kind": "terminal_bench_screening_install_preflight",
        "model_calls": 0,
        "source_commit": source_commit,
        "inventory_sha256": setup["inventory"]["inventory_sha256"],
        "tasks_expected": len(expected),
        "tasks_recorded": len(results),
        "failures": failures,
        "return_code": process.returncode,
        "elapsed_seconds": time.monotonic() - started,
        "results": results,
    }
    save_json(output / "preflight.json", record)
    return record


def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--source-commit", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--install-preflight", type=Path)
    action.add_argument("--execute", action="store_true")
    action.add_argument("--resume", type=Path)
    action.add_argument("--diagnose-task")
    action.add_argument("--continue-from", type=Path)
    parser.add_argument("--continue-blob-spool", type=Path)
    args = parser.parse_args(arguments)
    try:
        if args.check:
            checked = screening_preflight(args.ledger.resolve(), args.source_commit)
            print(json.dumps({
                "status": "screening_preflight_passed",
                "model_calls": 0,
                "source_commit": checked["provenance"]["source_commit"],
                "inventory_sha256": checked["inventory"]["inventory_sha256"],
                "tasks": len(checked["inventory"]["tasks"]),
            }))
            return 0
        if args.install_preflight is not None:
            record = run_install_preflight(args.ledger.resolve(), args.source_commit, args.install_preflight)
            print(json.dumps({
                "status": "passed" if not record["failures"] and record["return_code"] == 0 else "failed",
                "model_calls": 0,
                "tasks": record["tasks_recorded"],
                "failures": record["failures"],
            }))
            return 0 if not record["failures"] and record["return_code"] == 0 else 3
        directory = execute_screening(
            args.ledger.resolve(), args.source_commit,
            resume_directory=None if args.resume is None else args.resume.resolve(),
            diagnostic_task_id=args.diagnose_task,
            continuation_directory=(
                None if args.continue_from is None else args.continue_from.resolve()
            ),
            continuation_spool_directory=(
                None if args.continue_blob_spool is None else args.continue_blob_spool.resolve()
            ),
        )
        summary = json.loads((directory / "summary.json").read_bytes())
        print(json.dumps({"directory": str(directory), "status": summary["status"]}))
        return 0 if summary["status"] == "complete" else 3
    except (ValueError, OSError, subprocess.SubprocessError, importlib.metadata.PackageNotFoundError) as error:
        print(f"Screening preflight or execution failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
