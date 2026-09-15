"""Run the hash-bound Terminal-Bench 2.1 screening plan."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time

from accounting import now
from .blob_retrieval import make_blob_spool, resume_blob_spool, retrieval_settings
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
from .screening_scheduler import ScreeningState, make_screening_manifest, verify_screening_manifest
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


def _prepare_inputs(directory: Path, setup: dict, source_commit: str, run_id: str) -> tuple[dict, dict]:
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
    if replay.get("status") != "complete" or repeated.get("status") != "complete":
        return replay, "replay_mismatch_or_incomplete"
    return replay, None


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
    log_text = (attempt["attempt_directory"] / "harbor.log").read_text(errors="replace")
    result = None
    if not dispatched:
        image_markers = r"(?:manifest unknown|pull access denied|No such image|failed to pull|ImagePull)"
        result = "image_error" if re.search(image_markers, log_text, re.IGNORECASE) else "setup_error"
    elif process["timed_out"]:
        result = "timeout"
    elif request_failure is not None:
        reason = request_failure["reason"]
        result = "network_error" if reason in {"TimeoutError", "ConnectionError", "OSError"} else "provider_error"
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
    return {
        "result": result,
        "provider_dispatched": dispatched,
        "provider_cost": provider,
        "native_outcome": outcome,
        "metrics": metrics,
        "replay_manifest_sha256": None if replay is None else replay.get("manifest_sha256"),
        "replay_error": replay_error,
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
    provider = {
        "kind": "provider_usage_times_fixed_rates_not_invoice_reconciliation",
        "currency": "USD",
        "requests": provider_state["requests"],
        "known_cost_usd": provider_state["known_cost_usd"],
        "unknown_attempts": provider_state["unknown_requests"],
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
    vm = {
        "kind": "sum_of_attempt_active_vm_allocations",
        "currency": "USD",
        "attempts_with_cost": len(vm_values),
        "attempts_missing_cost": missing_vm_records,
        "calculated_cost_usd": sum(vm_values) if missing_vm_records == 0 else None,
    }
    blob = blob_operation_cost(
        retrieval["items"],
        ledger["cost"]["blob_write_per_10000_operations_usd"],
        ledger["cost"]["blob_read_per_10000_operations_usd"],
        ledger["cost"]["same_region_network_per_gb_usd"],
    )
    return {
        "kind": "screening_direct_attributable_variable_cost",
        "provider": provider,
        "active_vm": vm,
        "blob_and_network": blob,
        "combined": combined_direct_cost(provider, vm, blob),
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
    save_json(directory / "summary.json", summary)
    return staged


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
        if provider["unknown_requests"]:
            raise ValueError("Provider cost is unknown for an earlier request; resume cannot enforce the budget ceiling")
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


def execute_screening(ledger_path: Path, source_commit: str, *, resume_directory: Path | None = None) -> Path:
    setup = screening_preflight(ledger_path, source_commit)
    ledger = setup["ledger"]
    if resume_directory is None:
        run_id = f"screening-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{secrets.token_hex(4)}"
        directory = ROOT / ledger["output_dir"] / run_id
        directory.mkdir(parents=True, exist_ok=False)
        os.chmod(directory, 0o700)
        manifest, artifacts = _prepare_inputs(directory, setup, source_commit, run_id)
        state = ScreeningState(directory / "state.sqlite3")
        state.initialize(manifest)
        spool = make_blob_spool(
            setup["retrieval"], run_id, source_commit, setup["provenance"]["ledger_sha256"], "none"
        )
        inputs_retrieval = spool.stage_directory(
            directory / "inputs", "run-inputs", kind="terminal_bench_screening_inputs",
            metadata={"manifest_sha256": manifest["manifest_sha256"], "inventory_sha256": manifest["inventory_sha256"]},
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
            "completed_attempts": 0,
            "retrieval_inputs": inputs_retrieval,
            "classification_policy": POLICY,
            "sessions": [{"kind": "initial", "started_at": now()}],
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
    recorder.budget_used_usd = state.provider_cost_state()["known_cost_usd"]
    setup["sender"].deadline = recorder.deadline
    key = secrets.token_urlsafe(32)
    server = start_live_proxy(recorder, key)
    try:
        while True:
            recorder.check()
            claimed = state.claim(ledger["runner"]["concurrency"])
            if not claimed:
                break
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
            for item in completed:
                classification = _classify_attempt(item["attempt"], item["process"], recorder, transport)
                _finalize_attempt(
                    item,
                    classification,
                    vm["attempts"][item["attempt"]["attempt_id"]],
                    state,
                    spool,
                    transport,
                )
                summary["completed_attempts"] += 1
            summary["state"] = state.summary()
            summary["last_progress_at"] = now()
            _stage_checkpoint(directory, state, summary, spool)
            print(json.dumps({
                "run_id": run_id,
                "completed_attempts": summary["completed_attempts"],
                "state": summary["state"],
                "known_provider_cost_usd": recorder.budget_used_usd,
            }, ensure_ascii=False), flush=True)
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
        save_json(directory / "summary.json", summary)
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
        )
        summary = json.loads((directory / "summary.json").read_bytes())
        print(json.dumps({"directory": str(directory), "status": summary["status"]}))
        return 0 if summary["status"] == "complete" else 3
    except (ValueError, OSError, subprocess.SubprocessError, importlib.metadata.PackageNotFoundError) as error:
        print(f"Screening preflight or execution failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
