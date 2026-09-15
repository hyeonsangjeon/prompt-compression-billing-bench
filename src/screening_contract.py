"""Validate the fixed Terminal-Bench 2.1 screening execution contract."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
import re
import tomllib

from .screening_inventory import REVISION
from .verifier_revisions import VERIFIER_SPECS


FIXED_CONCURRENCY = 8
FIXED_RPM = 3_000
FIXED_TPM = 300_000
FIELDS = {
    "benchmark": {"name", "revision", "root_env", "inventory_env", "inventory_sha256", "task_count", "verifiers"},
    "model": {"provider", "name", "reported_model", "endpoint_env", "temperature", "reasoning_effort", "max_completion_tokens"},
    "runner": {"harbor_version", "agent_import_path", "environment_import_path", "concurrency", "max_turns", "agent_timeout_seconds", "verifier_timeout_seconds", "setup_timeout_seconds", "trial_timeout_seconds"},
    "measurement": {"tokenizer", "tiktoken_version", "cache_env", "table_sha256"},
    "queue": {"state_path_env", "rpm", "tpm", "limits_checked_at_utc", "limits_source_reference", "deployment_isolation_reference"},
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
    if set(ledger) != set(FIELDS) | {"schema_version", "mode", "output_dir", "raw_retrieval"}:
        raise ValueError("Unexpected or missing screening ledger sections")
    for section, names in FIELDS.items():
        if not isinstance(ledger[section], dict) or set(ledger[section]) != names:
            raise ValueError(f"Unexpected or missing [{section}] fields")
    if ledger["schema_version"] != 1 or ledger["mode"] != "terminal_bench_screening":
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
        "max_completion_tokens": 2048,
    }:
        raise ValueError("Keep the fixed gpt-5.4 request settings and reported revision")
    runner = ledger["runner"]
    if runner["harbor_version"] != "0.22.0" or runner["agent_import_path"] != "src.harbor_agent:ObservedTerminus2":
        raise ValueError("Keep Harbor 0.22.0 and the observed Terminus 2 agent")
    if runner["environment_import_path"] != "src.replay_environment:PreservingDockerEnvironment":
        raise ValueError("Screening must preserve verifier-visible Docker state")
    if runner["concurrency"] != FIXED_CONCURRENCY:
        raise ValueError("Screening concurrency is fixed at eight")
    for name in ("max_turns", "agent_timeout_seconds", "verifier_timeout_seconds", "setup_timeout_seconds", "trial_timeout_seconds"):
        if type(runner[name]) is not int or runner[name] < 1:
            raise ValueError(f"runner.{name} must be a positive integer")
    if ledger["measurement"] != {
        "tokenizer": "o200k_base", "tiktoken_version": "0.14.0", "cache_env": "TIKTOKEN_CACHE_DIR",
        "table_sha256": "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d",
    }:
        raise ValueError("Keep the fixed local token calculation contract")
    queue = ledger["queue"]
    if (queue["rpm"], queue["tpm"]) != (FIXED_RPM, FIXED_TPM):
        raise ValueError("Keep the checked 3000 RPM and 300000 TPM limits")
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
    for name in ("max_wall_seconds", "max_calls_per_trial", "request_timeout_seconds", "max_request_bytes",
                 "max_attempts_per_call", "max_retry_wait_seconds", "protocol_token_allowance"):
        if type(limits[name]) is not int or limits[name] < 1:
            raise ValueError(f"limits.{name} must be a positive integer")
    for section, names in {
        "limits": ("api_cost_usd",),
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
    for name in ("preregistered", "execution_authorized"):
        if type(ledger["approval"][name]) is not bool:
            raise ValueError("Approval values must be booleans")


def require_operational_screening(ledger: dict) -> float:
    if not ledger["approval"]["preregistered"] or not ledger["approval"]["execution_authorized"] or not ledger["approval"]["reference"].strip():
        raise ValueError("Preregistration and delegated execution authorization must be recorded")
    queue = ledger["queue"]
    if not queue["limits_source_reference"].strip() or not queue["deployment_isolation_reference"].strip():
        raise ValueError("Quota and shared-deployment coordination need evidence references")
    if ledger["limits"]["api_cost_usd"] <= 0 or ledger["prices"]["input_per_million_usd"] <= 0 or ledger["prices"]["output_per_million_usd"] <= 0:
        raise ValueError("A positive provider budget ceiling and verified rates are required")
    deadline = _timestamp(ledger["limits"]["deadline_utc"], "limits.deadline_utc")
    if deadline <= datetime.now(timezone.utc):
        raise ValueError("The screening deadline has passed")
    return deadline.timestamp()
