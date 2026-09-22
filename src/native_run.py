"""Opt-in, commit-bound native runner; no provider access during validation."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib.metadata
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import time
import tomllib

from accounting import now
from .baseline import baseline_summary, compare_quality, interim_baseline_gate
from .blob_retrieval import make_blob_spool, retrieval_settings
from .compressors import check_compressor_artifacts, make_compressor
from .contracts import safe_child, save_json
from .harbor_no_time_limits import apply_no_time_limit_policy, command as harbor_command
from .live_observations import POLICY
from .execution_safety import SafetyLimitReached, safety_policy_record
from .live_transport import (
    cache_namespace_message,
    DeploymentQueue,
    FoundrySender,
    LiveRecorder,
    ManagedIdentity,
    TrialRequestBlocked,
    start_live_proxy,
)
from .measurement import load_encoder
from .native_contract import CONDITIONS, TASKS, load_native_ledger, require_operational_values
from .native_judge import collect_native_outcome
from .protection import digest
from .provenance import ROOT, capture, git, verify_snapshot
from .runtime_limits import public_queue_record, runtime_queue_limits
from .task_metrics import aggregate_run_compressor_metrics, aggregate_run_timing_metrics, collect_trial_metrics, read_events
from .verifier_revisions import apply_verifier_revision


def runtime_environment(proxy_key: str) -> dict:
    allowed = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG",
               "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "TIKTOKEN_CACHE_DIR")
    environment = {name: os.environ[name] for name in allowed if name in os.environ}
    environment.update({
        "OPENAI_API_KEY": proxy_key, "LITELLM_LOCAL_MODEL_COST_MAP": "true",
        "LITELLM_LOG": "ERROR", "DO_NOT_TRACK": "1", "PYTHONPATH": str(ROOT),
    })
    return environment


def benchmark_sources(ledger: dict) -> tuple[Path, dict[str, dict[str, bytes]]]:
    specification = ledger["benchmark"]
    value = os.environ.get(specification["root_env"])
    if not value:
        raise ValueError(f"Set {specification['root_env']} to the pinned benchmark checkout")
    root = Path(value).resolve(strict=True)
    if git(root, "rev-parse", "--show-toplevel").decode().strip() != str(root) or git(root, "rev-parse", "HEAD").decode().strip() != specification["revision"]:
        raise ValueError("Benchmark checkout differs from the ledger revision")
    tasks = {}
    for task in TASKS:
        prefix = f"tasks/{task}/"
        names = git(root, "ls-tree", "-r", "--name-only", specification["revision"], "--", prefix).decode().splitlines()
        if not names:
            raise ValueError("A fixed task is absent from the pinned benchmark")
        files = {}
        for name in names:
            path = safe_child(root, name)
            if (root / name).is_symlink() or not path.is_file():
                raise ValueError("Benchmark task files must be regular committed files")
            content = path.read_bytes()
            if content != git(root, "show", f"{specification['revision']}:{name}"):
                raise ValueError(f"Benchmark file changed: {name}")
            files[name.removeprefix(prefix)] = content
        if not {"task.toml", "instruction.md", "tests/test.sh", "tests/test_outputs.py"} <= files.keys():
            raise ValueError("Task is missing its instruction or native judge")
        tasks[task] = files
    return root, tasks


def prepare_task(task: str, files: dict[str, bytes], target: Path, image: str, verifier_specs: dict) -> dict:
    before = tomllib.loads(files["task.toml"].decode())
    text, count = re.subn(r'(?m)^docker_image\s*=\s*"[^"\n]+"\s*$', f'docker_image = "{image}"', files["task.toml"].decode())
    after = tomllib.loads(text)
    expected = deepcopy(before)
    expected["environment"]["docker_image"] = image
    if count != 1 or after != expected:
        raise ValueError("Task image pinning would change another task setting")
    effective, verifier_revision = apply_verifier_revision(task, files, verifier_specs)
    effective.update({"task.toml": text.encode(), "environment/Dockerfile": f"FROM {image}\n".encode()})
    modified_files = sorted(name for name in effective if effective[name] != files.get(name))
    expected_modified = {"task.toml", "environment/Dockerfile"}
    if verifier_revision["modified"]:
        expected_modified.add(verifier_revision["source_path"])
    if set(modified_files) != expected_modified:
        raise ValueError("Task preparation changed a file outside the approved image and verifier revisions")
    target.mkdir(parents=True, exist_ok=False)
    for name, content in effective.items():
        path = safe_child(target, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return {
        "source_files": {name: digest(content) for name, content in files.items()},
        "effective_files": {name: digest(content) for name, content in effective.items()},
        "only_environment_image_is_overridden": not verifier_revision["modified"],
        "only_approved_files_modified": True,
        "approved_modified_files": modified_files,
        "native_judge_modified": verifier_revision["modified"],
        "verifier_revision": verifier_revision,
        "pinned_image": image,
    }


def harbor_config(ledger: dict, task_path: Path, jobs: Path, trial_id: str, api_base: str) -> dict:
    runner, model = ledger["runner"], ledger["model"]
    llm_kwargs = {"num_retries": 0}
    if ledger.get("schema_version") == 4:
        llm_kwargs["max_completion_tokens"] = ledger["limits"]["max_output_tokens"]
    return {
        "job_name": trial_id, "jobs_dir": str(jobs), "n_attempts": 1, "n_concurrent_trials": 1,
        "retry": {"max_retries": 0}, "quiet": True,
        "environment": {"type": "docker", "force_build": False, "delete": True},
        "verifier": {"disable": False},
        "tasks": [{"path": str(task_path)}],
        "agents": [{
            "import_path": runner["agent_import_path"], "model_name": "openai/" + model["name"],
            "n_concurrent": 1,
            "kwargs": {
                "api_base": api_base, "enable_summarize": False,
                "use_responses_api": False, "store_all_messages": True,
                "temperature": model["temperature"], "reasoning_effort": model["reasoning_effort"],
                "llm_kwargs": llm_kwargs,
            },
        }],
    }


def terminate_group(process, grace_seconds: float = 2) -> None:
    try:
        os.killpg(process.pid, signal.SIGINT)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


def supervise(
    command: list[str],
    log: Path,
    recorder,
    environment: dict,
    on_start=None,
    on_timing_start=None,
    trial_id: str | None = None,
) -> dict:
    recorder.check()
    started, started_at = time.monotonic(), now()
    if on_timing_start is not None:
        on_timing_start(started_at)
    stopped = False
    safety_stop = None
    with log.open("xb") as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                                   env=environment, cwd=ROOT, start_new_session=True, stdin=subprocess.DEVNULL)
        try:
            if on_start is not None:
                on_start(process.pid)
            while process.poll() is None:
                if trial_id is not None:
                    try:
                        recorder.check_trial(trial_id)
                    except SafetyLimitReached as error:
                        recorder.record_safety_stop(trial_id, error)
                        safety_stop = error.details
                        stopped = True
                    except TrialRequestBlocked:
                        stopped = True
                stopped = stopped or recorder.stopped.is_set()
                if stopped:
                    terminate_group(process)
                    break
                time.sleep(0.05)
        except BaseException:
            recorder.stop("NativeSupervisorInterrupted")
            terminate_group(process)
            raise
    return {"returncode": process.returncode, "timed_out": False, "stopped_by_guard": stopped,
            "started_at": started_at, "finished_at": now(), "elapsed_seconds": time.monotonic() - started,
            "docker_cleanup_verified": False, "safety_stop": safety_stop}


def runtime_versions() -> dict:
    packages = tomllib.loads((ROOT / "uv.lock").read_text())["package"]
    versions = {}
    for name in ("harbor", "litellm", "openai", "httpx", "pydantic", "tiktoken"):
        expected = {package["version"] for package in packages if package["name"] == name}
        installed = importlib.metadata.version(name)
        if expected != {installed}:
            raise ValueError(f"Runtime {name} differs from uv.lock; sync the locked native extra")
        versions[name] = installed
    return versions


def preflight(
    ledger: dict,
    ledger_path: Path,
    source_commit: str,
    condition: str = "none",
    *,
    required_conditions=CONDITIONS,
) -> dict:
    safety_policy = require_operational_values(ledger)
    if condition not in ledger["conditions"]:
        raise ValueError("Condition is not part of the fixed native design")
    provenance, snapshots = capture(ledger_path, source_commit)
    versions = runtime_versions()
    from harbor.models.job.config import JobConfig

    harbor_limit_policy = apply_no_time_limit_policy()
    JobConfig.model_validate(harbor_config(ledger, ROOT / "placeholder", ROOT / "runs", "check", "http://127.0.0.1:1/check/v1"))
    encoder = load_encoder(ledger["measurement"])
    benchmark_root, tasks = benchmark_sources(ledger)
    retrieval = retrieval_settings(ledger, ROOT)
    endpoint = os.environ.get(ledger["model"]["endpoint_env"], "")
    sender = FoundrySender(
        endpoint,
        ManagedIdentity(),
        timeout_seconds=ledger["limits"]["provider_http_timeout_seconds"],
    )
    queue_value = os.environ.get(ledger["queue"]["state_path_env"])
    if not queue_value or not Path(queue_value).is_absolute():
        raise ValueError("Use the same absolute queue file for every deployment caller")
    if Path(queue_value).resolve().is_relative_to(ROOT / "runs"):
        raise ValueError("A per-run queue cannot coordinate the deployment")
    if not required_conditions or any(name not in CONDITIONS for name in required_conditions):
        raise ValueError("Preflight compressor conditions differ from the native design")
    for compressor_name in required_conditions:
        check_compressor_artifacts(ledger["compressor"], compressor_name)
    return {"provenance": provenance, "snapshots": snapshots, "encoder": encoder, "tasks": tasks,
            "benchmark_root": str(benchmark_root), "sender": sender, "queue_path": Path(queue_value).resolve(),
            "queue_limits": runtime_queue_limits(ledger["queue"], ledger["schema_version"]),
            "runtime_versions": versions, "retrieval": retrieval,
            "safety_policy": safety_policy,
            "harbor_limit_policy": harbor_limit_policy}


def verify_native_run(directory: Path) -> dict:
    summary = json.loads((directory / "summary.json").read_bytes())
    if summary.get("kind") != "native_measurement" or summary.get("mode") != "native_candidate_compression":
        raise ValueError("Synthetic or static records cannot serve as a native baseline")
    source = verify_snapshot(directory)
    if source["source_commit"] != summary["source_commit"] or source["ledger_sha256"] != summary["ledger_sha256"]:
        raise ValueError("Native result and source provenance differ")
    ledger = load_native_ledger(directory / "ledger.toml")
    execution = json.loads((directory / "execution.json").read_bytes())
    deployment_limits = public_queue_record(ledger["queue"], ledger["schema_version"])
    if summary.get("concurrency") != ledger["runner"]["concurrency"] or summary.get("deployment_limits") != deployment_limits:
        raise ValueError("Native result concurrency or deployment limits differ from the ledger")
    if execution.get("concurrency") != ledger["runner"]["concurrency"] or execution.get("deployment_limits") != deployment_limits:
        raise ValueError("Native execution metadata concurrency or limits differ from the ledger")
    if ledger["schema_version"] == 4:
        expected_safety = safety_policy_record(ledger, applied=True)
        if summary.get("execution_safety") != expected_safety or execution.get("execution_safety") != expected_safety:
            raise ValueError("Native execution safety record differs from the applied ledger")
    if summary.get("verifier_revisions") != ledger["benchmark"]["verifiers"] or execution.get("verifier_revisions") != ledger["benchmark"]["verifiers"]:
        raise ValueError("Native result verifier revisions differ from the ledger")
    manifest_path = directory / "artifacts.json"
    if digest(manifest_path.read_bytes()) != summary["artifact_manifest_sha256"]:
        raise ValueError("Native artifact manifest changed")
    files = json.loads(manifest_path.read_bytes())["files"]
    actual = {path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file() or path.is_symlink()}
    if set(files) != actual - {"artifacts.json", "summary.json"}:
        raise ValueError("Native artifact inventory is incomplete or has extra files")
    for name, expected in files.items():
        if (directory / name).is_symlink() or digest(safe_child(directory, name).read_bytes()) != expected:
            raise ValueError(f"Native artifact changed: {name}")
    if {name for name in files if re.fullmatch(r"trials/[^/]+/trial.json", name)} != {trial["record_path"] for trial in summary["trials"]}:
        raise ValueError("Summary must include every recorded native trial")
    if summary["condition"] not in CONDITIONS or summary["status"] not in (
        "complete", "inconclusive", "stopped", "retrieval_pending"
    ):
        raise ValueError("Unexpected native condition or completion state")
    repetitions, rewards, incomplete_repetition = [], {}, False
    for index, trial in enumerate(summary["trials"]):
        repetition, task = index // len(TASKS) + 1, TASKS[index % len(TASKS)]
        trial_id = f"r{repetition:02d}-{task}"
        if (trial["task"], trial["repetition"], trial["trial_id"], trial["source_commit"], trial["condition"], trial["kind"]) != (
            task, repetition, trial_id, summary["source_commit"], summary["condition"], summary["kind"]
        ) or trial["record_path"] != f"trials/{trial_id}/trial.json" or trial["record_path"] not in files:
            raise ValueError("Native trial lineage or fixed task order differs")
        if json.loads(safe_child(directory, trial["record_path"]).read_bytes()) != {key: value for key, value in trial.items() if key != "record_path"}:
            raise ValueError("Summary differs from the native trial record")
        process = trial["process"]
        job = directory / "jobs" / trial_id
        outcome = collect_native_outcome(job, process=process, transport_failure=trial["transport_failure"])
        completed = not process["timed_out"] and not process["stopped_by_guard"] and process["returncode"] == 0
        metrics = collect_trial_metrics(job, directory / "transport", trial_id, process_complete=completed)
        if outcome != trial["native_outcome"] or metrics != trial["metrics"]:
            raise ValueError("Native outcome or metrics differ from their recorded evidence")
        if outcome["quality_valid"] and metrics["measurement_complete"]:
            if not incomplete_repetition:
                rewards[task] = int(outcome["native_reward"])
            if not incomplete_repetition and len(rewards) == len(TASKS):
                repetitions.append(rewards)
                rewards = {}
        else:
            incomplete_repetition = True
        if incomplete_repetition and task == TASKS[-1]:
            rewards = {}
    if incomplete_repetition and summary["status"] != "stopped":
        raise ValueError("An invalid trial must stop the run, not become a zero")
    if summary["repetitions"] != repetitions:
        raise ValueError("Native repetitions differ from the individual trial rewards")
    retrieval = json.loads((directory / "retrieval.json").read_bytes())
    if summary.get("retrieval") != retrieval:
        raise ValueError("Native retrieval summary differs from its record")
    if (
        retrieval.get("kind") != "native_blob_retrieval"
        or retrieval.get("run_id") != summary["run_id"]
        or retrieval.get("source_commit") != summary["source_commit"]
        or retrieval.get("ledger_sha256") != summary["ledger_sha256"]
        or retrieval.get("condition") != summary["condition"]
        or retrieval.get("credentials_recorded") is not False
    ):
        raise ValueError("Native retrieval lineage or credential boundary differs")
    expected_items = [f"repetition-{index:03d}" for index in range(1, len(repetitions) + 1)]
    if [item.get("item_id") for item in retrieval.get("items", [])] != expected_items:
        raise ValueError("Native retrieval items differ from complete repetitions")
    if summary["status"] in ("complete", "inconclusive") and retrieval.get("upload_state") != "uploaded":
        raise ValueError("A complete native run requires every repetition manifest in Blob")
    if summary["status"] == "retrieval_pending" and retrieval.get("upload_state") != "retrieval_pending":
        raise ValueError("Retrieval-pending status needs an unfinished Blob upload")
    measurement_status = summary.get("completion_status_before_retrieval", summary["status"])
    if summary["status"] == "retrieval_pending" and measurement_status not in ("complete", "inconclusive"):
        raise ValueError("Retrieval-pending run lacks its pre-retrieval measurement status")
    interim = interim_baseline_gate(repetitions[:5], list(TASKS)) if len(repetitions) >= 5 else None
    if summary["condition"] == "none" and summary.get("interim_decision") != interim:
        raise ValueError("The five-repetition baseline gate differs from native rewards")
    if summary["condition"] == "none" and len(repetitions) == 5:
        gate_stop = (summary.get("stop_reason") or {}).get("reason") == "InterimBaselineVariability"
        if summary["status"] != "stopped" or gate_stop != (interim["decision"] == "stop_for_design_audit"):
            raise ValueError("A five-repetition baseline stop differs from the predeclared gate or later failure")
    elif summary["condition"] == "none" and summary["status"] in ("complete", "inconclusive", "retrieval_pending"):
        if len(repetitions) not in (10, 20) or rewards:
            raise ValueError("A completed baseline requires complete repetitions")
        if len(repetitions) == 20 and baseline_summary(repetitions[:10], list(TASKS))["status"] == "observed_range_stabilized":
            raise ValueError("Baseline continued past its predeclared ten-repetition stop")
        decision = baseline_summary(repetitions, list(TASKS))
        decision["rule_status"] = "accepted_in_execution_ledger"
        if summary.get("baseline_decision") != json.loads(json.dumps(decision)):
            raise ValueError("Baseline stopping decision differs from the native rewards")
        informative = decision["status"] == "observed_range_stabilized" and decision["comparison_informative"]
        if (measurement_status == "complete") != informative:
            raise ValueError("Uninformative baseline cannot be labeled complete")
    if summary.get("compressor_metrics") != aggregate_run_compressor_metrics(summary["trials"]):
        raise ValueError("Run compressor metrics differ from the trial records")
    if summary.get("timing_metrics") != aggregate_run_timing_metrics(summary["trials"]):
        raise ValueError("Run phase timings differ from the trial records")
    if summary["condition"] != "none" and measurement_status == "complete":
        reference_bytes = (directory / "baseline-summary.json").read_bytes()
        if digest(reference_bytes) != summary["baseline"]["summary_sha256"]:
            raise ValueError("Verified baseline snapshot changed")
        reference = json.loads(reference_bytes)
        if reference["source_commit"] != summary["source_commit"] or reference["condition"] != "none" or reference["status"] != "complete" or rewards:
            raise ValueError("Comparison needs the same complete native baseline")
        changed = sum(trial["metrics"]["changed_candidate_occurrences"] for trial in summary["trials"])
        comparison = compare_quality(reference["repetitions"], repetitions, list(TASKS), changed)
        comparison["rule_status"] = "accepted_in_execution_ledger"
        if summary.get("quality_comparison") != comparison:
            raise ValueError("Quality comparison differs from the recorded native rewards")
    return summary


def verify_cache_bundle_run(directory: Path) -> dict:
    summary = json.loads((directory / "summary.json").read_bytes())
    if summary.get("kind") != "native_measurement" or summary.get("execution_profile") != "cache_reuse_bundle":
        raise ValueError("Only a measured cache-reuse native bundle is admissible")
    ledger = load_native_ledger(directory / "ledger.toml")
    context = _cache_bundle_context(summary.get("cache_reuse"), summary.get("condition"), ledger)
    source = verify_snapshot(directory)
    if source["source_commit"] != summary.get("source_commit") or source["ledger_sha256"] != summary.get("ledger_sha256"):
        raise ValueError("Cache bundle source or native ledger lineage differs")
    if summary.get("concurrency") != 1 or len(summary.get("trials", [])) != len(TASKS):
        raise ValueError("Cache bundle must contain one serial five-task repetition")
    execution = json.loads((directory / "execution.json").read_bytes())
    if execution.get("cache_reuse") != context or execution.get("concurrency") != 1:
        raise ValueError("Cache bundle execution metadata differs from its context")
    if ledger["schema_version"] == 4:
        expected_safety = safety_policy_record(ledger, applied=True)
        if summary.get("execution_safety") != expected_safety or execution.get("execution_safety") != expected_safety:
            raise ValueError("Cache bundle execution safety record differs from the applied ledger")
    manifest_path = directory / "artifacts.json"
    if digest(manifest_path.read_bytes()) != summary.get("artifact_manifest_sha256"):
        raise ValueError("Cache bundle artifact manifest changed")
    files = json.loads(manifest_path.read_bytes()).get("files")
    actual = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*") if path.is_file() or path.is_symlink()
    }
    if not isinstance(files, dict) or set(files) != actual - {"artifacts.json", "summary.json"}:
        raise ValueError("Cache bundle artifact inventory is incomplete or has extra files")
    for name, expected in files.items():
        path = safe_child(directory, name)
        if path.is_symlink() or digest(path.read_bytes()) != expected:
            raise ValueError(f"Cache bundle artifact changed: {name}")
    repetitions = {}
    for task, trial in zip(TASKS, summary["trials"], strict=True):
        trial_id = f"r01-{task}"
        if (
            trial.get("task"), trial.get("repetition"), trial.get("trial_id"),
            trial.get("condition"), trial.get("source_commit"), trial.get("kind"),
        ) != (task, 1, trial_id, summary["condition"], summary["source_commit"], summary["kind"]):
            raise ValueError("Cache bundle trial order or lineage differs")
        record_path = trial.get("record_path")
        if record_path != f"trials/{trial_id}/trial.json":
            raise ValueError("Cache bundle trial record path differs")
        stored = json.loads(safe_child(directory, record_path).read_bytes())
        if stored != {key: value for key, value in trial.items() if key != "record_path"}:
            raise ValueError("Cache bundle summary differs from its trial record")
        process = trial["process"]
        job = directory / "jobs" / trial_id
        outcome = collect_native_outcome(job, process=process, transport_failure=trial["transport_failure"])
        completed = not process["timed_out"] and not process["stopped_by_guard"] and process["returncode"] == 0
        metrics = collect_trial_metrics(job, directory / "transport", trial_id, process_complete=completed)
        if outcome != trial["native_outcome"] or metrics != trial["metrics"] or not trial_is_complete(trial):
            raise ValueError("Cache bundle native outcome or mandatory metrics differ")
        repetitions[task] = int(outcome["native_reward"])
    if summary.get("repetitions") != [repetitions]:
        raise ValueError("Cache bundle native repetition denominator differs")
    measurement_status = summary.get("completion_status_before_retrieval", summary.get("status"))
    if measurement_status != "complete":
        raise ValueError("Cache bundle did not complete its useful native repetition")
    events = read_events(directory / "transport/events.jsonl")
    attempts = [event for event in events if event.get("event") == "attempt_started"]
    responses = [event for event in events if event.get("event") == "http"]
    if not attempts or not responses:
        raise ValueError("Cache bundle has no provider request evidence")
    for event in attempts + responses:
        observation = event.get("cache_reuse")
        if not isinstance(observation, dict) or (
            observation.get("cycle_id"), observation.get("condition"), observation.get("reuse_level"),
            observation.get("eligible_predecessor_count"),
        ) != (
            context["cycle_id"], context["condition"], context["reuse_level"],
            context["eligible_predecessor_count"],
        ):
            raise ValueError("Cache request observation differs from the bundle context")
        if not re.fullmatch(r"[0-9a-f]{64}", observation.get("serialized_prefix_sha256", "")):
            raise ValueError("Cache request lacks its serialized-prefix hash")
    retrieval = json.loads((directory / "retrieval.json").read_bytes())
    if summary.get("retrieval") != retrieval or len(retrieval.get("items", [])) != 1:
        raise ValueError("Cache bundle retrieval must preserve its one completed repetition")
    return summary


def baseline_for_comparison(directory: Path, ledger: dict, source_commit: str) -> dict:
    summary = verify_native_run(directory)
    original_ledger = load_native_ledger(directory / "ledger.toml")
    for key in (
        "benchmark", "model", "runner", "measurement", "compressor", "stability",
        "raw_retrieval", "queue", "retrieval",
    ):
        if original_ledger[key] != ledger[key]:
            raise ValueError(f"Comparison differs from baseline {key}")
    if original_ledger["limits"] != ledger["limits"]:
        raise ValueError("Comparison differs from the baseline execution safety policy")
    if summary["condition"] != "none" or summary["source_commit"] != source_commit or summary["status"] != "complete":
        raise ValueError("Use a complete none baseline from the same execution SHA")
    decision = baseline_summary(summary["repetitions"], list(TASKS))
    if decision["status"] != "observed_range_stabilized" or not decision["comparison_informative"]:
        raise ValueError("Baseline is inconclusive or has no detectable degradation range")
    return summary


def run_trial(directory: Path, ledger: dict, recorder, server, key: str, task: str, repetition: int) -> dict:
    trial_id = f"r{repetition:02d}-{task}"
    trial_directory = directory / "trials" / trial_id
    trial_directory.mkdir(parents=True)
    save_json(trial_directory / "started.json", {"trial_id": trial_id, "started_at": now(),
                                                "source_commit": recorder.source_commit, "kind": recorder.evidence_kind})
    process = {"returncode": None, "timed_out": False, "stopped_by_guard": False}
    try:
        api_base = f"http://127.0.0.1:{server.server_port}/{trial_id}/v1"
        config = harbor_config(ledger, directory / "tasks" / task, directory / "jobs", trial_id, api_base)
        config_path = trial_directory / "harbor-config.json"
        save_json(config_path, config)
        command = harbor_command("run", "--config", str(config_path))
        process = supervise(
            command,
            trial_directory / "harbor.log",
            recorder,
            runtime_environment(key),
            trial_id=trial_id,
        )
    except BaseException as error:
        if isinstance(error, SafetyLimitReached):
            recorder.record_safety_stop(trial_id, error)
        else:
            recorder.stop("NativeTrialExecutionError", {"trial_id": trial_id, "error_type": type(error).__name__})
        process.update(stopped_by_guard=True, error_type=type(error).__name__)
    finally:
        recorder.close_trial(trial_id)
    job = directory / "jobs" / trial_id
    with recorder.lock:
        trial_failure = deepcopy(recorder.trials[trial_id]["failure"])
    transport_failure = trial_failure or deepcopy(recorder.failure)
    outcome = collect_native_outcome(job, process=process, transport_failure=transport_failure)
    completed = not process["timed_out"] and not process["stopped_by_guard"] and process["returncode"] == 0
    metrics = collect_trial_metrics(job, directory / "transport", trial_id, process_complete=completed)
    trial = {"kind": recorder.evidence_kind, "source_commit": recorder.source_commit, "condition": recorder.condition,
             "task": task, "repetition": repetition, "trial_id": trial_id, "transport_failure": transport_failure,
             "native_outcome": outcome, "metrics": metrics, "process": process,
             "execution_safety": recorder.safety_snapshot(trial_id),
             "evidence_state": {
                 "workspace_recorded": job.exists(),
                 "replay_evidence": "not_configured_for_native_five_task_runner",
                 "verifier_executed": outcome["native_reward"] is not None,
             }}
    path = trial_directory / "trial.json"
    save_json(path, trial)
    return {**trial, "record_path": path.relative_to(directory).as_posix()}


def trial_is_complete(trial: dict) -> bool:
    return trial["native_outcome"]["quality_valid"] and trial["metrics"]["measurement_complete"]


def run_trial_plans(directory: Path, ledger: dict, recorder, server, key: str,
                    plans: list[tuple[str, int]], on_repetition=None) -> list[dict]:
    concurrency = ledger["runner"]["concurrency"]
    completed = []
    reported = 0
    for offset in range(0, len(plans), concurrency):
        recorder.check()
        wave = plans[offset:offset + concurrency]
        for task, repetition in wave:
            recorder.register_trial(f"r{repetition:02d}-{task}", task, repetition)
        with ThreadPoolExecutor(max_workers=len(wave), thread_name_prefix="native-trial") as executor:
            futures = [executor.submit(run_trial, directory, ledger, recorder, server, key, task, repetition)
                       for task, repetition in wave]
            trials = [future.result() for future in futures]
        completed.extend(trials)
        while len(completed) - reported >= len(TASKS):
            group = completed[reported:reported + len(TASKS)]
            expected_repetition = plans[reported][1]
            if any(not trial_is_complete(trial) for trial in group):
                break
            if [trial["task"] for trial in group] != list(TASKS) or any(
                trial["repetition"] != expected_repetition for trial in group
            ):
                raise ValueError("Completed repetition differs from the fixed task plan")
            if on_repetition is not None:
                on_repetition(expected_repetition, group)
            reported += len(TASKS)
        if any(not trial_is_complete(trial) for trial in trials):
            incomplete = [trial for trial in trials if not trial_is_complete(trial)]
            safety = next(
                (
                    trial["transport_failure"] for trial in incomplete
                    if (trial.get("transport_failure") or {}).get("reason") == "SafetyLimitReached"
                ),
                None,
            )
            recorder.stop(
                "SafetyLimitReached" if safety is not None else "NativeOutcomeOrMandatoryMetricsIncomplete",
                safety["details"] if safety is not None else {
                    "trial_ids": [trial["trial_id"] for trial in incomplete]
                },
            )
            break
    return completed


def run_repetition_block(directory: Path, ledger: dict, recorder, server, key: str,
                         first: int, last: int, on_repetition=None) -> tuple[list[dict], list[dict], bool]:
    plans = [(task, repetition) for repetition in range(first, last + 1) for task in TASKS]
    trials = run_trial_plans(directory, ledger, recorder, server, key, plans, on_repetition)
    expected = (last - first + 1) * len(TASKS)
    repetitions = []
    for offset in range(0, len(trials), len(TASKS)):
        group = trials[offset:offset + len(TASKS)]
        if len(group) != len(TASKS) or any(not trial_is_complete(trial) for trial in group):
            break
        repetitions.append({trial["task"]: int(trial["native_outcome"]["native_reward"])
                            for trial in group})
    complete = len(trials) == expected and all(trial_is_complete(trial) for trial in trials)
    return trials, repetitions, complete


def _cache_bundle_context(value: dict | None, condition: str, ledger: dict) -> dict | None:
    if value is None:
        return None
    required = {
        "cycle_id", "bundle_id", "condition", "reuse_level", "eligible_predecessor_count",
        "cache_ledger_sha256", "native_ledger_sha256", "runtime_facts_sha256",
        "isolation_evidence_sha256",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("Cache bundle context fields differ from the execution contract")
    if value["condition"] != condition or condition not in ("none", "squeez"):
        raise ValueError("Cache bundle condition differs from the native condition")
    if value["reuse_level"] not in (0, 1, 2) or value["eligible_predecessor_count"] != value["reuse_level"]:
        raise ValueError("Cache bundle predecessor count differs from its reuse level")
    for name in ("cycle_id", "bundle_id"):
        if not isinstance(value[name], str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,127}", value[name]):
            raise ValueError("Cache bundle identifiers must be safe and bounded")
    for name in (
        "cache_ledger_sha256", "native_ledger_sha256",
        "runtime_facts_sha256", "isolation_evidence_sha256",
    ):
        if not isinstance(value[name], str) or not re.fullmatch(r"[0-9a-f]{64}", value[name]):
            raise ValueError("Cache bundle evidence bindings require SHA-256")
    if ledger["runner"]["concurrency"] != 1:
        raise ValueError("Cache-reuse mode requires native concurrency 1 before provider dispatch")
    return value


def execute_native(
    ledger_path: Path,
    ledger: dict,
    source_commit: str,
    condition: str,
    baseline_path: Path | None = None,
    *,
    cache_context: dict | None = None,
    request_observer=None,
) -> Path:
    cache_context = _cache_bundle_context(cache_context, condition, ledger)
    cache_mode = cache_context is not None
    if condition not in ledger["conditions"]:
        raise ValueError("Condition is not part of the native ledger")
    if cache_mode:
        if baseline_path is not None or request_observer is None:
            raise ValueError("Cache bundle execution needs an observer and cannot use a comparison baseline")
    elif (condition != "none") != (baseline_path is not None):
        raise ValueError("Run none first; every compression condition requires its verified native baseline")
    baseline = baseline_for_comparison(baseline_path, ledger, source_commit) if baseline_path else None
    required_conditions = ("none", "squeez") if cache_mode else CONDITIONS
    setup = preflight(
        ledger, ledger_path, source_commit, condition,
        required_conditions=required_conditions,
    )
    deployment = digest((setup["sender"].endpoint + "/" + ledger["model"]["name"]).encode())
    if baseline:
        original_execution = json.loads((baseline_path / "execution.json").read_bytes())
        if original_execution["deployment_sha256"] != deployment or original_execution["queue_path"] != str(setup["queue_path"]):
            raise ValueError("Comparison must share the baseline deployment and queue")
    run_prefix = f"native-cache-{cache_context['bundle_id']}" if cache_mode else f"native-{condition}"
    run_id = f"{run_prefix}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{secrets.token_hex(4)}"
    directory = ROOT / ledger["output_dir"] / run_id
    directory.mkdir(parents=True, exist_ok=False)
    os.chmod(directory, 0o700)
    for name, content in setup["snapshots"].items():
        path = safe_child(directory, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    save_json(directory / "provenance.json", setup["provenance"])
    if baseline is not None:
        (directory / "baseline-summary.json").write_bytes((baseline_path / "summary.json").read_bytes())
    summary = {
        "schema_version": 1, "kind": setup.get("evidence_kind", "native_measurement"), "mode": ledger["mode"], "run_id": run_id,
        "execution_profile": "cache_reuse_bundle" if cache_mode else "standard_native_comparison",
        "source_commit": source_commit, "ledger_sha256": setup["provenance"]["ledger_sha256"],
        "condition": condition, "status": "running", "started_at": now(), "trials": [], "repetitions": [],
        "classification_policy": POLICY, "determinism_controlled": False, "cache_controlled": False,
        "concurrency": ledger["runner"]["concurrency"],
        "deployment_limits": public_queue_record(ledger["queue"], ledger["schema_version"]),
        "raw_retrieval": ledger["raw_retrieval"], "baseline": None if baseline is None else {
            "run_id": baseline["run_id"], "summary_sha256": digest((baseline_path / "summary.json").read_bytes())},
        "verifier_revisions": ledger["benchmark"]["verifiers"],
        "compressor_metrics": aggregate_run_compressor_metrics([]),
        "timing_metrics": aggregate_run_timing_metrics([]),
        "execution_safety": setup["safety_policy"],
    }
    if cache_mode:
        summary["cache_reuse"] = cache_context
    queue = recorder = server = compressor = retrieval = None
    try:
        queue = DeploymentQueue(setup["queue_path"], deployment, *setup["queue_limits"])
        compressor_specification = {**ledger["compressor"], "name": condition}
        compressor = make_compressor(compressor_specification, directory / "compressor")
        recorder = LiveRecorder(
            directory / "transport", ledger, source_commit, compressor, setup["encoder"], queue,
            setup["sender"], condition=condition, evidence_kind=summary["kind"],
            request_observer=request_observer,
            request_prefix_message=(
                cache_namespace_message(cache_context["isolation_evidence_sha256"])
                if cache_mode else None
            ),
        )
        key = secrets.token_urlsafe(32)
        server = start_live_proxy(recorder, key)
        task_sources = {task: prepare_task(
            task, files, directory / "tasks" / task, ledger["benchmark"]["images"][task],
            ledger["benchmark"]["verifiers"],
        )
                        for task, files in setup["tasks"].items()}
        save_json(directory / "task-sources.json", task_sources)
        execution_record = {
            "source_commit": source_commit, "condition": condition, "compressor": compressor.metadata,
            "classification_policy": POLICY, "task_order": list(TASKS),
            "verifier_revisions": ledger["benchmark"]["verifiers"],
            "concurrency": ledger["runner"]["concurrency"],
            "concurrency_unit": "simultaneous_native_trial_processes",
            "harbor_concurrency_per_process": 1, "agent_concurrency_per_trial": 1,
            "scheduling": "contiguous_trial_waves_across_repetition_boundaries",
            "deployment_limits": summary["deployment_limits"],
            "queue_path": str(setup["queue_path"]), "deployment_sha256": deployment,
            "queue_scope": "cooperating_callers_on_one_host_using_this_exclusive_queue",
            "external_callers_independently_verified": False,
            "deployment_isolation_reference": ledger["queue"]["deployment_isolation_reference"],
            "retrieval": {
                "account_url_sha256": digest(setup["retrieval"]["client"].account_url.encode()),
                "container": setup["retrieval"]["container"], "prefix": setup["retrieval"]["prefix"],
                "account_url_env": ledger["retrieval"]["account_url_env"],
                "spool_root_env": ledger["retrieval"]["spool_root_env"],
                "credentials": "system_assigned_managed_identity_not_recorded",
                "nas_read_verification": "external_shutdown_gate",
            },
            "benchmark_root": setup["benchmark_root"],
            "execution_safety": setup["safety_policy"],
            "harness_stop_policy": ledger["limits"],
            "harbor_limit_policy": setup["harbor_limit_policy"],
            "runtime_versions": setup["runtime_versions"], "python": sys.version,
        }
        if cache_mode:
            execution_record["cache_reuse"] = cache_context
        save_json(directory / "execution.json", execution_record)
        retrieval = make_blob_spool(
            setup["retrieval"], run_id, source_commit, setup["provenance"]["ledger_sha256"], condition
        )

        def stage_repetition(repetition, repetition_trials):
            retrieval.stage_run_snapshot(directory, repetition, repetition_trials)

        minimum = ledger["stability"]["minimum_repetitions"]
        maximum = len(baseline["repetitions"]) if baseline else ledger["stability"]["maximum_repetitions"]
        first_block_end = ledger["stability"]["interim_repetitions"] if baseline is None else maximum
        if cache_mode:
            trials, repetitions, complete = run_repetition_block(
                directory, ledger, recorder, server, key, 1, 1, stage_repetition,
            )
            summary["trials"].extend(trials)
            summary["repetitions"].extend(repetitions)
            if not complete or len(repetitions) != 1:
                raise ValueError("Cache-reuse bundle requires one complete five-task native repetition")
            summary["status"] = "complete"
        else:
            trials, repetitions, complete = run_repetition_block(
                directory, ledger, recorder, server, key, 1, first_block_end, stage_repetition)
            summary["trials"].extend(trials)
            summary["repetitions"].extend(repetitions)
            if not complete:
                raise ValueError("Native outcome or required metrics are incomplete; no task replacement")
        if not cache_mode and condition == "none":
            interim = interim_baseline_gate(summary["repetitions"], list(TASKS))
            summary["interim_decision"] = interim
            if interim["decision"] == "stop_for_design_audit":
                summary["status"] = "stopped"
                recorder.stop("InterimBaselineVariability", interim)
            else:
                trials, repetitions, complete = run_repetition_block(
                    directory, ledger, recorder, server, key, first_block_end + 1, minimum,
                    stage_repetition,
                )
                summary["trials"].extend(trials)
                summary["repetitions"].extend(repetitions)
                if not complete:
                    raise ValueError("Native outcome or required metrics are incomplete; no task replacement")
                decision = baseline_summary(summary["repetitions"], list(TASKS))
                if decision["status"] == "extend_to_total_20":
                    trials, repetitions, complete = run_repetition_block(
                        directory, ledger, recorder, server, key, minimum + 1, maximum,
                        stage_repetition,
                    )
                    summary["trials"].extend(trials)
                    summary["repetitions"].extend(repetitions)
                    if not complete:
                        raise ValueError("Native outcome or required metrics are incomplete; no task replacement")
                    decision = baseline_summary(summary["repetitions"], list(TASKS))
                decision["rule_status"] = "accepted_in_execution_ledger"
                summary["baseline_decision"] = decision
        if not cache_mode and summary["status"] != "stopped":
            summary["status"] = "complete"
        if not cache_mode and condition == "none" and summary["status"] == "complete" and (
            summary["baseline_decision"]["status"] != "observed_range_stabilized"
            or not summary["baseline_decision"]["comparison_informative"]
        ):
            summary["status"] = "inconclusive"
        if not cache_mode and baseline and summary["status"] == "complete":
            changed = sum(trial["metrics"]["changed_candidate_occurrences"] for trial in summary["trials"])
            summary["quality_comparison"] = compare_quality(baseline["repetitions"], summary["repetitions"], list(TASKS), changed)
            summary["quality_comparison"]["rule_status"] = "accepted_in_execution_ledger"
    except BaseException as error:
        summary.update(status="stopped", error={"type": type(error).__name__, "message": str(error)})
        if recorder is not None:
            recorder.stop(type(error).__name__, getattr(error, "details", {"message": str(error)}))
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if compressor is not None:
            try:
                compressor.close()
            except BaseException as error:
                record = {"type": type(error).__name__, "message": str(error)}
                summary["status"] = "stopped"
                summary.setdefault("error", record)
                summary["compressor_close_error"] = record
                if recorder is not None:
                    recorder.stop("CompressorCloseError", record)
        if recorder is not None:
            with recorder.lock:
                summary["stop_reason"] = recorder.failure
                summary["known_provider_cost_usd"] = recorder.known_provider_cost_usd
                summary["unconfirmed_provider_exposure_usd"] = recorder.unconfirmed_provider_exposure_usd
                summary["pending_provider_exposure_usd"] = recorder.pending_provider_exposure_usd
        if queue is not None:
            queue.close()
        if retrieval is not None:
            wait_seconds = ledger["retrieval"]["final_flush_seconds"]
            try:
                retrieval_record = retrieval.finish(wait_seconds)
            except BaseException as error:
                retrieval_record = {
                    "schema_version": 1, "kind": "native_blob_retrieval",
                    "run_id": run_id, "source_commit": source_commit,
                    "ledger_sha256": setup["provenance"]["ledger_sha256"],
                    "condition": condition, "upload_state": "retrieval_pending", "items": [],
                    "nas_read_verification": "pending_external", "credentials_recorded": False,
                    "finalization_error_type": type(error).__name__,
                }
            save_json(directory / "retrieval.json", retrieval_record)
            summary["retrieval"] = retrieval_record
            if retrieval_record["upload_state"] == "retrieval_pending" and summary["status"] in (
                "complete", "inconclusive"
            ):
                summary["completion_status_before_retrieval"] = summary["status"]
                summary["status"] = "retrieval_pending"
        else:
            retrieval_record = {
                "schema_version": 1, "kind": "native_blob_retrieval", "run_id": run_id,
                "source_commit": source_commit, "ledger_sha256": setup["provenance"]["ledger_sha256"],
                "condition": condition, "upload_state": "retrieval_pending", "items": [],
                "nas_read_verification": "pending_external", "credentials_recorded": False,
                "finalization_error_type": "RetrievalNotInitialized",
            }
            save_json(directory / "retrieval.json", retrieval_record)
            summary["retrieval"] = retrieval_record
        summary["compressor_metrics"] = aggregate_run_compressor_metrics(summary["trials"])
        summary["timing_metrics"] = aggregate_run_timing_metrics(summary["trials"])
        summary["finished_at"] = now()
        artifacts = {path.relative_to(directory).as_posix(): digest(path.read_bytes())
                     for path in sorted(directory.rglob("*")) if path.is_file() and not path.is_symlink()}
        save_json(directory / "artifacts.json", {"kind": "private_artifact_hash_manifest", "files": artifacts})
        summary["artifact_manifest_sha256"] = digest((directory / "artifacts.json").read_bytes())
        save_json(directory / "summary.json", summary)
    return directory


def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", nargs="?", type=Path, default=ROOT / "ledgers/native.template.toml")
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--condition", choices=CONDITIONS, default="none")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--execute", action="store_true", help="Explicitly opt in only after baseline approval")
    parser.add_argument("--check", action="store_true", help="Validate local inputs without starting Harbor or calling a model")
    args = parser.parse_args(arguments)
    try:
        ledger = load_native_ledger(args.ledger)
        if args.execute and args.check:
            raise ValueError("Choose either validation or execution")
        if not args.execute:
            checked = preflight(ledger, args.ledger.resolve(), args.source_commit, args.condition)
            print(json.dumps({"status": "local_preflight_passed", "model_calls": 0,
                              "source_commit": checked["provenance"]["source_commit"]}))
            return 0
        directory = execute_native(args.ledger.resolve(), ledger, args.source_commit, args.condition, args.baseline)
        summary = verify_native_run(directory)
        print(json.dumps({"directory": str(directory), "status": summary["status"]}))
        return 0 if summary["status"] == "complete" else 3
    except (ValueError, OSError, subprocess.SubprocessError, importlib.metadata.PackageNotFoundError) as error:
        print(f"Native preflight or verification failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
