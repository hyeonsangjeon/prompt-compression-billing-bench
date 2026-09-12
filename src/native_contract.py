"""Validate the fixed five-task native design before any provider access."""

from datetime import datetime, timezone
import math
from pathlib import Path
import re
import tomllib

from .baseline import RULE


TASKS = ("cancel-async-tasks", "log-summary-date-ranges", "multi-source-data-merger",
         "nginx-request-logging", "openssl-selfsigned-cert")
REVISION = "7131e4375048a0e408a8fb404b5f499d726b695b"
FIXED_CONCURRENCY = 8
FIXED_RPM = 3_000
FIXED_TPM = 300_000
FIELDS = {
    "benchmark": {"name", "revision", "root_env", "tasks", "images"},
    "model": {"provider", "name", "reported_model", "endpoint_env", "temperature", "reasoning_effort", "max_completion_tokens"},
    "runner": {"harbor_version", "agent_import_path", "concurrency", "max_turns", "agent_timeout_seconds", "verifier_timeout_seconds", "setup_timeout_seconds", "trial_timeout_seconds"},
    "measurement": {"tokenizer", "tiktoken_version", "cache_env", "table_sha256"},
    "compressor": {"name", "target", "tools"},
    "queue": {"state_path_env", "rpm", "tpm", "limits_checked_at_utc", "limits_source_reference", "deployment_isolation_reference"},
    "limits": {"api_cost_usd", "deadline_utc", "max_wall_seconds", "max_calls_per_trial", "request_timeout_seconds", "max_request_bytes", "max_attempts_per_call", "max_retry_wait_seconds", "protocol_token_allowance"},
    "prices": {"input_per_million_usd", "cached_input_per_million_usd", "output_per_million_usd", "source_reference", "checked_at_utc"},
    "stability": {"rule", "minimum_repetitions", "maximum_repetitions", "comparison_repetitions"},
    "approval": {"execution_approved", "rule_accepted", "reference"},
}


def load_native_ledger(path: Path) -> dict:
    ledger = tomllib.loads(path.read_text())
    validate_native_ledger(ledger)
    return ledger


def validate_native_ledger(ledger: dict) -> None:
    if not isinstance(ledger, dict) or set(ledger) != set(FIELDS) | {"schema_version", "mode", "conditions", "output_dir", "raw_retrieval"}:
        raise ValueError("Unexpected or missing native ledger fields")
    for section, fields in FIELDS.items():
        if not isinstance(ledger[section], dict) or set(ledger[section]) != fields:
            raise ValueError(f"Unexpected or missing [{section}] fields")
    if type(ledger["schema_version"]) is not int or ledger["schema_version"] != 1 or ledger["mode"] != "native_log_truncation" or ledger["conditions"] != ["none", "squeez"]:
        raise ValueError("Only native none then squeez is supported; no deletion arm")
    if ledger["output_dir"] != "runs":
        raise ValueError("Native raw artifacts must stay under the private runs directory")
    for section, fields in {
        "model": {"reported_model"}, "queue": {"limits_checked_at_utc", "limits_source_reference", "deployment_isolation_reference"},
        "prices": {"source_reference", "checked_at_utc"}, "approval": {"reference"},
        "limits": {"deadline_utc"},
    }.items():
        if any(not isinstance(ledger[section][field], str) for field in fields):
            raise ValueError(f"[{section}] reference and timestamp fields must be text")
    if ledger["raw_retrieval"] != "not_exposed_to_agent":
        raise ValueError("Adding a retrieval tool changes the fixed intervention")
    benchmark, model, runner = ledger["benchmark"], ledger["model"], ledger["runner"]
    if benchmark["name"] != "terminal-bench-2.1" or benchmark["revision"] != REVISION or benchmark["tasks"] != list(TASKS):
        raise ValueError("Keep the selected five Terminal tasks and their pinned revision")
    if not isinstance(benchmark["images"], dict) or set(benchmark["images"]) != set(TASKS) or any(
        not isinstance(image, str) or not re.fullmatch(r"[a-z0-9_./-]+@sha256:[0-9a-f]{64}", image)
        for image in benchmark["images"].values()
    ):
        raise ValueError("Every task image needs an immutable digest")
    if model["provider"] != "foundry" or model["name"] != "gpt-5.4" or not re.fullmatch(r"gpt-5\.4-\d{4}-\d{2}-\d{2}", model["reported_model"]):
        raise ValueError("Pin the requested gpt-5.4 provider-reported snapshot")
    if type(model["temperature"]) not in (float, int) or model["temperature"] != 0 or model["reasoning_effort"] != "none":
        raise ValueError("Record temperature 0 and effort none; neither implies determinism")
    if runner["harbor_version"] != "0.22.0" or runner["agent_import_path"] != "src.harbor_agent:ObservedTerminus2":
        raise ValueError("Use the pinned, instrumented Terminus 2 adapter")
    if runner["concurrency"] != FIXED_CONCURRENCY:
        raise ValueError("Native trial concurrency is fixed at eight for every comparison arm")
    for value in (benchmark["root_env"], model["endpoint_env"], ledger["queue"]["state_path_env"], ledger["measurement"]["cache_env"]):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", value):
            raise ValueError("Store environment variable names, not credentials")
    for section, fields in {
        "runner": FIELDS["runner"] - {"harbor_version", "agent_import_path"},
        "model": {"max_completion_tokens"},
        "limits": FIELDS["limits"] - {"api_cost_usd", "deadline_utc"},
    }.items():
        for field in fields:
            if type(ledger[section][field]) is not int or ledger[section][field] < 1:
                raise ValueError(f"{section}.{field} must be a positive integer")
    for section, fields in {"queue": {"rpm", "tpm"}, "prices": FIELDS["prices"] - {"source_reference", "checked_at_utc"}, "limits": {"api_cost_usd"}}.items():
        for field in fields:
            value = ledger[section][field]
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{section}.{field} must be nonnegative and finite")
    if any(type(ledger["queue"][field]) is not int for field in ("rpm", "tpm")):
        raise ValueError("RPM and TPM must be integers")
    if (ledger["queue"]["rpm"], ledger["queue"]["tpm"]) != (FIXED_RPM, FIXED_TPM):
        raise ValueError("Keep the verified deployment limits fixed at 3000 RPM and 300000 TPM")
    checked_at = datetime.fromisoformat(ledger["queue"]["limits_checked_at_utc"])
    if checked_at.tzinfo is None or checked_at > datetime.now(timezone.utc) or not ledger["queue"]["limits_source_reference"].strip():
        raise ValueError("Deployment limits need a past timezone-aware check and source")
    if ledger["prices"]["cached_input_per_million_usd"] > ledger["prices"]["input_per_million_usd"]:
        raise ValueError("Cached input rate exceeds the full input rate")
    if ledger["stability"] != {"rule": RULE, "minimum_repetitions": 10, "maximum_repetitions": 20, "comparison_repetitions": "match_baseline"}:
        raise ValueError("Baseline stopping and comparison rules must be fixed before collection")
    if any(type(ledger["approval"][field]) is not bool for field in ("execution_approved", "rule_accepted")):
        raise ValueError("Approval fields must be explicit booleans")
    compressor = ledger["compressor"]
    if compressor["name"] != "squeez" or compressor["target"] != "identified_log_spans" or not isinstance(compressor["tools"], dict) or set(compressor["tools"]) != {"none", "squeez"}:
        raise ValueError("Both arms must use the same compressor interface and candidate policy")
    fixed = compressor["tools"]["squeez"]
    if not isinstance(fixed, dict) or set(fixed) != {"version", "binary_env", "sha256", "options"} or fixed["version"] != "1.48.4" or fixed["sha256"] != "ef956365ace3aa5f362847afc000aa008d5b4a26db4ee2c5bcc0d2718d043773":
        raise ValueError("Keep the audited squeez binary")
    if not isinstance(fixed["binary_env"], str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", fixed["binary_env"]):
        raise ValueError("Use an environment name for the reviewed squeez binary")
    if fixed["options"] != {"invocation": "wrap_cat_input_txt", "state": "fresh_home_per_span", "timeout_seconds": 10, "output": "complete_stdout"}:
        raise ValueError("Changing squeez strength or hiding its metadata changes the intervention")
    if compressor["tools"]["none"] != {"version": "unavailable", "options": {}}:
        raise ValueError("The baseline is the no-op compressor")


def require_operational_values(ledger: dict) -> float:
    if not all(ledger["approval"][field] for field in ("execution_approved", "rule_accepted")) or not ledger["approval"]["reference"].strip():
        raise ValueError("Baseline execution and the predeclared rule require explicit approval")
    queue, prices = ledger["queue"], ledger["prices"]
    if not queue["rpm"] or not queue["tpm"] or not queue["deployment_isolation_reference"].strip():
        raise ValueError("Verify deployment quotas and coordination with other callers")
    if not ledger["limits"]["api_cost_usd"] or not prices["input_per_million_usd"] or not prices["output_per_million_usd"] or not prices["source_reference"].strip():
        raise ValueError("Provide the remaining budget and verified rates, not example zeros")
    deadline = datetime.fromisoformat(ledger["limits"]["deadline_utc"])
    checked_at = datetime.fromisoformat(prices["checked_at_utc"])
    if deadline.utcoffset() is None or deadline.utcoffset().total_seconds() != 0 or checked_at.tzinfo is None:
        raise ValueError("Use an explicit UTC deadline and timezone-aware rate-check timestamp")
    if deadline <= datetime.now(timezone.utc) or checked_at > datetime.now(timezone.utc):
        raise ValueError("Deadline expired or rate-check timestamp is in the future")
    return deadline.timestamp()
