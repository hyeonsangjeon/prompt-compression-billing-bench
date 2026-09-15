"""Run the hash-bound Terminal-Bench 2.1 screening plan."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
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
import time

from accounting import now
from .blob_retrieval import atomic_json, make_blob_spool, resume_blob_spool, retrieval_settings
from .compressors import NoOpCompressor
from .contracts import safe_child, save_json
from .live_observations import POLICY
from .live_transport import DeploymentQueue, FoundrySender, LiveRecorder, ManagedIdentity, start_live_proxy
from .measurement import load_encoder
from .native_judge import collect_native_outcome
from .native_run import prepare_task, runtime_environment, runtime_versions, supervise
from .protection import digest
from .provenance import ROOT, capture, git, verify_snapshot
from .replay_environment import replay_bundle_manifest
from .screening_contract import load_screening_ledger, require_operational_screening
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
        "verifier": {"override_timeout_sec": runner["verifier_timeout_seconds"], "disable": False},
        "tasks": [{"path": str(path)} for path in task_paths],
        "agents": [{
            "import_path": runner["agent_import_path"],
            "model_name": "openai/" + model["name"],
            "override_timeout_sec": runner["agent_timeout_seconds"],
            "override_setup_timeout_sec": runner["setup_timeout_seconds"],
            "n_concurrent": concurrency,
            "kwargs": {
                "api_base": api_base,
                "max_turns": runner["max_turns"],
                "enable_summarize": False,
                "use_responses_api": False,
                "store_all_messages": True,
                "temperature": model["temperature"],
                "reasoning_effort": model["reasoning_effort"],
                "llm_kwargs": {"max_completion_tokens": model["max_completion_tokens"], "num_retries": 0},
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
    deadline = require_operational_screening(load_screening_ledger(ledger_path))
    ledger = load_screening_ledger(ledger_path)
    provenance, snapshots = capture(ledger_path, source_commit)
    inventory_path, inventory, task_files = _load_inventory(ledger)
    versions = runtime_versions()
    from harbor.models.job.config import JobConfig

    first_task = Path("/screening/task")
    JobConfig.model_validate(screening_harbor_config(
        ledger, [first_task], Path("/screening/jobs"), "screening-check",
        "http://127.0.0.1:1/check/v1", preserve_for_replay=True,
    ))
    encoder = load_encoder(ledger["measurement"])
    retrieval = retrieval_settings(ledger, ROOT)
    endpoint = os.environ.get(ledger["model"]["endpoint_env"], "")
    sender = FoundrySender(
        endpoint, ledger["limits"]["request_timeout_seconds"], ManagedIdentity(), deadline=deadline
    )
    queue_path = _queue_path(ledger)
    return {
        "ledger": ledger,
        "deadline": deadline,
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
    }


def _task_artifact(task: dict, ledger: dict, source_commit: str) -> dict:
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
    return {**payload, "artifact_manifest_sha256": digest(canonical_json(payload))}


def _prepare_inputs(
    directory: Path,
    setup: dict,
    source_commit: str,
    run_id: str,
    *,
    execution_scope: dict | None = None,
) -> tuple[dict, dict]:
    inputs = directory / "inputs"
    inputs.mkdir(parents=True, exist_ok=False)
    for name, content in setup["snapshots"].items():
        path = safe_child(inputs, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    save_json(inputs / "provenance.json", setup["provenance"])
    (inputs / "inventory.json").write_bytes(setup["inventory_path"].read_bytes())
    manifest = make_screening_manifest(setup["inventory"], source_commit, run_id)
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
        artifacts[task_id] = _task_artifact(task, setup["ledger"], source_commit)
    save_json(inputs / "task-sources.json", sources)
    save_json(inputs / "task-artifacts.json", artifacts)
    execution = {
        "schema_version": 1,
        "kind": "terminal_bench_screening_execution",
        "run_id": run_id,
        "source_commit": source_commit,
        "ledger_sha256": setup["provenance"]["ledger_sha256"],
        "inventory_sha256": setup["inventory"]["inventory_sha256"],
        "manifest_sha256": manifest["manifest_sha256"],
        "runtime_versions": setup["runtime_versions"],
        "python": sys.version,
        "concurrency": setup["ledger"]["runner"]["concurrency"],
        "deployment_limits": {
            "rpm": setup["ledger"]["queue"]["rpm"],
            "tpm": setup["ledger"]["queue"]["tpm"],
            "checked_at_utc": setup["ledger"]["queue"]["limits_checked_at_utc"],
            "source_reference": setup["ledger"]["queue"]["limits_source_reference"],
        },
        "verifier_replay": "same_preserved_state_one_additional_verifier_execution_no_model_call",
        "execution_scope": execution_scope or {
            "kind": "formal_terminal_bench_screening",
            "included_in_formal_screening_denominator": True,
        },
        "started_at": now(),
    }
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
        and provider.get("unknown_attempts_without_reservation") == 0
    )


def _evidence_timing_status(timing: dict, *, provider_rejected_before_verifier: bool) -> dict:
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
        elif provider_rejected_before_verifier and name in unexecuted:
            result[name] = {
                "status": "not_applicable",
                "reason": "explicit_provider_rejection_before_first_verifier",
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
    call_limit_reached = (
        request_failure is not None
        and request_failure.get("reason") == "TrialCallLimitReached"
    )
    outcome = collect_native_outcome(job, process=process, transport_failure=None)
    completed_process = not process["timed_out"] and not process["stopped_by_guard"] and process["returncode"] == 0
    metrics = collect_trial_metrics(job, transport, attempt_id, process_complete=completed_process)
    replay, replay_error = _attempt_replay(job)
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
    elif request_failure is not None and not call_limit_reached:
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
            provider_rejected_before_verifier=provider_rejected_before_verifier,
        ),
        "technical_exclusion_basis": {
            "kind": (
                "explicit_provider_rejection_before_first_verifier"
                if provider_rejected_before_verifier else None
            ),
            "original_error_recorded": request_failure is not None,
            "provider_cost_or_reservation_complete": (
                provider.get("unknown_attempts_without_reservation") == 0
            ),
        },
        "verifier_test_ids": test_ids,
        "request_failure": request_failure,
        "provider_call_limit_reached": call_limit_reached,
    }


def _run_attempt(
    attempt: dict,
    ledger: dict,
    recorder: LiveRecorder,
    server,
    key: str,
    state_path: Path,
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
    command = [str(Path(sys.executable).with_name("harbor")), "run", "--config", str(attempt_directory / "harbor-config.json")]

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
    started_monotonic = time.monotonic()
    process = {
        "returncode": None,
        "timed_out": False,
        "stopped_by_guard": False,
        "started_at": started_at,
    }
    try:
        process = supervise(
            command,
            attempt_directory / "harbor.log",
            recorder,
            ledger["runner"]["trial_timeout_seconds"],
            runtime_environment(key),
            on_start=started,
        )
    except BaseException as error:
        process.update(
            stopped_by_guard=recorder.stopped.is_set(),
            error_type=type(error).__name__,
            error_message=str(error),
            finished_at=now(),
            elapsed_seconds=time.monotonic() - started_monotonic,
        )
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
            budget_reservation_usd=request["budget_reservation_usd"],
        )


def _finalize_attempt(
    completed: dict,
    classification: dict,
    vm_record: dict,
    state: ScreeningState,
    spool,
    transport: Path,
) -> dict:
    attempt = completed["attempt"]
    attempt_directory = attempt["attempt_directory"]
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
        "kind": "terminal_bench_screening_attempt",
        "trial_id": attempt["trial_id"],
        "attempt_id": attempt["attempt_id"],
        "attempt_number": attempt["attempt_number"],
        "task_id": attempt["task_id"],
        "repetition": attempt["repetition"],
        "condition": "none",
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
        kind="terminal_bench_screening_attempt",
        metadata={
            "trial_id": attempt["trial_id"],
            "attempt_id": attempt["attempt_id"],
            "task_id": attempt["task_id"],
            "repetition": attempt["repetition"],
            "result": classification["result"],
        },
    )
    state.complete_attempt(
        attempt["attempt_id"],
        classification["result"],
        provider_dispatched=classification["provider_dispatched"],
        evidence_sha256=staged["metadata"]["source_tree_sha256"],
        cost_usd=direct["calculated_cost_usd"],
        verifier_test_ids=classification["verifier_test_ids"],
    )
    return {"record": record, "retrieval": staged}


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


def _run_cost_summary(directory: Path, state: ScreeningState, retrieval: dict, ledger: dict) -> dict:
    provider_state = state.provider_cost_state()
    provider_budget = state.provider_budget_state()
    continuation_cost = state.continuation_cost_state()
    provider = {
        "kind": "provider_usage_times_fixed_rates_not_invoice_reconciliation",
        "currency": "USD",
        "requests": provider_state["requests"],
        "known_cost_usd": provider_state["known_cost_usd"],
        "unknown_attempts": provider_state["unknown_requests"],
        "conservative_unknown_reservation_usd": provider_state[
            "conservative_unknown_reservation_usd"
        ],
        "unknown_attempts_without_reservation": provider_state[
            "unknown_requests_without_reservation"
        ],
        "budget_accounted_cost_usd": provider_state["budget_accounted_cost_usd"],
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
        "provider_budget": {
            "kind": "screening_wide_provider_cost_and_conservative_unknown_reservations",
            "currency": "USD",
            **provider_budget,
            "current_run_ledger_ceiling_usd": ledger["limits"]["api_cost_usd"],
            "linked_formal_attempt_cost_is_not_added_twice": True,
        },
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
    explicit_rejection = (
        (classification.get("technical_exclusion_basis") or {}).get("kind")
        == "explicit_provider_rejection_before_first_verifier"
    )
    required_timings = [
        name for name in ("task_process_wall_seconds", "state_save_wall_seconds")
        if not _measured_seconds(timing.get(name))
    ] if explicit_rejection else list(full_replay_timings)
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
    provider_cost_complete = (
        provider.get("calculated_cost_usd") is not None
        or (
            provider.get("unknown_attempts", 0) > 0
            and provider.get("unknown_attempts_without_reservation") == 0
            and provider.get("conservative_unknown_reservation_usd", 0) > 0
        )
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
    cost_complete = provider_cost_complete and active_vm_cost_complete and blob_cost_complete
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
    result = classification["result"]
    quality_result = result in QUALITY_RESULTS
    completed_evidence = (
        remote_hash_verified
        and cost_complete
        and ((strict_replay_complete and not required_timings) or explicit_rejection_complete)
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
        "remote_hash_verified": remote_hash_verified,
        "timing": {**timing, "upload_wall_seconds": upload_seconds},
        "missing_timing_fields": required_timings,
        "not_applicable_timing_fields": not_applicable_timings,
        "cost_complete": cost_complete,
        "cost": {
            "provider_calculated_cost_usd": provider.get("calculated_cost_usd"),
            "provider_known_cost_usd": provider.get("known_cost_usd"),
            "provider_conservative_unknown_reservation_usd": provider.get(
                "conservative_unknown_reservation_usd"
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


def _continuation_file(directory: Path, relative: str) -> Path:
    path = directory / relative
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(directory):
        raise ValueError(f"Continuation evidence file is missing or unsafe: {relative}")
    return path


def _verified_provider_budget_record(
    path: Path,
    ledger: dict,
    prior_run_id: str,
    linked_provider: dict,
) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Provider budget continuation record is missing or unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("Provider budget continuation record is not valid JSON") from error
    fields = {
        "schema_version", "kind", "currency", "continuation_source_run_id",
        "provider_ceiling_usd", "prior_known_cost_usd", "prior_unknown_requests",
        "prior_reserved_unknown_usd", "remaining_provider_budget_usd",
        "diagnostic_costs_included", "source_reference", "record_sha256",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("Provider budget continuation record fields differ")
    if (
        value["schema_version"] != 1
        or value["kind"] != "screening_provider_budget_continuation"
        or value["currency"] != "USD"
        or value["continuation_source_run_id"] != prior_run_id
        or value["diagnostic_costs_included"] is not True
        or not isinstance(value["source_reference"], str)
        or not value["source_reference"].strip()
    ):
        raise ValueError("Provider budget continuation record identity or scope differs")
    payload = {key: item for key, item in value.items() if key != "record_sha256"}
    if (
        not re.fullmatch(r"[0-9a-f]{64}", value["record_sha256"])
        or digest(canonical_json(payload)) != value["record_sha256"]
    ):
        raise ValueError("Provider budget continuation record hash differs")
    for name in (
        "provider_ceiling_usd", "prior_known_cost_usd",
        "prior_reserved_unknown_usd", "remaining_provider_budget_usd",
    ):
        number = value[name]
        if (
            type(number) not in (int, float)
            or isinstance(number, bool)
            or not math.isfinite(number)
            or number < 0
        ):
            raise ValueError(f"Provider budget continuation record has an invalid {name}")
    if type(value["prior_unknown_requests"]) is not int or value["prior_unknown_requests"] < 0:
        raise ValueError("Provider budget continuation record has an invalid unknown request count")
    if not math.isclose(
        value["provider_ceiling_usd"],
        value["prior_known_cost_usd"]
        + value["prior_reserved_unknown_usd"]
        + value["remaining_provider_budget_usd"],
        rel_tol=0,
        abs_tol=1e-9,
    ):
        raise ValueError("Provider budget continuation arithmetic differs")
    if not math.isclose(
        value["remaining_provider_budget_usd"],
        ledger["limits"]["api_cost_usd"],
        rel_tol=0,
        abs_tol=1e-9,
    ):
        raise ValueError("Current ledger does not use the recorded remaining provider budget")
    if (
        value["prior_known_cost_usd"] + 1e-12 < linked_provider["known_cost_usd"]
        or value["prior_unknown_requests"] < linked_provider["unknown_requests"]
        or value["prior_reserved_unknown_usd"] + 1e-12
            < linked_provider["conservative_unknown_reservation_usd"]
    ):
        raise ValueError("Provider budget record omits linked formal screening cost")
    return value


def _prepare_continuation(
    directory: Path,
    setup: dict,
    source_commit: str,
    manifest: dict,
    prior_directory: Path,
    provider_budget_record_path: Path,
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
    current_ledger = deepcopy(setup["ledger"])
    prior_remaining_budget = prior_ledger["limits"]["api_cost_usd"]
    current_remaining_budget = current_ledger["limits"]["api_cost_usd"]
    prior_ledger["limits"]["api_cost_usd"] = current_remaining_budget
    if prior_ledger != current_ledger:
        raise ValueError("Continuation changes the execution ledger beyond its remaining provider budget")
    if current_remaining_budget > prior_remaining_budget:
        raise ValueError("Continuation cannot increase the prior run provider budget")
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
        task["task_id"]: _task_artifact(task, setup["ledger"], prior_commit)
        for task in prior_inventory["tasks"] if task["exclusion"] is None
    }
    if prior_artifacts != expected_artifacts:
        raise ValueError("Continuation source task artifacts differ")
    prior_summary_path = _continuation_file(prior_directory, "summary.json")
    prior_retrieval_path = _continuation_file(prior_directory, "retrieval.json")
    prior_state_path = _continuation_file(prior_directory, "state.sqlite3")
    prior_summary = json.loads(prior_summary_path.read_bytes())
    prior_retrieval = json.loads(prior_retrieval_path.read_bytes())
    if prior_retrieval.get("upload_state") != "uploaded":
        raise ValueError("Continuation source Blob evidence is not fully uploaded")
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
    finally:
        connection.close()
    if unfinished:
        raise ValueError("Continuation source has unresolved attempts; do not rewrite their state")
    if len(rows) != prior_summary.get("state", {}).get("completed_attempts"):
        raise ValueError("Continuation completed-attempt count differs from its summary")

    tasks = {task["task_id"]: task for task in prior_inventory["tasks"]}
    records = []
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
        if (
            batch_record is None
            or batch_record.get("result") != (attempt.get("classification") or {}).get("result")
            or batch_record.get("remote_hash_verified") is not True
        ):
            raise ValueError("Continuation batch evidence differs from the attempt record")

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
        classification["evidence_timing_status"] = _evidence_timing_status(
            classification["evidence_timing"],
            provider_rejected_before_verifier=explicit_rejection,
        )
        classification["technical_exclusion_basis"] = {
            "kind": "explicit_provider_rejection_before_first_verifier" if explicit_rejection else None,
            "original_error_recorded": classification.get("request_failure") is not None,
            "provider_cost_or_reservation_complete": (
                enriched_provider["unknown_attempts_without_reservation"] == 0
            ),
        }
        checked_record = {**attempt, "classification": classification}
        checked = _completed_attempt_evidence(checked_record, retrieval_record, setup["ledger"])
        if not checked["evidence_complete"]:
            raise ValueError(
                f"Continuation attempt evidence remains incomplete: {row['task_id']} "
                f"({','.join(checked['missing_timing_fields']) or 'non-timing evidence'})"
            )
        if enriched_provider["http_attempts"] >= setup["ledger"]["limits"]["max_calls_per_trial"]:
            raise ValueError("A prior attempt reached the changed provider-call boundary and needs separate review")
        blob = blob_operation_cost(
            [retrieval_record],
            setup["ledger"]["cost"]["blob_write_per_10000_operations_usd"],
            setup["ledger"]["cost"]["blob_read_per_10000_operations_usd"],
            setup["ledger"]["cost"]["same_region_network_per_gb_usd"],
        )
        vm_cost = attempt["active_vm_cost"]["calculated_cost_usd"]
        direct = combined_direct_cost(enriched_provider, attempt["active_vm_cost"], blob)
        records.append({
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
            "provider_reserved_unknown_usd": enriched_provider[
                "conservative_unknown_reservation_usd"
            ],
            "provider_requests": enriched_provider["requests"],
            "active_vm_cost_usd": vm_cost,
            "blob_network_cost_usd": blob["calculated_cost_usd"],
            "direct_cost_usd": direct["calculated_cost_usd"],
            "blob_payload_sha256": retrieval_record["payload"]["sha256"],
            "blob_remote_verified_at": retrieval_record["remote_verified_at"],
            "source_change_boundary_reached": False,
        })

    changed_source_files = git(
        ROOT, "diff", "--name-only", prior_commit, source_commit, "--", "src", "schemas",
        "requirements", "fixtures/llmlingua2", "run.py", "accounting.py", "pyproject.toml", "uv.lock",
    ).decode().splitlines()
    source_diff = git(
        ROOT, "diff", "--binary", prior_commit, source_commit, "--", "src", "schemas",
        "requirements", "fixtures/llmlingua2", "run.py", "accounting.py", "pyproject.toml", "uv.lock",
    )
    prior_active_vm_cost = (prior_summary.get("cost") or {}).get("active_vm", {}).get(
        "calculated_cost_usd"
    )
    prior_blob_network_cost = (prior_summary.get("cost") or {}).get("blob_and_network", {}).get(
        "calculated_cost_usd"
    )
    if not _measured_seconds(prior_active_vm_cost) or not _measured_seconds(prior_blob_network_cost):
        raise ValueError("Continuation source run-level VM or Blob cost is incomplete")
    linked_provider = {
        "known_cost_usd": sum(record["provider_known_cost_usd"] for record in records),
        "unknown_requests": sum(record["provider_unknown_requests"] for record in records),
        "conservative_unknown_reservation_usd": sum(
            record["provider_reserved_unknown_usd"] for record in records
        ),
    }
    provider_budget = _verified_provider_budget_record(
        provider_budget_record_path, setup["ledger"], prior_manifest["run_id"], linked_provider
    )
    save_json(directory / "inputs" / "provider-budget-continuation.json", provider_budget)
    lineage = {
        "kind": "screening_read_only_continuation",
        "prior_run_id": prior_manifest["run_id"],
        "prior_source_commit": prior_commit,
        "prior_ledger_sha256": prior_provenance["ledger_sha256"],
        "prior_inventory_sha256": prior_inventory["inventory_sha256"],
        "prior_manifest_sha256": prior_manifest["manifest_sha256"],
        "prior_summary_sha256": digest(prior_summary_path.read_bytes()),
        "prior_retrieval_sha256": digest(prior_retrieval_path.read_bytes()),
        "prior_state_sha256": digest(prior_state_path.read_bytes()),
        "current_run_id": manifest["run_id"],
        "current_source_commit": source_commit,
        "current_manifest_sha256": manifest["manifest_sha256"],
        "source_diff_sha256": digest(source_diff),
        "prior_active_vm_cost_usd": prior_active_vm_cost,
        "prior_blob_network_cost_usd": prior_blob_network_cost,
        "provider_ceiling_usd": provider_budget["provider_ceiling_usd"],
        "prior_provider_known_cost_usd": provider_budget["prior_known_cost_usd"],
        "prior_provider_unknown_requests": provider_budget["prior_unknown_requests"],
        "prior_provider_reserved_unknown_usd": provider_budget[
            "prior_reserved_unknown_usd"
        ],
        "remaining_provider_budget_usd": provider_budget["remaining_provider_budget_usd"],
        "provider_budget_record_sha256": provider_budget["record_sha256"],
        "changed_source_files": changed_source_files,
        "linked_completed_attempts": len(records),
        "linked_quality_results": sum(record["result"] in QUALITY_RESULTS for record in records),
        "linked_technical_exclusions": sum(record["result"] not in QUALITY_RESULTS for record in records),
        "link_basis": (
            "all_prior_completed_attempts_have_complete_preserved_evidence_and_did_not_reach_"
            "the_changed_provider_call_boundary"
        ),
        "records": records,
    }
    payload = {**lineage, "continuation_sha256": digest(canonical_json(lineage))}
    save_json(directory / "inputs" / "continuation.json", payload)
    execution_path = directory / "inputs" / "execution.json"
    execution = json.loads(execution_path.read_bytes())
    execution["continuation_sha256"] = payload["continuation_sha256"]
    execution["prior_run_id"] = prior_manifest["run_id"]
    execution["provider_budget_record_sha256"] = provider_budget["record_sha256"]
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
            continuation = json.loads((inputs / "continuation.json").read_bytes())
            provider_budget = json.loads(
                (inputs / "provider-budget-continuation.json").read_bytes()
            )
            continuation_payload = {
                key: value for key, value in continuation.items() if key != "continuation_sha256"
            }
            if (
                not re.fullmatch(r"[0-9a-f]{64}", continuation_sha256)
                or continuation.get("continuation_sha256") != continuation_sha256
                or digest(canonical_json(continuation_payload)) != continuation_sha256
                or execution.get("provider_budget_record_sha256")
                    != provider_budget.get("record_sha256")
                or digest(canonical_json({
                    key: value for key, value in provider_budget.items() if key != "record_sha256"
                })) != provider_budget.get("record_sha256")
                or continuation.get("provider_budget_record_sha256")
                    != provider_budget.get("record_sha256")
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
        provider = state.provider_cost_state()
        if provider["unknown_requests_without_reservation"]:
            raise ValueError(
                "Provider cost is unknown without a conservative reservation; resume cannot enforce the budget ceiling"
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
    provider_budget_record_path: Path | None = None,
) -> Path:
    setup = screening_preflight(ledger_path, source_commit)
    ledger = setup["ledger"]
    if sum(value is not None for value in (
        resume_directory, diagnostic_task_id, continuation_directory
    )) > 1:
        raise ValueError("Resume, diagnostic, and read-only continuation modes are mutually exclusive")
    if (continuation_directory is None) != (provider_budget_record_path is None):
        raise ValueError("Read-only continuation requires exactly one provider budget record")
    eligible_task_ids = {
        task["task_id"] for task in setup["inventory"]["tasks"] if task["exclusion"] is None
    }
    if diagnostic_task_id is not None and diagnostic_task_id not in eligible_task_ids:
        raise ValueError("The diagnostic task is absent from the fixed eligible inventory")
    execution_scope = (
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
        prefix = "screening-diagnostic" if diagnostic_task_id is not None else "screening"
        run_id = f"{prefix}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{secrets.token_hex(4)}"
        directory = ROOT / ledger["output_dir"] / run_id
        directory.mkdir(parents=True, exist_ok=False)
        os.chmod(directory, 0o700)
        manifest, artifacts = _prepare_inputs(
            directory, setup, source_commit, run_id, execution_scope=execution_scope
        )
        state = ScreeningState(directory / "state.sqlite3")
        state.initialize(manifest)
        continuation = None
        if continuation_directory is not None:
            continuation = _prepare_continuation(
                directory, setup, source_commit, manifest, continuation_directory,
                provider_budget_record_path,
            )
            state.link_continuation(continuation, continuation["records"])
        spool = make_blob_spool(
            setup["retrieval"], run_id, source_commit, setup["provenance"]["ledger_sha256"], "none"
        )
        inputs_retrieval = spool.stage_directory(
            directory / "inputs", "run-inputs", kind="terminal_bench_screening_inputs",
            metadata={
                "manifest_sha256": manifest["manifest_sha256"],
                "inventory_sha256": manifest["inventory_sha256"],
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
            "kind": "terminal_bench_screening",
            "run_id": run_id,
            "source_commit": source_commit,
            "ledger_sha256": setup["provenance"]["ledger_sha256"],
            "inventory_sha256": manifest["inventory_sha256"],
            "manifest_sha256": manifest["manifest_sha256"],
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
                    "prior_summary_sha256", "prior_retrieval_sha256", "prior_state_sha256",
                    "source_diff_sha256", "prior_active_vm_cost_usd",
                    "prior_blob_network_cost_usd", "linked_completed_attempts", "linked_quality_results",
                    "linked_technical_exclusions", "provider_ceiling_usd",
                    "prior_provider_known_cost_usd", "prior_provider_unknown_requests",
                    "prior_provider_reserved_unknown_usd", "remaining_provider_budget_usd",
                    "provider_budget_record_sha256", "link_basis",
                )
            }
    else:
        directory = resume_directory
        manifest, artifacts, state, spool, summary = _resume_inputs(directory, setup, source_commit)
        directory = directory.resolve(strict=True)
        run_id = manifest["run_id"]
    deployment = digest((setup["sender"].endpoint + "/" + ledger["model"]["name"]).encode())
    queue = DeploymentQueue(setup["queue_path"], deployment, ledger["queue"]["rpm"], ledger["queue"]["tpm"])
    compressor = NoOpCompressor({"options": {}}, directory / "compressor")
    session = f"session-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{secrets.token_hex(3)}"
    transport = directory / "transport" / session
    recorder = LiveRecorder(
        transport, ledger, source_commit, compressor, setup["encoder"], queue, setup["sender"],
        condition="none", evidence_kind="terminal_bench_screening", request_error_scope="trial",
    )
    recorder.budget_used_usd = state.local_provider_cost_state()["budget_accounted_cost_usd"]
    setup["sender"].deadline = recorder.deadline
    key = secrets.token_urlsafe(32)
    server = start_live_proxy(recorder, key)
    batch_number = 0
    try:
        while True:
            recorder.check()
            claim_size = 1 if diagnostic_task_id is not None else ledger["runner"]["concurrency"]
            claimed = state.claim(claim_size, task_id=diagnostic_task_id)
            if not claimed:
                break
            batch_number += 1
            contexts = [_new_attempt_context(row, directory, artifacts) for row in claimed]
            for attempt in contexts:
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
            with ThreadPoolExecutor(max_workers=len(contexts), thread_name_prefix="screening-trial") as executor:
                completed = list(executor.map(
                    lambda attempt: _run_attempt(attempt, ledger, recorder, server, key, state.path), contexts
                ))
            vm = allocate_active_vm_cost(_attempt_intervals(completed), ledger["cost"]["vm_hourly_usd"])
            finalized = []
            for item in completed:
                classification = _classify_attempt(item["attempt"], item["process"], recorder, transport)
                finalized.append(_finalize_attempt(
                    item,
                    classification,
                    vm["attempts"][item["attempt"]["attempt_id"]],
                    state,
                    spool,
                    transport,
                ))
                summary["completed_attempts"] += 1
            summary["state"] = state.summary()
            summary["last_progress_at"] = now()
            checkpoint = _stage_checkpoint(directory, state, summary, spool)
            batch_verification = _verify_completed_batch(
                finalized,
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
                "known_provider_cost_usd": recorder.budget_used_usd,
                "batch_evidence": batch_verification,
            }, ensure_ascii=False), flush=True)
            if not batch_verification["additional_claims_allowed"]:
                summary["status"] = "stopped"
                summary["stop_reason"] = {
                    "reason": "batch_evidence_incomplete",
                    "details": {
                        "batch_number": batch_number,
                        "additional_claims": 0,
                    },
                }
                break
            if diagnostic_task_id is not None:
                break
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
    command = [str(Path(sys.executable).with_name("harbor")), "run", "--config", str(output / "harbor-config.json")]
    started = time.monotonic()
    process = subprocess.run(
        command,
        cwd=ROOT,
        env=runtime_environment("preflight-no-provider"),
        stdout=(output / "harbor.log").open("wb"),
        stderr=subprocess.STDOUT,
        timeout=setup["ledger"]["limits"]["max_wall_seconds"],
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
    parser.add_argument("--provider-budget-record", type=Path)
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
        if (args.continue_from is None) != (args.provider_budget_record is None):
            raise ValueError("--continue-from and --provider-budget-record must be used together")
        directory = execute_screening(
            args.ledger.resolve(), args.source_commit,
            resume_directory=None if args.resume is None else args.resume.resolve(),
            diagnostic_task_id=args.diagnose_task,
            continuation_directory=(
                None if args.continue_from is None else args.continue_from.resolve()
            ),
            provider_budget_record_path=(
                None if args.provider_budget_record is None
                else args.provider_budget_record.resolve()
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
