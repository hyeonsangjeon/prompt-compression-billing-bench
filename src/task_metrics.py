"""Per-native-trial calls, turns, token units and observed command repetitions."""

from collections import Counter
from datetime import datetime
import json
import math
from pathlib import Path

from .command_trace import shell_units, submission_kind
from .protection import digest


def timestamp(value: str) -> float:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Metric timestamps must include a timezone")
    return parsed.timestamp()


def command_metrics(trace: list[dict], changes: list[dict]) -> dict:
    started, finished, issues = {}, {}, []
    for event in trace:
        if event.get("event") not in ("submission_started", "submission_finished"):
            continue
        identifier = event.get("command_id")
        target = started if event["event"] == "submission_started" else finished
        if type(identifier) is not int or identifier < 1 or identifier in target:
            raise ValueError("Command trace has invalid or duplicate identifiers")
        target[identifier] = event
    if set(started) != set(finished):
        issues.append("command_submission_outcome_missing")
    accepted, uncertain = [], []
    for identifier, event in sorted(started.items()):
        content = event["keystrokes"]
        if digest(content.encode()) != event["command_sha256"] or submission_kind(content) != event["submission_kind"] or shell_units(content) != event["shell_units"]:
            raise ValueError("Command trace text and derived fields disagree")
        timestamp(event["at"])
        if event["submission_kind"] != "command_block":
            continue
        if finished.get(identifier, {}).get("status") == "accepted_by_terminal":
            accepted.append(event)
        else:
            uncertain.append(identifier)
    if uncertain:
        issues.append("command_submission_acceptance_uncertain")
    repeats, unit_repeats = [], []
    seen_blocks, seen_units = {}, {}
    for event in accepted:
        command = event["keystrokes"]
        keys = [("block", command, seen_blocks, repeats)]
        keys.extend(("shell_unit", unit, seen_units, unit_repeats) for unit in event["shell_units"])
        for identity, text, seen, destination in keys:
            if text in seen:
                previous = seen[text]
                linked = []
                for change in changes:
                    if not timestamp(previous["at"]) <= timestamp(change["at"]) < timestamp(event["at"]):
                        continue
                    source_command = change.get("echoed_command", "")
                    match = source_command + "\n" == text if identity == "block" else text in shell_units(source_command)
                    if match:
                        linked.append({"request": change["request"], "candidate_index": change["candidate_index"],
                                       "before_sha256": change["before_sha256"], "after_sha256": change["after_sha256"]})
                destination.append({
                    "identity": identity, "command_text": text, "previous_command_id": previous["command_id"],
                    "command_id": event["command_id"], "prior_changed_outputs": linked,
                    "link_basis": "command_text_and_time_order_not_identical_environment",
                    "truncation_causality": "not_established",
                })
            seen[text] = event
    block_counts = Counter(event["keystrokes"] for event in accepted)
    unit_counts = Counter(unit for event in accepted for unit in event["shell_units"])
    return {
        "kind": "calculated_from_terminal_submission_events",
        "unit": "terminal_accepted_command_blocks_not_shell_exit_successes",
        "submitted_command_blocks": len(accepted) + len(uncertain), "accepted_command_blocks": len(accepted),
        "uncertain_command_ids": uncertain,
        "same_command_reexecutions": sum(count - 1 for count in block_counts.values()),
        "repeated_command_texts": sum(count > 1 for count in block_counts.values()),
        "same_subcommand_reexecutions": sum(count - 1 for count in unit_counts.values()),
        "accepted_blocks_not_decomposable": sum(not event["shell_units"] for event in accepted),
        "wait_submissions": sum(event["submission_kind"] == "wait" for event in started.values()),
        "other_terminal_inputs": sum(event["submission_kind"] == "terminal_input_not_complete_command" for event in started.values()),
        "post_changed_output_reexecutions": sum(bool(row["prior_changed_outputs"]) for row in repeats),
        "post_changed_output_subcommand_reexecutions": sum(bool(row["prior_changed_outputs"]) for row in unit_repeats),
        "reexecutions": repeats, "subcommand_reexecutions": unit_repeats,
        "integrity_issues": issues, "truncation_causality": "not_established",
    }


def phase_metrics(responses: list[dict], compressions: list[dict], compression_failures: list[dict]) -> dict:
    for event in responses:
        client = event.get("client_http_seconds")
        if type(client) not in (int, float) or not math.isfinite(client) or client < 0:
            raise ValueError("Client HTTP timing is invalid")
        for name in ("transport_seconds", "model_seconds", "provider_service_seconds", "pre_inference_seconds"):
            value = event.get(name)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise ValueError("Provider phase timing is invalid")

    def total(name: str) -> tuple[float | None, float, int]:
        known = [event[name] for event in responses if event.get(name) is not None]
        return (sum(known) if responses and len(known) == len(responses) else None, sum(known), len(known))

    result = {
        "kind": "measured_and_calculated_phase_seconds",
        "unit": "seconds",
        "provider_http_attempts": len(responses),
        "compress_seconds": sum(event["compressor_wall_seconds"] for event in compressions + compression_failures),
        "client_http_seconds": sum(event["client_http_seconds"] for event in responses),
        "transport_basis": "client_http_minus_provider_service_ttlt",
        "model_basis": "provider_usage_latency_checkpoint_engine_ttlt",
    }
    for name in ("transport_seconds", "model_seconds", "provider_service_seconds", "pre_inference_seconds"):
        complete, subtotal, calls = total(name)
        result[name] = complete
        result["known_" + name] = subtotal
        result["known_" + name.removesuffix("_seconds") + "_calls"] = calls
    return result


def trial_metrics(events: list[dict], trace: list[dict] | None, trajectory: dict | None,
                  trial_id: str, *, process_complete: bool) -> dict:
    selected = [event for event in events if event.get("trial_id") == trial_id]
    attempts = [event for event in selected if event.get("event") == "attempt_started"]
    responses = [event for event in selected if event.get("event") == "http"]
    by_attempt = {(event["request"], event["attempt"]): event for event in responses}
    if len(by_attempt) != len(responses):
        raise ValueError("HTTP attempts would be double-counted")
    expected = {(event["request"], event["attempt"]) for event in attempts}
    if len(expected) != len(attempts) or set(by_attempt) - expected:
        raise ValueError("HTTP attempt lineage is inconsistent")
    known = [event["tokens"] for event in responses if event.get("tokens") is not None]
    unknown = len(attempts) - len(known)
    issues = []
    if not attempts:
        issues.append("no_provider_attempts_recorded")
    if set(by_attempt) != expected:
        issues.append("unfinished_http_attempts")
    if unknown:
        issues.append("provider_usage_incomplete")
    totals = {name: sum(row[name] for row in known) for name in ("input_tokens", "output_tokens")}
    cache_known = [row["cached_input_tokens"] for row in known if row["cached_input_tokens"] is not None]
    steps = trajectory.get("steps") if isinstance(trajectory, dict) else None
    turns = None
    if isinstance(steps, list) and all(isinstance(step, dict) and step.get("source") in ("agent", "user", "system") for step in steps):
        identifiers = [step.get("step_id") for step in steps]
        if any(type(identifier) is not int for identifier in identifiers) or len(set(identifiers)) != len(steps):
            issues.append("native_turn_identifiers_invalid")
        else:
            turns = sum(step["source"] == "agent" for step in steps)
    else:
        issues.append("native_trajectory_missing_or_invalid")
    delivered = sum(event.get("event") == "response_delivered" for event in selected)
    if turns is not None and turns > delivered:
        issues.append("native_turns_exceed_delivered_responses")
    changed = [event for event in selected if event.get("event") == "candidate_changed"]
    compressions = [event for event in selected if event.get("event") == "compressor_completed"]
    compression_failures = [event for event in selected if event.get("event") == "compressor_failed"]
    compression_keys = [(event["request"], event["candidate_index"]) for event in compressions]
    if len(compression_keys) != len(set(compression_keys)):
        raise ValueError("Compressor calls would be double-counted")
    if compression_failures:
        issues.append("compressor_calls_failed")
    for event in compression_failures:
        if type(event.get("compressor_wall_seconds")) not in (int, float) or not math.isfinite(event["compressor_wall_seconds"]) or event["compressor_wall_seconds"] < 0:
            raise ValueError("Failed compressor timing is invalid")
    if process_complete and len(changed) != sum(event["changed"] for event in compressions):
        issues.append("changed_candidate_events_incomplete")
    for event in compressions:
        for name in ("compressor_wall_seconds", "serialization_wait_seconds", "adapter_execution_seconds"):
            if type(event.get(name)) not in (int, float) or not math.isfinite(event[name]) or event[name] < 0:
                raise ValueError("Compressor timing is invalid")
        worker = event.get("worker_inference_seconds")
        if worker is not None and (type(worker) not in (int, float) or not math.isfinite(worker) or worker < 0):
            raise ValueError("Worker inference timing is invalid")
    commands = command_metrics(trace, changed) if trace is not None else None
    if commands is None:
        issues.append("terminal_submission_trace_missing")
    else:
        issues.extend(commands["integrity_issues"])
    local_inputs = [event.get("local_input_tokens") for event in attempts]
    local_outputs = [event["local_output"]["content_tokens"] for event in responses if event.get("local_output") is not None]
    costs = [event["calculated_cost_usd"] for event in responses if event.get("calculated_cost_usd") is not None]
    return {
        "schema_version": 1, "kind": "calculated_from_recorded_native_and_transport_events",
        "trial_id": trial_id, "turns": turns,
        "turn_definition": "Harbor_recorded_agent_steps_not_HTTP_attempts_or_unfinished_steps",
        "turns_complete": process_complete and turns is not None and turns <= delivered,
        "delivered_responses_without_separate_agent_step": None if turns is None else delivered - turns,
        "logical_model_calls": sum(event.get("event") == "call_received" for event in selected),
        "total_model_calls": len(attempts), "call_unit": "provider_HTTP_attempts_including_retries",
        "http_retries": sum(event["attempt"] > 1 for event in attempts),
        "successful_http_responses": sum(event.get("status") == 200 for event in responses),
        "delivered_responses": delivered,
        "provider_tokens": {
            "kind": "provider_reported_usage_not_invoice_reconciliation", "unit": "tokens",
            **{name: value if not unknown else None for name, value in totals.items()},
            "reported_subtotal": totals, "unknown_usage_attempts": unknown,
            "cached_input_tokens": sum(cache_known) if len(cache_known) == len(attempts) else None,
            "cache_reported_subtotal": sum(cache_known), "cache_controlled": False,
        },
        "local_tokens": {
            "kind": "calculated", "tokenizer": "o200k_base", "unit": "tokens",
            "input_tokens": sum(local_inputs) if all(type(value) is int for value in local_inputs) else None,
            "output_tokens": sum(local_outputs) if len(local_outputs) == len(attempts) else None,
            "known_output_subtotal": sum(local_outputs),
            "input_scope": "message_content_per_sent_HTTP_attempt_not_API_framing",
            "output_scope": "visible_assistant_content_not_hidden_reasoning",
        },
        "commands": commands, "changed_candidate_occurrences": len(changed),
        "timing": phase_metrics(responses, compressions, compression_failures),
        "compressor": {
            "kind": "measured_from_live_adapter_events", "unit": "seconds",
            "calls": len(compressions) + len(compression_failures), "completed_calls": len(compressions),
            "failed_calls": len(compression_failures),
            "changed_occurrences": sum(event["changed"] for event in compressions),
            "wall_seconds": sum(event["compressor_wall_seconds"] for event in compressions + compression_failures),
            "completed_wall_seconds": sum(event["compressor_wall_seconds"] for event in compressions),
            "serialization_wait_seconds": sum(event["serialization_wait_seconds"] for event in compressions),
            "adapter_execution_seconds": sum(event["adapter_execution_seconds"] for event in compressions),
            "worker_inference_seconds": (
                sum(event["worker_inference_seconds"] for event in compressions)
                if compressions and all(event["worker_inference_seconds"] is not None for event in compressions)
                else None
            ),
            "known_worker_inference_seconds": sum(
                event["worker_inference_seconds"] for event in compressions
                if event["worker_inference_seconds"] is not None
            ),
            "worker_inference_calls": sum(event["worker_inference_seconds"] is not None for event in compressions),
        },
        "cost": {"kind": "provider_usage_times_ledger_rates_not_invoice", "unit": "USD",
                 "calculated_cost_usd": sum(costs) if len(costs) == len(attempts) else None,
                 "known_cost_subtotal_usd": sum(costs), "unknown_cost_attempts": len(attempts) - len(costs),
                 "invoice_reconciled": False},
        "truncation_causality": "not_established", "integrity_issues": issues,
        "measurement_complete": process_complete and not issues,
    }


def aggregate_run_compressor_metrics(trials: list[dict]) -> dict:
    rows = [trial["metrics"]["compressor"] for trial in trials]
    calls = sum(row["calls"] for row in rows)
    worker_calls = sum(row["worker_inference_calls"] for row in rows)
    return {
        "kind": "calculated_from_trial_compressor_metrics", "unit": "seconds",
        "trials": len(rows), "calls": calls,
        "completed_calls": sum(row["completed_calls"] for row in rows),
        "failed_calls": sum(row["failed_calls"] for row in rows),
        "changed_occurrences": sum(row["changed_occurrences"] for row in rows),
        "wall_seconds": sum(row["wall_seconds"] for row in rows),
        "completed_wall_seconds": sum(row["completed_wall_seconds"] for row in rows),
        "serialization_wait_seconds": sum(row["serialization_wait_seconds"] for row in rows),
        "adapter_execution_seconds": sum(row["adapter_execution_seconds"] for row in rows),
        "worker_inference_seconds": (
            sum(row["known_worker_inference_seconds"] for row in rows)
            if calls and worker_calls == calls else None
        ),
        "known_worker_inference_seconds": sum(row["known_worker_inference_seconds"] for row in rows),
        "worker_inference_calls": worker_calls,
    }


def aggregate_run_timing_metrics(trials: list[dict]) -> dict:
    rows = [trial["metrics"]["timing"] for trial in trials]
    attempts = sum(row["provider_http_attempts"] for row in rows)
    result = {
        "kind": "calculated_from_trial_phase_metrics", "unit": "seconds",
        "trials": len(rows), "provider_http_attempts": attempts,
        "compress_seconds": sum(row["compress_seconds"] for row in rows),
        "client_http_seconds": sum(row["client_http_seconds"] for row in rows),
        "transport_basis": "client_http_minus_provider_service_ttlt",
        "model_basis": "provider_usage_latency_checkpoint_engine_ttlt",
    }
    for name in ("transport_seconds", "model_seconds", "provider_service_seconds", "pre_inference_seconds"):
        call_field = "known_" + name.removesuffix("_seconds") + "_calls"
        known_field = "known_" + name
        known_calls = sum(row[call_field] for row in rows)
        result[name] = sum(row[known_field] for row in rows) if attempts and known_calls == attempts else None
        result[known_field] = sum(row[known_field] for row in rows)
        result[call_field] = known_calls
    return result


def read_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def collect_trial_metrics(job: Path, transport: Path, trial_id: str, *, process_complete: bool) -> dict:
    trajectories = list(job.glob("*/agent/trajectory.json"))
    traces = list(job.glob("*/agent/command-trace/events.jsonl"))
    artifacts = {}
    data = {}
    read_errors = []
    for name, paths in (("trajectory", trajectories), ("command_trace", traces)):
        if len(paths) != 1:
            data[name] = None
            continue
        path = paths[0]
        try:
            if not path.resolve().is_relative_to(job.resolve()):
                raise ValueError("Native metric artifact escapes its trial")
            content = path.read_bytes()
            artifacts[name] = {"path": path.relative_to(job).as_posix(), "sha256": digest(content)}
            data[name] = json.loads(content) if name == "trajectory" else read_events(path)
        except (OSError, ValueError):
            data[name] = None
            read_errors.append(name + "_unreadable_or_malformed")
    event_path = transport / "events.jsonl"
    try:
        events = read_events(event_path) if event_path.exists() else []
        metrics = trial_metrics(events, data["command_trace"], data["trajectory"], trial_id, process_complete=process_complete)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        metrics = trial_metrics([], None, None, trial_id, process_complete=False)
        read_errors.append("metric_evidence_invalid_requires_review")
    metrics["integrity_issues"].extend(read_errors)
    if read_errors:
        metrics["measurement_complete"] = False
    metrics["artifacts"] = artifacts
    return metrics
