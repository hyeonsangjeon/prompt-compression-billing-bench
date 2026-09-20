"""Validate and describe mandatory safety limits for future provider execution."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math

from .protection import digest


SCHEMA_VERSION = 4
POLICY_REVISION = 1
LIMIT_FIELDS = {
    "policy_revision",
    "max_provider_calls_per_attempt",
    "max_api_cost_usd_per_attempt",
    "max_api_cost_usd_per_run",
    "max_wall_seconds_per_attempt",
    "run_deadline_utc",
    "max_request_bytes",
    "max_output_tokens",
    "protocol_token_allowance",
    "provider_http_timeout_seconds",
    "max_retry_wait_seconds",
    "transient_http_attempts",
    "no_progress_window_calls",
    "no_progress_minimum_distinct_signals",
    "natural_termination_observation",
}
FIXED_LIMITS = {
    "policy_revision": POLICY_REVISION,
    "max_provider_calls_per_attempt": 60,
    "max_wall_seconds_per_attempt": 2400,
    "max_request_bytes": 8_000_000,
    "max_output_tokens": 2048,
    "protocol_token_allowance": 4096,
    "provider_http_timeout_seconds": 300,
    "max_retry_wait_seconds": 120,
    "transient_http_attempts": 3,
    "no_progress_window_calls": 8,
    "no_progress_minimum_distinct_signals": 3,
    "natural_termination_observation": "separate_pilot_only",
}
COST_FIELDS = ("max_api_cost_usd_per_attempt", "max_api_cost_usd_per_run")


class SafetyLimitReached(RuntimeError):
    """A predeclared safety boundary stopped an attempt or the whole run."""

    def __init__(
        self,
        limit_name: str,
        scope: str,
        applied_limit: int | float | str,
        observed: int | float | str,
        *,
        trial_id: str | None = None,
        stop_kind: str = "budget_stopped",
    ):
        if scope not in ("attempt", "run") or stop_kind not in ("budget_stopped", "censored"):
            raise ValueError("Safety stop scope or kind is invalid")
        super().__init__(f"Safety limit reached: {limit_name}")
        self.run_wide = scope == "run"
        self.details = {
            "classification": "technical_incomplete",
            "quality_status": "unknown",
            "stop_kind": stop_kind,
            "censoring": "right_censored",
            "limit_name": limit_name,
            "scope": scope,
            "applied_limit": applied_limit,
            "observed": observed,
            "trial_id": trial_id,
        }


def _finite_nonnegative(value: object, label: str) -> float:
    if (
        type(value) not in (int, float)
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{label} must be a finite nonnegative number")
    return float(value)


def _deadline(value: str, *, allow_blank: bool) -> datetime | None:
    if value == "" and allow_blank:
        return None
    if not isinstance(value, str):
        raise ValueError("limits.run_deadline_utc must be text")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("limits.run_deadline_utc must be an ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("limits.run_deadline_utc must use an explicit UTC offset")
    return parsed


def validate_safety_limits(limits: dict) -> None:
    if not isinstance(limits, dict) or set(limits) != LIMIT_FIELDS:
        raise ValueError("Unexpected or missing schema-v4 safety limit fields")
    for name, expected in FIXED_LIMITS.items():
        if limits[name] != expected:
            raise ValueError(f"Keep the fixed schema-v4 safety setting: {name}")
    per_attempt = _finite_nonnegative(
        limits["max_api_cost_usd_per_attempt"],
        "limits.max_api_cost_usd_per_attempt",
    )
    whole_run = _finite_nonnegative(
        limits["max_api_cost_usd_per_run"],
        "limits.max_api_cost_usd_per_run",
    )
    unresolved = per_attempt == 0 and whole_run == 0 and limits["run_deadline_utc"] == ""
    resolved = per_attempt > 0 and whole_run >= per_attempt and limits["run_deadline_utc"] != ""
    if not (unresolved or resolved):
        raise ValueError("Cost ceilings and the UTC deadline must be all unresolved or all operational")
    _deadline(limits["run_deadline_utc"], allow_blank=True)


def require_operational_safety(ledger: dict, *, current_time: datetime | None = None) -> dict:
    if ledger.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("New provider execution requires the safety-capped schema-v4 ledger")
    limits = ledger["limits"]
    validate_safety_limits(limits)
    if any(limits[name] <= 0 for name in COST_FIELDS):
        raise ValueError("Approved positive API cost ceilings are required before provider execution")
    deadline = _deadline(limits["run_deadline_utc"], allow_blank=False)
    now = current_time or datetime.now(timezone.utc)
    if deadline <= now:
        raise ValueError("The approved run deadline must still be in the future")
    return safety_policy_record(ledger, applied=True)


def safety_policy_record(ledger: dict, *, applied: bool) -> dict:
    limits = ledger["limits"]
    validate_safety_limits(limits)
    operational = all(limits[name] > 0 for name in COST_FIELDS) and bool(limits["run_deadline_utc"])
    if applied and not operational:
        raise ValueError("An applied safety policy needs approved cost ceilings and a deadline")
    return {
        "schema_version": 1,
        "kind": "provider_execution_safety_policy",
        "policy_revision": limits["policy_revision"],
        "status": "applied" if applied else "template_unapproved",
        "limits": {
            "provider_http_attempts_per_attempt": limits["max_provider_calls_per_attempt"],
            "api_calculated_cost_usd_per_attempt": (
                limits["max_api_cost_usd_per_attempt"] if applied else None
            ),
            "api_calculated_cost_usd_per_run": (
                limits["max_api_cost_usd_per_run"] if applied else None
            ),
            "attempt_wall_seconds": limits["max_wall_seconds_per_attempt"],
            "run_deadline_utc": limits["run_deadline_utc"] if applied else None,
            "request_bytes": limits["max_request_bytes"],
            "output_tokens": limits["max_output_tokens"],
            "protocol_token_allowance": limits["protocol_token_allowance"],
            "provider_http_timeout_seconds": limits["provider_http_timeout_seconds"],
            "maximum_retry_wait_seconds": limits["max_retry_wait_seconds"],
            "transient_http_attempts": limits["transient_http_attempts"],
        },
        "no_progress": {
            "window_logical_requests": limits["no_progress_window_calls"],
            "minimum_distinct_signals": limits["no_progress_minimum_distinct_signals"],
            "signal": "latest_assistant_command_plan_and_following_user_observation_sha256",
            "missing_signal": "fixed_missing_signal_marker",
        },
        "cost_accounting": {
            "basis": "provider_usage_times_ledger_rates_not_invoice",
            "pre_dispatch_reservation": "uncached_input_plus_output_cap",
            "unknown_cost": "retained_as_unconfirmed_exposure_not_zero",
        },
        "natural_termination": {
            "comparison_setting": limits["natural_termination_observation"],
            "requires_separate_pilot": True,
            "pilot_requires_preapproved_cost": True,
            "pilot_requires_maximum_exposure": True,
            "pilot_requires_manual_kill_condition": True,
            "pilot_execution_available": False,
        },
        "stop_classification": {
            "outcome": "technical_incomplete",
            "quality_status": "unknown",
            "allowed_stop_kinds": ["budget_stopped", "censored"],
            "wrong_answer_allowed": False,
        },
    }


def effective_deadline_epoch(policy: dict) -> float:
    value = policy["limits"]["run_deadline_utc"]
    if value is None:
        raise ValueError("An applied safety policy needs a run deadline")
    return datetime.fromisoformat(value).timestamp()


def progress_signal(payload: dict) -> str:
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list):
        return digest(b"fixed_missing_progress_signal")
    for user_index in range(len(messages) - 1, -1, -1):
        user = messages[user_index]
        if not isinstance(user, dict) or user.get("role") != "user" or not isinstance(user.get("content"), str):
            continue
        for assistant_index in range(user_index - 1, -1, -1):
            assistant = messages[assistant_index]
            if (
                isinstance(assistant, dict)
                and assistant.get("role") == "assistant"
                and isinstance(assistant.get("content"), str)
            ):
                content = assistant["content"]
                command_plan: object = {"assistant_sha256": digest(content.encode())}
                try:
                    parsed = json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    parsed = None
                if isinstance(parsed, dict):
                    commands = parsed.get("commands")
                    if isinstance(commands, list) and all(
                        isinstance(command, dict) and isinstance(command.get("keystrokes"), str)
                        for command in commands
                    ):
                        command_plan = {
                            "commands": [command["keystrokes"] for command in commands],
                            "task_complete": parsed.get("task_complete"),
                        }
                signal = {
                    "command_plan": command_plan,
                    "following_user_observation_sha256": digest(user["content"].encode()),
                }
                return digest(json.dumps(signal, sort_keys=True, separators=(",", ":")).encode())
    return digest(b"fixed_missing_progress_signal")


def safety_failure(failure: dict | None) -> dict | None:
    if not isinstance(failure, dict) or failure.get("reason") != "SafetyLimitReached":
        return None
    details = failure.get("details")
    if not isinstance(details, dict) or details.get("classification") != "technical_incomplete":
        return None
    return details
