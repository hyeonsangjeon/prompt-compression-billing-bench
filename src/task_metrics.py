"""Per-native-trial calls, turns, token units and observed command repetitions."""

from collections import Counter
from datetime import datetime
import json
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
        "cost": {"kind": "provider_usage_times_ledger_rates_not_invoice", "unit": "USD",
                 "calculated_cost_usd": sum(costs) if len(costs) == len(attempts) else None,
                 "known_cost_subtotal_usd": sum(costs), "unknown_cost_attempts": len(attempts) - len(costs),
                 "invoice_reconciled": False},
        "truncation_causality": "not_established", "integrity_issues": issues,
        "measurement_complete": process_complete and not issues,
    }


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
