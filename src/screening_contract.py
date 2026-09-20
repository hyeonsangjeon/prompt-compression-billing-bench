"""Validate the fixed Terminal-Bench 2.1 screening execution contract."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
import re
import tomllib

from .screening_inventory import REVISION
from .execution_safety import LIMIT_FIELDS, require_operational_safety, validate_safety_limits
from .runtime_limits import queue_fields, runtime_queue_limits, validate_queue_limits
from .verifier_revisions import VERIFIER_SPECS


FIXED_CONCURRENCY = 8
LEGACY_FIELDS = {
    "benchmark": {"name", "revision", "root_env", "inventory_env", "inventory_sha256", "task_count", "verifiers"},
    "model": {"provider", "name", "reported_model", "endpoint_env", "temperature", "reasoning_effort", "max_completion_tokens"},
    "runner": {"harbor_version", "agent_import_path", "environment_import_path", "concurrency", "max_turns", "agent_timeout_seconds", "verifier_timeout_seconds", "setup_timeout_seconds", "trial_timeout_seconds"},
    "measurement": {"tokenizer", "tiktoken_version", "cache_env", "table_sha256"},
    "queue": queue_fields(1),
    "retrieval": {"account_url_env", "spool_root_env", "container", "prefix", "upload_timeout_seconds", "maximum_attempts", "initial_backoff_seconds", "maximum_backoff_seconds", "final_flush_seconds"},
    "limits": {"api_cost_usd", "deadline_utc", "max_wall_seconds", "max_calls_per_trial", "request_timeout_seconds", "max_request_bytes", "max_attempts_per_call", "max_retry_wait_seconds", "protocol_token_allowance"},
    "prices": {"input_per_million_usd", "cached_input_per_million_usd", "output_per_million_usd", "source_reference", "checked_at_utc"},
    "screening": {"condition", "maximum_repetitions_per_task", "valid_results_required", "passes_required", "stop_after_quality_failures", "preparation_retry_maximum", "randomization_seed"},
    "replay": {"required", "bundle_revision", "require_complete_capture"},
    "cost": {
        "currency", "vm_hourly_usd", "vm_meter_reference", "vm_price_checked_at_utc", "allocation",
        "blob_and_network_contract", "blob_write_per_10000_operations_usd",
        "blob_read_per_10000_operations_usd", "same_region_network_per_gb_usd",
        "blob_network_meter_reference", "blob_network_price_checked_at_utc", "near_zero_usd",
    },
    "approval": {"preregistered", "execution_authorized", "reference"},
}

FIELDS = {
    "benchmark": {"name", "revision", "root_env", "inventory_env", "inventory_sha256", "task_count", "verifiers"},
    "model": {"provider", "name", "reported_model", "endpoint_env", "temperature", "reasoning_effort"},
    "runner": {"harbor_version", "agent_import_path", "environment_import_path", "concurrency"},
    "measurement": {"tokenizer", "tiktoken_version", "cache_env", "table_sha256"},
    "retrieval": {"account_url_env", "spool_root_env", "container", "prefix", "upload_timeout_seconds", "maximum_attempts", "initial_backoff_seconds", "maximum_backoff_seconds", "final_flush_seconds"},
    "limits": set(),
    "prices": {"input_per_million_usd", "cached_input_per_million_usd", "output_per_million_usd", "source_reference", "checked_at_utc"},
    "screening": {"condition", "maximum_repetitions_per_task", "valid_results_required", "passes_required", "stop_after_quality_failures", "preparation_retry_maximum", "randomization_seed"},
    "replay": {"required", "bundle_revision", "require_complete_capture"},
    "cost": {
        "currency", "vm_hourly_usd", "vm_meter_reference", "vm_price_checked_at_utc", "allocation",
        "blob_and_network_contract", "blob_write_per_10000_operations_usd",
        "blob_read_per_10000_operations_usd", "same_region_network_per_gb_usd",
        "blob_network_meter_reference", "blob_network_price_checked_at_utc", "near_zero_usd",
    },
    "approval": {"preregistered", "execution_authorized", "reference"},
}
LEGACY_UNBOUNDED_LIMIT_FIELDS = {
    "provider_cost_stop", "provider_call_stop", "request_size_stop",
    "provider_http_timeout", "run_deadline_stop", "transient_http_attempts",
    "reporting_target_utc",
}


def load_screening_ledger(path: Path) -> dict:
    value = tomllib.loads(path.read_text())
    validate_screening_ledger(value)
    return value


def _timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed


def validate_screening_ledger(ledger: dict) -> None:
    if ledger.get("schema_version") == 1:
        _validate_legacy_screening_ledger(ledger)
        return
    schema_version = ledger.get("schema_version")
    limit_fields = LIMIT_FIELDS if schema_version == 4 else LEGACY_UNBOUNDED_LIMIT_FIELDS
    approval_fields = FIELDS["approval"] | ({"cost_limits_approved"} if schema_version == 4 else set())
    fields = {**FIELDS, "limits": limit_fields, "approval": approval_fields, "queue": queue_fields(schema_version)}
    if set(ledger) != set(fields) | {"schema_version", "mode", "output_dir", "raw_retrieval"}:
        raise ValueError("Unexpected or missing screening ledger sections")
    for section, names in fields.items():
        if not isinstance(ledger[section], dict) or set(ledger[section]) != names:
            raise ValueError(f"Unexpected or missing [{section}] fields")
    if schema_version not in (2, 3, 4) or ledger["mode"] != "terminal_bench_screening":
        raise ValueError("Screening ledger schema or mode differs")
    if ledger["output_dir"] != "runs" or ledger["raw_retrieval"] != "not_exposed_to_agent":
        raise ValueError("Raw screening evidence must remain private and unavailable to the agent")
    benchmark = ledger["benchmark"]
    if benchmark["name"] != "terminal-bench-2.1" or benchmark["revision"] != REVISION or benchmark["task_count"] != 89:
        raise ValueError("Keep the fixed Terminal-Bench 2.1 revision and all 89 tasks")
    if benchmark["verifiers"] != VERIFIER_SPECS:
        raise ValueError("Keep the approved hash-bound verifier revision")
    if not re.fullmatch(r"[0-9a-f]{64}", benchmark["inventory_sha256"]):
        raise ValueError("A resolved screening inventory SHA-256 is required")
    for name in (benchmark["root_env"], benchmark["inventory_env"], ledger["model"]["endpoint_env"],
                 ledger["measurement"]["cache_env"], ledger["queue"]["state_path_env"],
                 ledger["retrieval"]["account_url_env"], ledger["retrieval"]["spool_root_env"]):
        if not isinstance(name, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
            raise ValueError("Runtime locations must be named through environment variables")
    model = ledger["model"]
    if model != {
        "provider": "foundry", "name": "gpt-5.4", "reported_model": "gpt-5.4-2026-03-05",
        "endpoint_env": "FOUNDRY_ENDPOINT", "temperature": 0, "reasoning_effort": "none",
    }:
        raise ValueError("Keep the fixed gpt-5.4 request settings and reported revision")
    runner = ledger["runner"]
    if runner["harbor_version"] != "0.22.0" or runner["agent_import_path"] != "src.harbor_agent:ObservedTerminus2":
        raise ValueError("Keep Harbor 0.22.0 and the observed Terminus 2 agent")
    if runner["environment_import_path"] != "src.replay_environment:PreservingDockerEnvironment":
        raise ValueError("Screening must preserve verifier-visible Docker state")
    if runner["concurrency"] != FIXED_CONCURRENCY:
        raise ValueError("Screening concurrency is fixed at eight")
    if ledger["measurement"] != {
        "tokenizer": "o200k_base", "tiktoken_version": "0.14.0", "cache_env": "TIKTOKEN_CACHE_DIR",
        "table_sha256": "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d",
    }:
        raise ValueError("Keep the fixed local token calculation contract")
    queue = ledger["queue"]
    validate_queue_limits(queue, schema_version)
    _timestamp(queue["limits_checked_at_utc"], "queue.limits_checked_at_utc")
    retrieval = ledger["retrieval"]
    if retrieval != {
        "account_url_env": "NATIVE_BLOB_ACCOUNT_URL", "spool_root_env": "NATIVE_BLOB_SPOOL_ROOT",
        "container": "runs", "prefix": "screening", "upload_timeout_seconds": 300,
        "maximum_attempts": 30, "initial_backoff_seconds": 2, "maximum_backoff_seconds": 60,
        "final_flush_seconds": 600,
    }:
        raise ValueError("Keep the local-first managed-identity Blob retrieval contract")
    screening = ledger["screening"]
    if screening != {
        "condition": "none", "maximum_repetitions_per_task": 20, "valid_results_required": 20,
        "passes_required": 18, "stop_after_quality_failures": 3, "preparation_retry_maximum": 1,
        "randomization_seed": 20260915,
    }:
        raise ValueError("Keep the fixed 18-of-20 screening rule and one preparation retry")
    if ledger["replay"] != {"required": True, "bundle_revision": 2, "require_complete_capture": True}:
        raise ValueError("Every valid screening result needs a complete replay bundle")
    limits = ledger["limits"]
    if schema_version == 4:
        validate_safety_limits(limits)
    elif limits != {
        "provider_cost_stop": "none", "provider_call_stop": "none",
        "request_size_stop": "provider_enforced_only", "provider_http_timeout": "none",
        "run_deadline_stop": "none", "transient_http_attempts": 3,
        "reporting_target_utc": "2026-09-16T14:59:00+00:00",
    }:
        raise ValueError("Keep the historical schema-v2/v3 no-harness-stop policy")
    for section, names in {
        "prices": ("input_per_million_usd", "cached_input_per_million_usd", "output_per_million_usd"),
        "cost": (
            "vm_hourly_usd", "blob_write_per_10000_operations_usd",
            "blob_read_per_10000_operations_usd", "same_region_network_per_gb_usd",
            "near_zero_usd",
        ),
    }.items():
        for name in names:
            value = ledger[section][name]
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{section}.{name} must be finite and nonnegative")
    if ledger["prices"]["cached_input_per_million_usd"] > ledger["prices"]["input_per_million_usd"]:
        raise ValueError("Cached input cannot cost more than full input")
    minimum_provider_unit = ledger["prices"]["cached_input_per_million_usd"] / 1_000_000
    if not math.isclose(ledger["cost"]["near_zero_usd"], minimum_provider_unit, rel_tol=0, abs_tol=1e-15):
        raise ValueError("Near-zero cost must equal the smallest fixed provider token charge")
    if ledger["cost"]["currency"] != "USD" or ledger["cost"]["allocation"] != "equal_share_of_each_active_time_segment":
        raise ValueError("Keep one currency and the predeclared active-VM allocation")
    if (
        not ledger["cost"]["blob_and_network_contract"].strip()
        or not ledger["cost"]["vm_meter_reference"].strip()
        or not ledger["cost"]["blob_network_meter_reference"].strip()
    ):
        raise ValueError("Direct infrastructure cost needs source references")
    _timestamp(ledger["cost"]["vm_price_checked_at_utc"], "cost.vm_price_checked_at_utc")
    _timestamp(
        ledger["cost"]["blob_network_price_checked_at_utc"],
        "cost.blob_network_price_checked_at_utc",
    )
    _timestamp(ledger["prices"]["checked_at_utc"], "prices.checked_at_utc")
    if not ledger["prices"]["source_reference"].strip():
        raise ValueError("Provider rates need a source reference")
    approval_booleans = ("preregistered", "execution_authorized") + (("cost_limits_approved",) if schema_version == 4 else ())
    for name in approval_booleans:
        if type(ledger["approval"][name]) is not bool:
            raise ValueError("Approval values must be booleans")


def require_operational_screening(ledger: dict) -> dict:
    if ledger.get("schema_version") != 4:
        raise ValueError("New provider execution requires the safety-capped schema-v4 ledger")
    if not ledger["approval"].get("preregistered") or not ledger["approval"].get("execution_authorized") or not ledger["approval"].get("cost_limits_approved") or not ledger["approval"]["reference"].strip():
        raise ValueError("Preregistration and delegated execution authorization must be recorded")
    policy = require_operational_safety(ledger)
    queue = ledger["queue"]
    if not queue["limits_source_reference"].strip() or not queue["deployment_isolation_reference"].strip():
        raise ValueError("Quota and shared-deployment coordination need evidence references")
    runtime_queue_limits(queue, ledger["schema_version"])
    if ledger["prices"]["input_per_million_usd"] <= 0 or ledger["prices"]["output_per_million_usd"] <= 0:
        raise ValueError("Verified rates are required to enforce and measure the cost ceilings")
    return policy


def _validate_legacy_screening_ledger(ledger: dict) -> None:
    if set(ledger) != set(LEGACY_FIELDS) | {"schema_version", "mode", "output_dir", "raw_retrieval"}:
        raise ValueError("Unexpected or missing legacy screening ledger sections")
    for section, names in LEGACY_FIELDS.items():
        if not isinstance(ledger[section], dict) or set(ledger[section]) != names:
            raise ValueError(f"Unexpected or missing legacy [{section}] fields")
    if ledger["mode"] != "terminal_bench_screening":
        raise ValueError("Legacy screening ledger mode differs")
    if ledger["benchmark"]["revision"] != REVISION or ledger["benchmark"]["verifiers"] != VERIFIER_SPECS:
        raise ValueError("Legacy screening benchmark or verifier differs")
    if ledger["model"] != {
        "provider": "foundry", "name": "gpt-5.4", "reported_model": "gpt-5.4-2026-03-05",
        "endpoint_env": "FOUNDRY_ENDPOINT", "temperature": 0, "reasoning_effort": "none",
        "max_completion_tokens": 2048,
    }:
        raise ValueError("Legacy screening model contract differs")
    if ledger["runner"]["harbor_version"] != "0.22.0" or ledger["runner"]["concurrency"] != FIXED_CONCURRENCY:
        raise ValueError("Legacy screening runner differs")
    validate_queue_limits(ledger["queue"], 1)
