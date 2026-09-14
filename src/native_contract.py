"""Validate the fixed five-task native design before any provider access."""

from datetime import datetime, timezone
import math
from pathlib import Path
import re
import tomllib

from .baseline import INTERIM_MAX_RANGE_WIDTH, INTERIM_REPETITIONS, RULE
from .verifier_revisions import VERIFIER_SPECS


TASKS = ("cancel-async-tasks", "log-summary-date-ranges", "multi-source-data-merger",
         "nginx-request-logging", "openssl-selfsigned-cert")
REVISION = "7131e4375048a0e408a8fb404b5f499d726b695b"
FIXED_CONCURRENCY = 8
FIXED_RPM = 3_000
FIXED_TPM = 300_000
CONDITIONS = ("none", "squeez", "headroom", "llmlingua2")
LLMLINGUA_MODEL_FILES = {
    "config.json": {"bytes": 752, "sha256": "a3fdcf4e63057797101ecc84412bc654f9adb4e8d4ed3c91c5afb28eda327706"},
    "model.safetensors": {"bytes": 2_235_829_648, "sha256": "a33a153b2493bff6be06af6921e69de9c0d0bb6ff06fe5bbb68670ba8d980ae2"},
    "special_tokens_map.json": {"bytes": 280, "sha256": "06e405a36dfe4b9604f484f6a1e619af1a7f7d09e34a8555eb0b77b66318067f"},
    "tokenizer.json": {"bytes": 17_082_756, "sha256": "f59925fcb90c92b894cb93e51bb9b4a6105c5c249fe54ce1c704420ac39b81af"},
    "tokenizer_config.json": {"bytes": 1_147, "sha256": "f90024142df07163e5e6c5b9a6ad7c8c68b22a9112af11e3db4559a9ff90f737"},
}
LLMLINGUA_TOKENIZER_FILES = {
    "9b5ad71b2ce5302211f9c61530b329a4922fc6a4": {"bytes": 1_681_126, "sha256": "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"},
    "fb374d419588a4632f3f557e76b4b70aebbca790": {"bytes": 3_613_922, "sha256": "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"},
}
LLMLINGUA_FIXTURES = [
    {"name": "path-listing", "path": "fixtures/llmlingua2/path-listing.txt",
     "input_sha256": "1509c8ab2413d1a8f204073c2b94f36401957808a800527951e2f8a6f2cfa0e4",
     "output_sha256": "5584b5ad36b4a36db45bb35a5659154fdafae5559f67248465b3dff6e5297423"},
    {"name": "severity-log", "path": "fixtures/llmlingua2/severity-log.txt",
     "input_sha256": "e6f48a8035541a288112807cf169480f41e163a041d94af8eba0aff20dd73e30",
     "output_sha256": "e0edacae128c56ec95b20d1e427f115e98067ce31e3ccb19a656e6a7ec53961d"},
    {"name": "package-install", "path": "fixtures/llmlingua2/package-install.txt",
     "input_sha256": "bcb77fccee038963729d58991a2cff44f7f35d705f3f39e88ed8369a9ca0cda5",
     "output_sha256": "d6d647b8efdd766ec081da2376d37526db7effffdba1843e2b6e3a1cb69b458c"},
]
FIELDS = {
    "benchmark": {"name", "revision", "root_env", "tasks", "images", "verifiers"},
    "model": {"provider", "name", "reported_model", "endpoint_env", "temperature", "reasoning_effort", "max_completion_tokens"},
    "runner": {"harbor_version", "agent_import_path", "concurrency", "max_turns", "agent_timeout_seconds", "verifier_timeout_seconds", "setup_timeout_seconds", "trial_timeout_seconds"},
    "measurement": {"tokenizer", "tiktoken_version", "cache_env", "table_sha256"},
    "compressor": {"name", "target", "tools"},
    "queue": {"state_path_env", "rpm", "tpm", "limits_checked_at_utc", "limits_source_reference", "deployment_isolation_reference"},
    "retrieval": {"account_url_env", "spool_root_env", "container", "prefix", "upload_timeout_seconds", "maximum_attempts", "initial_backoff_seconds", "maximum_backoff_seconds", "final_flush_seconds"},
    "limits": {"api_cost_usd", "deadline_utc", "max_wall_seconds", "max_calls_per_trial", "request_timeout_seconds", "max_request_bytes", "max_attempts_per_call", "max_retry_wait_seconds", "protocol_token_allowance"},
    "prices": {"input_per_million_usd", "cached_input_per_million_usd", "output_per_million_usd", "source_reference", "checked_at_utc"},
    "stability": {"rule", "interim_repetitions", "interim_max_range_width", "minimum_repetitions", "maximum_repetitions", "comparison_repetitions"},
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
    if type(ledger["schema_version"]) is not int or ledger["schema_version"] != 1 or ledger["mode"] != "native_candidate_compression" or ledger["conditions"] != list(CONDITIONS):
        raise ValueError("Keep the fixed none, squeez, Headroom and LLMLingua-2 comparison")
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
    if benchmark["verifiers"] != VERIFIER_SPECS:
        raise ValueError("Keep the approved hash-bound benchmark verifier revisions")
    if model["provider"] != "foundry" or model["name"] != "gpt-5.4" or not re.fullmatch(r"gpt-5\.4-\d{4}-\d{2}-\d{2}", model["reported_model"]):
        raise ValueError("Pin the requested gpt-5.4 provider-reported snapshot")
    if type(model["temperature"]) not in (float, int) or model["temperature"] != 0 or model["reasoning_effort"] != "none":
        raise ValueError("Record temperature 0 and effort none; neither implies determinism")
    if runner["harbor_version"] != "0.22.0" or runner["agent_import_path"] != "src.harbor_agent:ObservedTerminus2":
        raise ValueError("Use the pinned, instrumented Terminus 2 adapter")
    if runner["concurrency"] != FIXED_CONCURRENCY:
        raise ValueError("Native trial concurrency is fixed at eight for every comparison arm")
    for value in (
        benchmark["root_env"], model["endpoint_env"], ledger["queue"]["state_path_env"],
        ledger["measurement"]["cache_env"], ledger["retrieval"]["account_url_env"],
        ledger["retrieval"]["spool_root_env"],
    ):
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
    retrieval = ledger["retrieval"]
    if retrieval != {
        "account_url_env": "NATIVE_BLOB_ACCOUNT_URL", "spool_root_env": "NATIVE_BLOB_SPOOL_ROOT",
        "container": "runs", "prefix": "runs", "upload_timeout_seconds": 300,
        "maximum_attempts": 30, "initial_backoff_seconds": 2,
        "maximum_backoff_seconds": 60, "final_flush_seconds": 600,
    }:
        raise ValueError("Keep the managed-identity Blob spool and bounded retry contract")
    if ledger["stability"] != {
        "rule": RULE, "interim_repetitions": INTERIM_REPETITIONS,
        "interim_max_range_width": INTERIM_MAX_RANGE_WIDTH,
        "minimum_repetitions": 10, "maximum_repetitions": 20,
        "comparison_repetitions": "match_baseline",
    }:
        raise ValueError("Baseline stopping and comparison rules must be fixed before collection")
    if any(type(ledger["approval"][field]) is not bool for field in ("execution_approved", "rule_accepted")):
        raise ValueError("Approval fields must be explicit booleans")
    compressor = ledger["compressor"]
    if compressor["name"] != "selected_by_condition" or compressor["target"] != "identified_log_spans" or not isinstance(compressor["tools"], dict) or set(compressor["tools"]) != set(CONDITIONS):
        raise ValueError("Every arm must use the same compressor interface and candidate policy")
    fixed = compressor["tools"]["squeez"]
    if not isinstance(fixed, dict) or set(fixed) != {"version", "binary_env", "sha256", "options"} or fixed["version"] != "1.48.4" or fixed["sha256"] != "ef956365ace3aa5f362847afc000aa008d5b4a26db4ee2c5bcc0d2718d043773":
        raise ValueError("Keep the audited squeez binary")
    if not isinstance(fixed["binary_env"], str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", fixed["binary_env"]):
        raise ValueError("Use an environment name for the reviewed squeez binary")
    if fixed["options"] != {"invocation": "wrap_cat_input_txt", "state": "fresh_home_per_span", "timeout_seconds": 10, "output": "complete_stdout"}:
        raise ValueError("Changing squeez strength or hiding its metadata changes the intervention")
    if compressor["tools"]["none"] != {"version": "unavailable", "options": {}}:
        raise ValueError("The baseline is the no-op compressor")
    headroom = compressor["tools"]["headroom"]
    if not isinstance(headroom, dict) or set(headroom) != {"version", "module_env", "module_sha256", "wheel_sha256", "options"}:
        raise ValueError("Unexpected Headroom specification")
    if headroom != {
        "version": "0.36.5", "module_env": "HEADROOM_LOSSLESS_MODULE",
        "module_sha256": "a97f1801a610ebcff4201600e3453634d118db57a8a36183bfe1918d98d67d60",
        "wheel_sha256": "56954b76cd10b5312061725e7470575598a4bde3fa7f80f77d82a08a71fceae8",
        "options": {"profile_revision": 2, "allowed_kind": "paths", "inverse": "path_unheading",
                    "selection": "smaller_utf8_exact_inverse_no_fewer_display_lines",
                    "scope": "restricted_unmodified_helper_not_default_pipeline"},
    }:
        raise ValueError("Keep the reviewed Headroom paths-only profile")
    llmlingua = compressor["tools"]["llmlingua2"]
    if not isinstance(llmlingua, dict) or set(llmlingua) != {
        "version", "python_env", "python_version", "worker_path", "worker_sha256", "requirements_path",
        "requirements_sha256", "model_env", "model_id", "model_revision", "tokenizer_cache_env",
        "options", "model_files", "tokenizer_cache_files", "fixtures",
    }:
        raise ValueError("Unexpected LLMLingua-2 specification")
    if {
        key: llmlingua[key] for key in (
            "version", "python_env", "python_version", "worker_path", "worker_sha256", "requirements_path",
            "requirements_sha256", "model_env", "model_id", "model_revision", "tokenizer_cache_env",
        )
    } != {
        "version": "0.2.2", "python_env": "LLMLINGUA_PYTHON", "python_version": "3.10.12",
        "worker_path": "src/llmlingua_worker.py",
        "worker_sha256": "81ec78d1d9a5c9c6c1b62277bf9abed11588f101672eef2816c61708813635db",
        "requirements_path": "requirements/llmlingua2-cpu.txt",
        "requirements_sha256": "ab865e99ec5d846dc87537ca9d35011b93461f48e9cd01b551a2425a5da7816f",
        "model_env": "LLMLINGUA_MODEL",
        "model_id": "microsoft/llmlingua-2-xlm-roberta-large-meetingbank",
        "model_revision": "ebaba9b0e874dadd3003ffcff828e4397e568089",
        "tokenizer_cache_env": ledger["measurement"]["cache_env"],
    }:
        raise ValueError("Keep the reviewed LLMLingua-2 runtime and model revision")
    if llmlingua["model_files"] != LLMLINGUA_MODEL_FILES or llmlingua["tokenizer_cache_files"] != LLMLINGUA_TOKENIZER_FILES or llmlingua["fixtures"] != LLMLINGUA_FIXTURES:
        raise ValueError("Keep the pinned LLMLingua model, tokenizer and determinism fixtures")
    if llmlingua["options"] != {
        "method": "PromptCompressor.compress_prompt_llmlingua2", "rate": 0.5, "target_token": -1,
        "force_tokens": ["\n", "?", ".", ","], "force_reserve_digit": False,
        "drop_consecutive": False, "chunk_end_tokens": [".", "\n"], "device": "cpu",
        "torch_dtype": "float32", "seed": 42, "torch_threads": 8, "torch_interop_threads": 1,
        "deterministic_algorithms": True, "worker_processes_per_run": 8, "parallel_inference": True,
        "max_input_characters": 5000, "overflow_policy": "keep_prefix_once_discard_suffix",
        "initialize_timeout_seconds": 180, "inference_timeout_seconds": 300,
        "pool_wait_timeout_seconds": 600,
    }:
        raise ValueError("Keep the reviewed LLMLingua-2 rate, input cap and eight-worker CPU profile")


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
