"""Fail-closed cache-reuse planning, runtime admission, and result contracts."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

from accounting import provider_tokens
from .live_transport import (
    CACHE_NAMESPACE_CONTENT_HEX_CHARS,
    CACHE_NAMESPACE_STRATEGY,
    cache_namespace_message,
)
from .native_contract import TASKS, load_native_ledger, parse_native_ledger
from .protection import canonical, digest


ROOT = Path(__file__).resolve().parents[1]
CONDITIONS = ("none", "squeez")
REUSE_LEVELS = (0, 1, 2)
REUSE_CONTRASTS = ("none:1-0", "none:2-0", "squeez:1-0", "squeez:2-0")
COMPRESSION_CONTRASTS = ("reuse0:squeez-none", "reuse1:squeez-none", "reuse2:squeez-none")
REQUIRED_RUNTIME_CHECKS = (
    "R01_ENDPOINT_PRESENT",
    "R01_MANAGED_IDENTITY_PERMISSION",
    "R01_DEPLOYMENT_MODEL_API_ACCESS",
    "R01_EFFECTIVE_RETENTION",
    "R02_NATIVE_CACHE_FIELD_SUPPORT",
    "R02_NAMESPACE_ISOLATION",
    "R02_EXTERNAL_MATCHING_TRAFFIC_EXCLUDED",
    "R02_QUEUE_RPM_TPM_FACTS",
    "R02_SERIALIZED_PREFIX_CONTRACT",
    "R02_FIXED_PRICE_SOURCE",
    "R02_TASK_AND_SQUEEZ_ASSETS",
    "R02_NO_PROGRESS_BINDING",
    "R02_RUNNER_CONCURRENCY_ONE",
    "APPROVAL_CURRENT_LEADER",
)
RUNTIME_CHECK_OWNERS = {
    **{identifier: "runtime_owner" for identifier in REQUIRED_RUNTIME_CHECKS[:-2]},
    "R02_RUNNER_CONCURRENCY_ONE": "source_and_runtime",
    "APPROVAL_CURRENT_LEADER": "leader",
}
NATIVE_RUNTIME_MODULES = ("harbor", "httpx", "jsonschema", "litellm", "openai", "pydantic", "tiktoken")
SAFE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,127}")
CYCLE_PIN_FIELDS = {
    "provider", "model", "reported_revision", "endpoint_env", "api_surface",
    "temperature", "reasoning_effort", "isolation_evidence_sha256",
    "eligibility_decision_sha256",
}
CACHE_THRESHOLD_TOKENS = 1_024
SCREENING_REQUEST_ORDINALS = (1, 2)
STRUCTURAL_SCREENING_TOKENS = {
    "cancel-async-tasks": 782,
    "log-summary-date-ranges": 1_004,
    "multi-source-data-merger": 1_109,
    "nginx-request-logging": 1_088,
    "openssl-selfsigned-cert": 970,
}
STRUCTURALLY_ELIGIBLE_TASKS = (
    "multi-source-data-merger",
    "nginx-request-logging",
)
STRUCTURALLY_INELIGIBLE_TASKS = (
    "cancel-async-tasks",
    "log-summary-date-ranges",
    "openssl-selfsigned-cert",
)
ELIGIBILITY_CONTRACT_FIELDS = {
    "schema_version", "kind", "decision_version", "decided_at_utc",
    "screening_source_commit", "screening_evidence_sha256", "screening_launches",
    "provider_cache_threshold_tokens", "screening_token_unit", "selection_timing",
    "primary_estimand", "ineligible_cache_result", "full_bundle_estimand",
    "external_validity_limit", "task_denominators", "raw_content_stored",
    "provider_model_api_calls", "rows", "decision_sha256",
}
ELIGIBILITY_ROW_FIELDS = {
    "task_id", "request_ordinal", "local_screening_prefix_tokens",
    "stable_serialized_prefix_bytes", "capture_serialized_prefix_sha256",
    "capture_request_sha256", "cache_eligibility", "execution_bundle_included",
    "primary_cache_estimand_included",
}


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def parse_json_object(content: bytes, label: str) -> dict:
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError(f"Expected one JSON object: {label}")
    return value


def load_json(path: Path) -> dict:
    return parse_json_object(path.read_bytes(), path.name)


def load_cache_ledger(path: Path) -> dict:
    ledger = load_json(path)
    validate_cache_ledger(ledger)
    return ledger


def _require_exact(value, expected, message: str) -> None:
    if value != expected:
        raise ValueError(message)


def eligibility_decision_sha256(contract: dict) -> str:
    if not isinstance(contract, dict) or "decision_sha256" not in contract:
        raise ValueError("Eligibility decision is missing its self-binding SHA-256")
    payload = {key: value for key, value in contract.items() if key != "decision_sha256"}
    return digest(canonical(payload))


def validate_eligibility_contract(contract: dict) -> dict:
    if not isinstance(contract, dict) or set(contract) != ELIGIBILITY_CONTRACT_FIELDS:
        raise ValueError("Eligibility decision fields differ")
    _require_exact(contract["schema_version"], 1, "Unsupported eligibility decision schema")
    _require_exact(
        contract["kind"],
        "cache_reuse_structural_eligibility_decision",
        "Unexpected eligibility decision kind",
    )
    _require_exact(contract["decision_version"], 2, "Unsupported eligibility decision version")
    if not isinstance(contract["decided_at_utc"], str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)",
        contract["decided_at_utc"],
    ):
        raise ValueError("Eligibility decision requires a UTC decision time")
    if not re.fullmatch(r"[0-9a-f]{40}", contract["screening_source_commit"]):
        raise ValueError("Eligibility screening requires an exact source commit")
    if not re.fullmatch(r"[0-9a-f]{64}", contract["screening_evidence_sha256"]):
        raise ValueError("Eligibility screening requires a hash-bound evidence record")
    _require_exact(contract["screening_launches"], 2, "Eligibility screening requires two launches")
    _require_exact(
        contract["provider_cache_threshold_tokens"],
        CACHE_THRESHOLD_TOKENS,
        "Provider cache threshold changed",
    )
    _require_exact(
        contract["screening_token_unit"],
        "local_stable_message_content_prefix_tokens_not_provider_billed_usage",
        "Eligibility screening token provenance changed",
    )
    _require_exact(
        contract["selection_timing"],
        "after_zero_call_structural_screening_before_provider_inference",
        "Eligibility selection timing changed",
    )
    _require_exact(
        contract["primary_estimand"],
        "same_task_condition_reuse_effect_structurally_eligible_tasks_only",
        "Primary cache estimand changed",
    )
    _require_exact(
        contract["ineligible_cache_result"],
        "not_applicable",
        "Structurally ineligible cache results must remain not_applicable",
    )
    _require_exact(
        contract["full_bundle_estimand"],
        "descriptive_provider_usage_computed_cost_quality_all_five_tasks",
        "Full-bundle descriptive estimand changed",
    )
    _require_exact(
        contract["external_validity_limit"],
        "eligibility_screening_favors_cache_capable_inputs_no_generalization",
        "Eligibility-screening external-validity limit changed",
    )
    _require_exact(
        contract["task_denominators"],
        {"execution": 5, "primary_eligible": 2, "not_applicable": 3},
        "Eligibility task denominators changed",
    )
    if contract["raw_content_stored"] is not False or contract["provider_model_api_calls"] != 0:
        raise ValueError("Eligibility screening must remain hash-only and zero-call")
    rows = contract["rows"]
    if not isinstance(rows, list) or len(rows) != len(TASKS) * len(SCREENING_REQUEST_ORDINALS):
        raise ValueError("Eligibility decision needs every fixed task and screened ordinal")
    expected_keys = [
        (task_id, request_ordinal)
        for task_id in TASKS
        for request_ordinal in SCREENING_REQUEST_ORDINALS
    ]
    actual_keys = []
    by_task: dict[str, list[dict]] = {task_id: [] for task_id in TASKS}
    for row in rows:
        if not isinstance(row, dict) or set(row) != ELIGIBILITY_ROW_FIELDS:
            raise ValueError("Eligibility decision row fields differ")
        key = (row["task_id"], row["request_ordinal"])
        actual_keys.append(key)
        if key not in expected_keys:
            raise ValueError("Eligibility decision contains an unknown task or ordinal")
        expected_tokens = STRUCTURAL_SCREENING_TOKENS[row["task_id"]]
        _require_exact(
            row["local_screening_prefix_tokens"],
            [expected_tokens, expected_tokens],
            "Eligibility screening token count changed or launch equality failed",
        )
        if type(row["stable_serialized_prefix_bytes"]) is not int or row["stable_serialized_prefix_bytes"] < 1:
            raise ValueError("Eligibility rows require a positive serialized-prefix byte boundary")
        for field in ("capture_serialized_prefix_sha256", "capture_request_sha256"):
            hashes = row[field]
            if (
                not isinstance(hashes, list)
                or len(hashes) != 2
                or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes)
            ):
                raise ValueError("Eligibility capture hashes must bind exactly two launches")
        if len(set(row["capture_serialized_prefix_sha256"])) != 1:
            raise ValueError("Same-task ordinal serialized prefixes differ across screening launches")
        expected_eligibility = "eligible" if expected_tokens >= CACHE_THRESHOLD_TOKENS else "not_applicable"
        if (
            expected_eligibility == "not_applicable"
            and expected_tokens + CACHE_NAMESPACE_CONTENT_HEX_CHARS >= CACHE_THRESHOLD_TOKENS
        ):
            raise ValueError("Cycle namespace token budget changes the structural eligibility stratum")
        _require_exact(row["cache_eligibility"], expected_eligibility, "Task cache eligibility differs from the threshold")
        _require_exact(row["execution_bundle_included"], True, "Every fixed task must remain in the execution bundle")
        _require_exact(
            row["primary_cache_estimand_included"],
            expected_eligibility == "eligible",
            "Primary eligible-stratum membership changed",
        )
        by_task[row["task_id"]].append(row)
    if actual_keys != expected_keys:
        raise ValueError("Eligibility task and ordinal rows must be complete and ordered")
    for task_id, task_rows in by_task.items():
        if len({row["cache_eligibility"] for row in task_rows}) != 1:
            raise ValueError("One task cannot change eligibility across screened ordinals")
        if task_id in STRUCTURALLY_ELIGIBLE_TASKS and task_rows[0]["cache_eligibility"] != "eligible":
            raise ValueError("Eligible task stratum changed")
        if task_id in STRUCTURALLY_INELIGIBLE_TASKS and task_rows[0]["cache_eligibility"] != "not_applicable":
            raise ValueError("Not-applicable task stratum changed")
    calculated = eligibility_decision_sha256(contract)
    if contract["decision_sha256"] != calculated:
        raise ValueError("Eligibility decision self-binding SHA-256 differs")
    return contract


def task_cache_eligibility(contract: dict, task_id: str) -> str:
    if task_id not in TASKS:
        raise ValueError("Eligibility lookup requires a fixed task")
    rows = [row for row in contract["rows"] if row["task_id"] == task_id]
    values = {row["cache_eligibility"] for row in rows}
    if len(rows) != len(SCREENING_REQUEST_ORDINALS) or len(values) != 1:
        raise ValueError("Eligibility lookup requires both screened ordinals")
    return values.pop()


def validate_cache_ledger(ledger: dict) -> None:
    required = {
        "schema_version", "kind", "status", "live_execution_authorized",
        "design_source_commit", "design_ledger_sha256", "native_ledger", "output_dir",
        "execution_unit", "conditions", "reuse_levels", "runner", "model", "generation",
        "cache", "measurement", "pricing", "contrasts", "stability", "quality",
        "transport", "runtime_required_checks", "output", "record",
    }
    if not isinstance(ledger, dict) or set(ledger) != required:
        raise ValueError("Unexpected or missing cache-reuse ledger fields")
    _require_exact(ledger["schema_version"], 1, "Unsupported cache-reuse ledger version")
    _require_exact(ledger["kind"], "cache_reuse_execution_ledger", "Unexpected cache-reuse ledger kind")
    if ledger["status"] not in {"template_live_no_go", "runtime_bound_live_no_go", "runtime_bound_approved"}:
        raise ValueError("Unknown cache-reuse ledger status")
    if type(ledger["live_execution_authorized"]) is not bool:
        raise ValueError("Live authorization must be an explicit boolean")
    if (ledger["status"] == "runtime_bound_approved") != ledger["live_execution_authorized"]:
        raise ValueError("Only a runtime-bound approved ledger may authorize live execution")
    for field, length in (("design_source_commit", 40), ("design_ledger_sha256", 64)):
        if not isinstance(ledger[field], str) or not re.fullmatch(rf"[0-9a-f]{{{length}}}", ledger[field]):
            raise ValueError(f"{field} must be an immutable lowercase digest")
    native_path = Path(ledger["native_ledger"])
    if native_path.is_absolute() or ".." in native_path.parts or native_path.as_posix() != ledger["native_ledger"]:
        raise ValueError("native_ledger must be a normalized repository-relative path")
    _require_exact(ledger["output_dir"], "runs/cache-reuse", "Cache-reuse outputs must stay in their own private run root")
    unit = ledger["execution_unit"]
    _require_exact(unit, {
        "kind": "fixed_five_task_native_bundle",
        "task_ids": list(TASKS),
        "native_judging_included": True,
    }, "D1 requires the fixed five-task native bundle")
    _require_exact(ledger["conditions"], list(CONDITIONS), "Only none and squeez belong to this axis")
    _require_exact(ledger["reuse_levels"], list(REUSE_LEVELS), "Reuse levels must be 0, 1 and 2")
    runner = ledger["runner"]
    _require_exact(runner, {
        "concurrency": 1,
        "condition_order_odd_cycle": ["none", "squeez"],
        "condition_order_even_cycle": ["squeez", "none"],
        "discarded_warmup_bundles": 0,
    }, "Cache-reuse cycles require serial execution and alternating condition order")
    model = ledger["model"]
    expected_model = {
        "provider": "foundry", "name": "gpt-5.4",
        "reported_revision": "gpt-5.4-2026-03-05",
        "endpoint_env": "FOUNDRY_ENDPOINT",
        "deployment_binding": "required_private_runtime_fact",
        "api_surface": "openai_v1_chat_completions",
    }
    _require_exact(model, expected_model, "Model, revision, endpoint name and API surface must remain pinned")
    _require_exact(ledger["generation"], {
        "temperature": 0, "reasoning_effort": "none", "determinism_claimed": False,
    }, "Generation settings changed or were promoted to a determinism claim")
    cache = ledger["cache"]
    _require_exact(cache, {
        "provider_input_field": "usage.prompt_tokens",
        "provider_cached_input_field": "usage.prompt_tokens_details.cached_tokens",
        "cache_write_field": "not_measured_until_exact_native_support_verified",
        "prefix_extractor": "canonical_message_prefix_v1",
        "prefix_message_count": "required_private_runtime_fact",
        "namespace_or_isolation": "required_private_runtime_fact",
        "external_matching_traffic": "must_be_excluded",
    }, "Provider cache field or prefix/isolation contract changed")
    measurement = ledger["measurement"]
    expected_measurement = {
        "primary_cache_metric": "sum_provider_cached_input_tokens_divided_by_sum_provider_input_tokens_per_useful_bundle",
        "primary_input_cost": "provider_usage_times_fixed_ledger_input_prices_per_useful_bundle",
        "provider_usage": "measured_provider_native",
        "local_tokens": "calculated_diagnostic_only",
        "computed_price": "calculated_not_invoice",
        "invoice": "not_measured",
        "missing_native_usage": "missing_never_zero_or_miss",
        "explicit_numeric_zero": "zero",
        "zero_eligible_opportunity": "not_applicable",
    }
    _require_exact(measurement, expected_measurement, "Measurement units or missing/zero rules changed")
    pricing = ledger["pricing"]
    if set(pricing) != {
        "status", "input_per_million_usd", "cached_input_per_million_usd",
        "output_per_million_usd", "source_reference_sha256", "checked_at_utc",
    } or pricing["status"] not in {"not_verified", "verified"}:
        raise ValueError("Pricing must preserve its verification status and source fields")
    for field in ("input_per_million_usd", "cached_input_per_million_usd", "output_per_million_usd"):
        value = pricing[field]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("Price values must be finite and nonnegative")
    if pricing["cached_input_per_million_usd"] > pricing["input_per_million_usd"]:
        raise ValueError("Cached input price cannot exceed the full input price")
    if pricing["status"] == "verified":
        if not re.fullmatch(r"[0-9a-f]{64}", pricing["source_reference_sha256"] or ""):
            raise ValueError("Verified prices require a source SHA-256")
        if not isinstance(pricing["checked_at_utc"], str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)", pricing["checked_at_utc"],
        ):
            raise ValueError("Verified prices require a UTC observation time")
    elif pricing["source_reference_sha256"] is not None or pricing["checked_at_utc"] is not None:
        raise ValueError("Unverified prices cannot carry source or observation claims")
    contrasts = ledger["contrasts"]
    _require_exact(contrasts, {
        "reuse": list(REUSE_CONTRASTS),
        "compression": list(COMPRESSION_CONTRASTS),
        "forbidden": ["diagonal_or_two_axis"],
    }, "Only fixed-reuse and fixed-condition contrasts are allowed")
    stability = ledger["stability"]
    _require_exact(stability, {
        "target_valid_cycles": 10,
        "maximum_valid_cycles": 20,
        "first_blocks": [[1, 5], [6, 10]],
        "extension_blocks": [[1, 10], [11, 20]],
        "rule": "observed_ranges_overlap_and_median_sign_matches_for_every_paired_series",
        "final_unstable_verdict": "same_condition_width_excess",
    }, "The predeclared 10-to-20 cache stability rule changed")
    _require_exact(ledger["quality"], {
        "rule": "D3_native_quality_10_to_20_separate",
        "cache_rule_reuse": False,
        "inconclusive_effect": "quality_inconclusive_cache_descriptive_only",
    }, "D3 quality and cache stability must stay separate")
    _require_exact(ledger["transport"], {
        "http_429_is_cache_miss": False,
        "retry_contract": "existing_transport_only",
        "outer_retry_restart": False,
        "no_progress_signal": "required_private_runtime_fact",
    }, "Transport retries or no-progress handling changed")
    _require_exact(ledger["runtime_required_checks"], list(REQUIRED_RUNTIME_CHECKS), "Runtime admission checks changed")
    _require_exact(ledger["output"], {
        "no_clobber": True, "invalid_cycles_preserved": True,
        "run_id_unique": True, "attempt_id_unique": True, "cycle_id_unique": True,
        "raw_content_public": False,
    }, "Output no-clobber or privacy contract changed")
    _require_exact(ledger["record"], {
        "denominators": ["task", "run", "request", "cache_cycle"],
        "lineage": [
            "source_commit", "ledger_sha256", "native_ledger_sha256",
            "runtime_facts_sha256", "run_id", "cycle_id", "bundle_id", "attempt_id",
        ],
        "pins": ["model", "deployment", "reported_revision", "source", "input", "tool", "schema"],
        "provenance": ["measured", "synthetic", "projected", "provider", "local", "computed", "invoice"],
    }, "Result denominator, lineage, pin or provenance fields changed")


def _plan_payload(ledger: dict, cycle_count: int) -> dict:
    rows = []
    plan_index = 1
    for cycle_number in range(1, cycle_count + 1):
        condition_order = (
            ledger["runner"]["condition_order_odd_cycle"]
            if cycle_number % 2 else ledger["runner"]["condition_order_even_cycle"]
        )
        cycle_id = f"cycle-{cycle_number:02d}"
        for condition_position, condition in enumerate(condition_order, 1):
            for reuse_level in REUSE_LEVELS:
                bundle_id = f"{cycle_id}-{condition}-reuse-{reuse_level}"
                rows.append({
                    "plan_index": plan_index,
                    "cycle_number": cycle_number,
                    "cycle_id": cycle_id,
                    "condition_position": condition_position,
                    "condition": condition,
                    "reuse_level": reuse_level,
                    "eligible_predecessor_count_required": reuse_level,
                    "bundle_id": bundle_id,
                    "task_count": len(TASKS),
                    "task_ids": list(TASKS),
                    "useful_native_bundle": True,
                    "discarded_warmup": False,
                    "concurrency": 1,
                })
                plan_index += 1
    return {
        "schema_version": 1,
        "kind": "cache_reuse_execution_plan",
        "cycle_count": cycle_count,
        "cell_count": len(rows),
        "task_trials": len(rows) * len(TASKS),
        "rows": rows,
        "allowed_contrasts": {
            "reuse": list(REUSE_CONTRASTS),
            "compression": list(COMPRESSION_CONTRASTS),
        },
        "forbidden_contrasts": ["diagonal_or_two_axis"],
    }


def make_plan(ledger: dict, cycle_count: int) -> dict:
    validate_cache_ledger(ledger)
    if type(cycle_count) is not int or not 1 <= cycle_count <= ledger["stability"]["maximum_valid_cycles"]:
        raise ValueError("Cycle count must be between one and the predeclared maximum")
    plan = _plan_payload(ledger, cycle_count)
    validate_plan(plan, ledger)
    return plan


def validate_plan(plan: dict, ledger: dict) -> dict:
    validate_cache_ledger(ledger)
    if not isinstance(plan, dict) or type(plan.get("cycle_count")) is not int:
        raise ValueError("Malformed cache-reuse plan")
    cycle_count = plan["cycle_count"]
    if not 1 <= cycle_count <= ledger["stability"]["maximum_valid_cycles"]:
        raise ValueError("Plan cycle count exceeds the predeclared boundary")
    expected = _plan_payload(ledger, cycle_count)
    if plan != expected:
        if plan.get("rows") != expected["rows"]:
            raise ValueError("Cache-reuse plan order, cells or predecessor counts differ")
        if plan.get("allowed_contrasts") != expected["allowed_contrasts"] or plan.get("forbidden_contrasts") != expected["forbidden_contrasts"]:
            raise ValueError("Diagonal or undeclared contrasts are forbidden")
        raise ValueError("Cache-reuse plan identity or denominators differ")
    return plan


def validate_runtime_facts(facts: dict, ledger: dict) -> dict[str, dict]:
    required = {
        "schema_version", "kind", "checks", "environment_presence",
        "values_stored", "provider_model_api_calls",
    }
    optional = {"prefix_contract", "eligibility_contract"}
    if set(facts) - required - optional or not required <= set(facts):
        raise ValueError("Unexpected or missing runtime fact fields")
    if facts["schema_version"] != 1 or facts["kind"] != "cache_reuse_runtime_facts":
        raise ValueError("Unexpected runtime fact identity")
    if facts["values_stored"] is not False or facts["provider_model_api_calls"] != 0:
        raise ValueError("Runtime facts must be presence-only and collected without provider calls")
    checks = facts["checks"]
    if not isinstance(checks, list) or len(checks) != len(REQUIRED_RUNTIME_CHECKS):
        raise ValueError("Runtime fact denominator differs from the ledger")
    by_id = {}
    for check in checks:
        if not isinstance(check, dict) or not {"id", "status", "owner"} <= set(check):
            raise ValueError("Runtime check is malformed")
        if set(check) - {"id", "status", "owner", "evidence_sha256", "observed_at_utc", "method", "predicate"}:
            raise ValueError("Runtime check contains an undeclared field")
        if check["id"] in by_id or check["status"] not in {"verified", "partially_verified", "not_verified"}:
            raise ValueError("Runtime check ID or status is invalid")
        if check["owner"] != RUNTIME_CHECK_OWNERS.get(check["id"]):
            raise ValueError("Runtime check owner is invalid")
        evidence = check.get("evidence_sha256")
        if evidence is not None and not re.fullmatch(r"[0-9a-f]{64}", evidence):
            raise ValueError("Runtime evidence needs a SHA-256, not a path or value")
        if check["status"] == "verified":
            if not {"evidence_sha256", "observed_at_utc", "method", "predicate"} <= set(check):
                raise ValueError("Verified runtime facts require evidence, time, method and predicate")
            if not isinstance(check["observed_at_utc"], str) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)", check["observed_at_utc"],
            ):
                raise ValueError("Verified runtime facts require a UTC observation time")
            if any(not isinstance(check[field], str) or not check[field] for field in ("method", "predicate")):
                raise ValueError("Verified runtime fact method and predicate cannot be empty")
        by_id[check["id"]] = check
    if tuple(by_id) != tuple(ledger["runtime_required_checks"]):
        raise ValueError("Runtime checks must preserve the exact ledger order and IDs")
    approval = by_id["APPROVAL_CURRENT_LEADER"]
    if approval["status"] == "verified" and any(
        by_id[identifier]["status"] != "verified"
        for identifier in REQUIRED_RUNTIME_CHECKS[:-1]
    ):
        raise ValueError("Current leader approval requires the other thirteen runtime facts")
    presence = facts["environment_presence"]
    if not isinstance(presence, dict) or any(
        not re.fullmatch(r"[A-Z][A-Z0-9_]*", name) or type(value) is not bool
        for name, value in presence.items()
    ):
        raise ValueError("Environment facts may contain names and booleans only")
    prefix = facts.get("prefix_contract")
    if prefix is not None:
        if set(prefix) != {"message_count", "namespace_message_index", "namespace_content_sha256"}:
            raise ValueError("Prefix contract fields differ")
        if type(prefix["message_count"]) is not int or prefix["message_count"] < 1:
            raise ValueError("Prefix message count must be positive")
        if type(prefix["namespace_message_index"]) is not int or not 0 <= prefix["namespace_message_index"] < prefix["message_count"]:
            raise ValueError("Namespace message index must be inside the serialized prefix")
        if not re.fullmatch(r"[0-9a-f]{64}", prefix["namespace_content_sha256"]):
            raise ValueError("Namespace content must be represented by SHA-256 only")
    eligibility = facts.get("eligibility_contract")
    if eligibility is not None:
        if prefix is not None:
            raise ValueError("The task-stratified eligibility contract cannot mix with the legacy global prefix contract")
        validate_eligibility_contract(eligibility)
        if eligibility["screening_source_commit"] != ledger["design_source_commit"]:
            raise ValueError("Eligibility screening source differs from the approved cache ledger")
        if by_id["R02_SERIALIZED_PREFIX_CONTRACT"].get("evidence_sha256") != eligibility["decision_sha256"]:
            raise ValueError("R02 serialized-prefix evidence must bind the eligibility decision")
    if by_id["R02_SERIALIZED_PREFIX_CONTRACT"]["status"] == "verified" and eligibility is None:
        raise ValueError("Verified R02 requires the task-stratified eligibility decision")
    return by_id


def environment_presence(
    ledger: dict,
    native_ledger: dict,
    environment: Mapping[str, str] | None = None,
) -> dict[str, bool]:
    names = {
        ledger["model"]["endpoint_env"],
        native_ledger["benchmark"]["root_env"],
        native_ledger["measurement"]["cache_env"],
        native_ledger["queue"]["state_path_env"],
        native_ledger["retrieval"]["account_url_env"],
        native_ledger["retrieval"]["spool_root_env"],
        native_ledger["compressor"]["tools"]["squeez"]["binary_env"],
    }
    values = os.environ if environment is None else environment
    return {name: name in values for name in sorted(names)}


def native_cache_contract_checks(ledger: dict, native_ledger: dict) -> dict[str, bool]:
    cache_model = ledger["model"]
    native_model = native_ledger["model"]
    cache_generation = ledger["generation"]
    native_prices = native_ledger["prices"]
    cache_prices = ledger["pricing"]
    price_source = native_prices["source_reference"]
    return {
        "native_model_contract": (
            native_model["provider"] == cache_model["provider"]
            and native_model["name"] == cache_model["name"]
            and native_model["reported_model"] == cache_model["reported_revision"]
            and native_model["endpoint_env"] == cache_model["endpoint_env"]
        ),
        "native_generation_contract": (
            native_model["temperature"] == cache_generation["temperature"]
            and native_model["reasoning_effort"] == cache_generation["reasoning_effort"]
        ),
        "native_price_contract": (
            cache_prices["status"] == "verified"
            and all(
                native_prices[field] == cache_prices[field]
                for field in (
                    "input_per_million_usd",
                    "cached_input_per_million_usd",
                    "output_per_million_usd",
                    "checked_at_utc",
                )
            )
            and bool(price_source)
            and sha256_bytes(price_source.encode()) == cache_prices["source_reference_sha256"]
        ),
        "native_execution_authorized": (
            native_ledger["approval"]["execution_approved"] is True
            and native_ledger["approval"]["rule_accepted"] is True
            and bool(native_ledger["approval"]["reference"].strip())
            and bool(native_ledger["queue"]["deployment_isolation_reference"].strip())
        ),
    }


def doctor(
    ledger: dict,
    runtime_facts: dict,
    native_ledger: dict,
    environment: Mapping[str, str] | None = None,
) -> dict:
    validate_cache_ledger(ledger)
    checks = validate_runtime_facts(runtime_facts, ledger)
    results = []

    def add(identifier: str, passed: bool, detail: str) -> None:
        results.append({"id": identifier, "passed": bool(passed), "detail": detail})

    add("python_3_12", sys.version_info >= (3, 12), "Python 3.12 or newer is required")
    for module in NATIVE_RUNTIME_MODULES:
        add(f"dependency_{module}", importlib.util.find_spec(module) is not None, f"locked dependency {module} is importable")
    add("native_concurrency_one", native_ledger["runner"]["concurrency"] == 1, "cache mode requires explicit native concurrency 1")
    add("native_tasks", native_ledger["benchmark"]["tasks"] == list(TASKS), "native ledger keeps the D1 task bundle")
    add("native_conditions", all(name in native_ledger["conditions"] for name in CONDITIONS), "native ledger contains none and squeez")
    for identifier, passed in native_cache_contract_checks(ledger, native_ledger).items():
        add(identifier, passed, "native and cache ledgers must describe one approved execution contract")
    add("cache_ledger_authorized", ledger["live_execution_authorized"] is True, "public template is intentionally not authorized")
    pricing = ledger["pricing"]
    price_ready = (
        pricing["status"] == "verified"
        and pricing["input_per_million_usd"] > 0
        and pricing["source_reference_sha256"] is not None
        and pricing["checked_at_utc"] is not None
    )
    add("fixed_prices", price_ready, "fixed input prices need a source hash and check time")
    add(
        "prefix_contract",
        runtime_facts.get("eligibility_contract") is not None,
        "runtime must bind every fixed task and screened ordinal to the structural eligibility decision",
    )
    presence = environment_presence(ledger, native_ledger, environment)
    for identifier in REQUIRED_RUNTIME_CHECKS:
        verified = checks[identifier]["status"] == "verified"
        if identifier == "R01_ENDPOINT_PRESENT":
            verified = verified and presence[ledger["model"]["endpoint_env"]]
        add(identifier, verified, "runtime fact must be verified in the current execution process")
    passed = sum(result["passed"] for result in results)
    return {
        "schema_version": 1,
        "kind": "cache_reuse_offline_doctor",
        "decision": "go" if passed == len(results) else "no_go",
        "provider_model_api_calls": 0,
        "credential_values_read": False,
        "environment_presence": presence,
        "checks": results,
        "passed": passed,
        "total": len(results),
    }


class PrefixTracker:
    """Hash exact serialized prefixes and require predecessor equality without storing text."""

    def __init__(
        self,
        eligibility_contract: dict,
        cycle_id: str,
        isolation_evidence_sha256: str,
    ):
        if not SAFE_ID.fullmatch(cycle_id):
            raise ValueError("Cycle ID must be a safe no-clobber identifier")
        if (
            not isinstance(isolation_evidence_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", isolation_evidence_sha256)
        ):
            raise ValueError("Cycle namespace isolation evidence requires SHA-256")
        self.eligibility_contract = validate_eligibility_contract(eligibility_contract)
        self.contract_rows = {
            (row["task_id"], row["request_ordinal"]): row
            for row in self.eligibility_contract["rows"]
        }
        self.cycle_id = cycle_id
        self.isolation_evidence_sha256 = isolation_evidence_sha256
        self.completed: dict[tuple[str, str], list[list[str]]] = {}
        self.pending: dict[tuple[str, int, str], list[str]] = {}

    def observe(self, *, condition: str, reuse_level: int, task: str, payload: dict, serialized: bytes) -> dict:
        if condition not in CONDITIONS or reuse_level not in REUSE_LEVELS or task not in TASKS:
            raise ValueError("Request context differs from the cache-reuse plan")
        if canonical(payload) != serialized:
            raise ValueError("Prefix hashing requires the exact canonical outgoing request")
        history = self.completed.get((condition, task), [])
        if len(history) != reuse_level:
            raise ValueError("Eligible predecessor count differs before provider dispatch")
        pending_key = (condition, reuse_level, task)
        request_hashes = self.pending.get(pending_key, [])
        request_ordinal = len(request_hashes)
        namespace = cache_namespace_message(
            self.cycle_id,
            condition,
            task,
            request_ordinal + 1,
            self.isolation_evidence_sha256,
        )
        messages = payload.get("messages")
        if (
            not isinstance(messages, list)
            or len(messages) < 2
            or messages[0] != namespace
        ):
            raise ValueError("Outgoing request differs from the cycle namespace contract")
        normalized_payload = {**payload, "messages": messages[1:]}
        normalized_serialized = canonical(normalized_payload)
        screening_ordinal = min(request_ordinal + 1, SCREENING_REQUEST_ORDINALS[-1])
        contract_row = self.contract_rows[(task, screening_ordinal)]
        prefix_bytes = contract_row["stable_serialized_prefix_bytes"]
        if len(normalized_serialized) < prefix_bytes:
            raise ValueError("Outgoing request is shorter than the screened serialized prefix")
        screening_prefix_hash = digest(normalized_serialized[:prefix_bytes])
        if screening_prefix_hash != contract_row["capture_serialized_prefix_sha256"][0]:
            raise ValueError("Same-task ordinal serialized prefix differs from the zero-call screening decision")
        marker = b'"messages":['
        insertion_offset = normalized_serialized.find(marker)
        if (
            insertion_offset < 0
            or normalized_serialized.find(marker, insertion_offset + 1) >= 0
        ):
            raise ValueError("Canonical request has an ambiguous message-list boundary")
        insertion_offset += len(marker)
        if prefix_bytes <= insertion_offset:
            raise ValueError("Screened prefix ends before the cycle namespace boundary")
        namespace_fragment = canonical(namespace) + b","
        expected_serialized = (
            normalized_serialized[:insertion_offset]
            + namespace_fragment
            + normalized_serialized[insertion_offset:]
        )
        if expected_serialized != serialized:
            raise ValueError("Cycle namespace serialization differs from the outgoing request")
        namespaced_prefix_bytes = prefix_bytes + len(namespace_fragment)
        prefix_hash = digest(serialized[:namespaced_prefix_bytes])
        for predecessor in history:
            if request_ordinal >= len(predecessor) or predecessor[request_ordinal] != prefix_hash:
                raise ValueError("Cache-key-relevant serialized prefix drifted")
        self.pending.setdefault(pending_key, []).append(prefix_hash)
        return {
            "cycle_id": self.cycle_id,
            "condition": condition,
            "reuse_level": reuse_level,
            "eligible_predecessor_count": len(history),
            "request_ordinal_within_task": request_ordinal + 1,
            "screening_request_ordinal": screening_ordinal,
            "cycle_namespace_strategy": CACHE_NAMESPACE_STRATEGY,
            "cycle_namespace_content_sha256": digest(namespace["content"].encode()),
            "screening_serialized_prefix_sha256": screening_prefix_hash,
            "serialized_prefix_sha256": prefix_hash,
            "serialized_prefix_bytes": namespaced_prefix_bytes,
            "request_sha256": digest(serialized),
            "structural_cache_eligibility": contract_row["cache_eligibility"],
            "eligibility_decision_sha256": self.eligibility_contract["decision_sha256"],
        }

    def finish_bundle(self, condition: str, reuse_level: int, tasks: list[str], *, successful: bool) -> None:
        if tasks != list(TASKS):
            raise ValueError("Completed bundle differs from the fixed D1 task order")
        rows = []
        for task in tasks:
            key = (condition, reuse_level, task)
            hashes = self.pending.pop(key, None)
            if not hashes:
                raise ValueError("Every task needs at least one observed provider request")
            history = self.completed.get((condition, task), [])
            if len(history) != reuse_level:
                raise ValueError("Bundle predecessor denominator changed")
            if any(len(predecessor) != len(hashes) for predecessor in history):
                raise ValueError("Provider request count drifted across eligible bundles")
            rows.append((task, hashes))
        if successful:
            for task, hashes in rows:
                self.completed.setdefault((condition, task), []).append(hashes)


def provider_usage_record(
    response: dict,
    http_status: int | None,
    reuse_level: int,
    pricing: dict,
    *,
    structural_eligibility: str = "eligible",
) -> dict:
    if structural_eligibility not in {"eligible", "not_applicable"}:
        raise ValueError("Cache structural eligibility must be eligible or not_applicable")
    opportunity = (
        "eligible"
        if structural_eligibility == "eligible" and reuse_level > 0
        else "not_applicable"
    )
    unavailable_cache_status = (
        "not_applicable" if structural_eligibility == "not_applicable" else "missing"
    )
    if http_status == 429:
        return {
            "status": "rate_limited", "provider_usage": None, "cache_field_status": unavailable_cache_status,
            "opportunity": opportunity, "structural_eligibility": structural_eligibility,
            "computed_input_cost_usd": None, "computed_total_cost_usd": None,
            "invoice": {"status": "not_measured", "value": None},
        }
    if http_status != 200:
        return {
            "status": "transport_error", "provider_usage": None, "cache_field_status": unavailable_cache_status,
            "opportunity": opportunity, "structural_eligibility": structural_eligibility,
            "computed_input_cost_usd": None, "computed_total_cost_usd": None,
            "invoice": {"status": "not_measured", "value": None},
        }
    tokens = provider_tokens(response)
    if tokens is None:
        return {
            "status": "missing_native_usage", "provider_usage": response.get("usage"),
            "cache_field_status": unavailable_cache_status, "opportunity": opportunity,
            "structural_eligibility": structural_eligibility,
            "computed_input_cost_usd": None, "computed_total_cost_usd": None,
            "invoice": {"status": "not_measured", "value": None},
        }
    cached = tokens["cached_input_tokens"]
    cache_status = (
        "not_applicable"
        if structural_eligibility == "not_applicable"
        else "missing" if cached is None
        else "explicit_zero" if cached == 0
        else "positive"
    )
    status = "missing_native_usage" if cached is None else "invalid_denominator" if tokens["input_tokens"] == 0 else "measured"
    input_cost = total_cost = None
    if status == "measured" and pricing["status"] == "verified":
        uncached = tokens["input_tokens"] - cached
        input_cost = (
            uncached * pricing["input_per_million_usd"]
            + cached * pricing["cached_input_per_million_usd"]
        ) / 1_000_000
        total_cost = input_cost + tokens["output_tokens"] * pricing["output_per_million_usd"] / 1_000_000
    return {
        "status": status,
        "provider_usage": {
            "kind": "measured_provider_native", "unit": "tokens",
            "input_tokens": tokens["input_tokens"],
            "cached_input_tokens": cached,
            "output_tokens": tokens["output_tokens"],
        },
        "cache_field_status": cache_status,
        "opportunity": opportunity,
        "structural_eligibility": structural_eligibility,
        "computed_input_cost_usd": input_cost,
        "computed_total_cost_usd": total_cost,
        "invoice": {"status": "not_measured", "value": None},
    }


def _usage_totals(records: list[dict], *, include_cache_effect: bool) -> dict:
    if not records:
        raise ValueError("A usage stratum needs provider response records")
    missing = sum(record["status"] == "missing_native_usage" for record in records)
    invalid = sum(record["status"] == "invalid_denominator" for record in records)
    errors = sum(record["status"] in {"rate_limited", "transport_error"} for record in records)
    measured = [record for record in records if record["status"] == "measured"]
    input_tokens = sum(record["provider_usage"]["input_tokens"] for record in measured)
    cached_tokens = sum(record["provider_usage"]["cached_input_tokens"] for record in measured)
    output_tokens = sum(record["provider_usage"]["output_tokens"] for record in measured)
    input_costs = [record["computed_input_cost_usd"] for record in measured]
    total_costs = [record["computed_total_cost_usd"] for record in measured]
    complete = not (missing or invalid or errors) and len(measured) == len(records) and input_tokens > 0
    result = {
        "kind": "calculated_from_unique_measured_provider_responses",
        "request_denominator": len(records),
        "measured_requests": len(measured),
        "missing_native_usage": missing,
        "invalid_denominator": invalid,
        "transport_or_429": errors,
        "provider_input_tokens": input_tokens if complete else None,
        "provider_cached_input_tokens": cached_tokens if complete else None,
        "provider_output_tokens": output_tokens if complete else None,
        "computed_input_cost_usd": sum(input_costs) if complete and all(value is not None for value in input_costs) else None,
        "computed_total_cost_usd": sum(total_costs) if complete and all(value is not None for value in total_costs) else None,
        "valid": complete and all(value is not None for value in input_costs + total_costs),
    }
    if include_cache_effect:
        result.update({
            "provider_cache_share": cached_tokens / input_tokens if complete else None,
            "request_hit_rate": (
                sum(record["cache_field_status"] == "positive" for record in measured) / len(measured)
                if complete else None
            ),
        })
    else:
        result["cache_effect"] = "not_applicable_as_full_bundle_estimand"
    return result


def bundle_metrics(records: list[dict]) -> dict:
    if not records:
        raise ValueError("A useful bundle needs provider response records")
    if any(record.get("structural_eligibility") not in {"eligible", "not_applicable"} for record in records):
        raise ValueError("Every provider response needs a structural eligibility status")
    eligible = [record for record in records if record["structural_eligibility"] == "eligible"]
    not_applicable = [record for record in records if record["structural_eligibility"] == "not_applicable"]
    primary = _usage_totals(eligible, include_cache_effect=True)
    descriptive = _usage_totals(records, include_cache_effect=False)
    return {
        **primary,
        "primary_estimand": "same_task_condition_reuse_effect_structurally_eligible_tasks_only",
        "eligible_request_denominator": len(eligible),
        "not_applicable_request_denominator": len(not_applicable),
        "full_bundle_descriptive": descriptive,
        "valid": primary["valid"] and descriptive["valid"],
    }


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _sign(value: float) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


def _series_stable(first: list[float], second: list[float]) -> bool:
    overlap = max(min(first), min(second)) <= min(max(first), max(second))
    return overlap and _sign(_median(first)) == _sign(_median(second))


def _validate_cycle_cohort(valid: list[dict]) -> None:
    if not valid:
        return
    cycle_ids = [cycle.get("cycle_id") for cycle in valid]
    run_ids = [cycle.get("run_id") for cycle in valid]
    cycle_numbers = [cycle.get("cycle_number") for cycle in valid]
    if (
        any(not isinstance(value, str) or not SAFE_ID.fullmatch(value) for value in cycle_ids + run_ids)
        or len(set(cycle_ids)) != len(cycle_ids)
        or len(set(run_ids)) != len(run_ids)
    ):
        raise ValueError("Valid cycles require unique safe cycle and run IDs")
    if cycle_numbers != list(range(1, len(valid) + 1)):
        raise ValueError("Valid cycles must be ordered as the sequential predeclared cohort")
    for cycle, number, run_id in zip(valid, cycle_numbers, run_ids, strict=True):
        if cycle["cycle_id"] != f"cycle-{number:02d}-{digest(run_id.encode())}":
            raise ValueError("Cycle ID must bind its sequential number and unique run ID")
    lineage_fields = (
        ("source_commit", 40),
        ("cache_ledger_sha256", 64),
        ("native_ledger_sha256", 64),
        ("runtime_facts_sha256", 64),
    )
    for field, length in lineage_fields:
        values = [cycle.get(field) for cycle in valid]
        if any(not isinstance(value, str) or not re.fullmatch(rf"[0-9a-f]{{{length}}}", value) for value in values):
            raise ValueError("Cycle cohort provenance requires full immutable hashes")
        if len(set(values)) != 1:
            raise ValueError("Valid cycles cannot mix source or ledger provenance")
    pins = [cycle.get("pins") for cycle in valid]
    if any(not isinstance(value, dict) or set(value) != CYCLE_PIN_FIELDS for value in pins):
        raise ValueError("Cycle cohort pins are incomplete")
    if any(value != pins[0] for value in pins[1:]):
        raise ValueError("Valid cycles cannot mix model, deployment, or isolation pins")
    if not re.fullmatch(r"[0-9a-f]{64}", pins[0]["isolation_evidence_sha256"]):
        raise ValueError("Cycle isolation evidence must be hash-bound")


def _stability_series(valid: list[dict], split: int) -> tuple[bool, dict]:
    series = {}
    stable = True
    for contrast in REUSE_CONTRASTS:
        for metric in ("cache_share_difference", "input_cost_difference"):
            values = [cycle["contrasts"][contrast][metric] for cycle in valid]
            if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
                raise ValueError("Stability requires finite paired differences")
            current = _series_stable(values[:split], values[split:])
            series[f"{contrast}:{metric}"] = current
            stable = stable and current
    return stable, series


def cache_stability(cycles: list[dict]) -> dict:
    valid = [cycle for cycle in cycles if cycle.get("valid") is True]
    _validate_cycle_cohort(valid)
    if len(valid) < 10:
        return {"status": "need_valid_cycles", "valid_cycles": len(valid), "required": 10}
    if len(valid) not in (10, 20):
        raise ValueError("Evaluate the predeclared 10 or 20 valid-cycle boundary only")
    split = 5 if len(valid) == 10 else 10
    if len(valid) == 20:
        first_ten_stable, _first_ten_series = _stability_series(valid[:10], 5)
        if first_ten_stable:
            raise ValueError("Twenty-cycle evaluation requires a recorded unstable ten-cycle boundary")
    stable, series = _stability_series(valid, split)
    if stable:
        return {"status": "stable", "valid_cycles": len(valid), "series": series}
    if len(valid) == 10:
        return {"status": "extend_to_20", "valid_cycles": 10, "series": series}
    return {"status": "same_condition_width_excess", "valid_cycles": 20, "series": series}


def cache_verdict(cycles: list[dict], *, quality_conclusive: bool) -> dict:
    if any(cycle.get("invalid_reason") == "missing_native_usage" for cycle in cycles):
        return {"verdict": "missing_native_usage", "operational": False}
    stability = cache_stability(cycles)
    if stability["status"] != "stable":
        return {"verdict": stability["status"], "operational": False, "stability": stability}
    if not quality_conclusive:
        return {"verdict": "quality_inconclusive", "operational": False, "stability": stability}
    valid = [cycle for cycle in cycles if cycle.get("valid") is True]
    pairs = [cycle["contrasts"][contrast] for cycle in valid for contrast in REUSE_CONTRASTS]
    shares = [pair["cache_share_difference"] for pair in pairs]
    costs = [pair["input_cost_difference"] for pair in pairs]
    if all(value > 0 for value in shares) and all(value < 0 for value in costs):
        verdict = "supported"
    elif all(value == 0 for value in shares + costs):
        verdict = "not_observed"
    elif all(value < 0 for value in shares) and all(value > 0 for value in costs):
        verdict = "wrong_direction"
    else:
        verdict = "no_separation"
    return {"verdict": verdict, "operational": verdict in {"supported", "not_observed"}, "stability": stability}


def result_row(
    *, run_id: str, cycle_id: str, bundle_id: str, attempt_id: str,
    source_commit: str, ledger_sha256: str, native_ledger_sha256: str,
    runtime_facts_sha256: str, eligibility_decision_sha256: str,
    condition: str, reuse_level: int, task_id: str,
    request_observation: dict, usage: dict, local_tokens: dict | None,
    native_verdict: str | None, pins: dict, synthetic: bool = False,
) -> dict:
    identifiers = (run_id, cycle_id, bundle_id, attempt_id)
    if any(not isinstance(value, str) or not value for value in identifiers):
        raise ValueError("Run, cycle, bundle and attempt IDs are required")
    if condition not in CONDITIONS or reuse_level not in REUSE_LEVELS or task_id not in TASKS:
        raise ValueError("Result row differs from the fixed plan")
    hashes = (
        ledger_sha256,
        native_ledger_sha256,
        runtime_facts_sha256,
        eligibility_decision_sha256,
    )
    if (
        not re.fullmatch(r"[0-9a-f]{40}", source_commit)
        or any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes)
    ):
        raise ValueError("Result lineage requires full source and ledger hashes")
    structural_eligibility = usage.get("structural_eligibility")
    if (
        structural_eligibility not in {"eligible", "not_applicable"}
        or request_observation.get("structural_cache_eligibility") != structural_eligibility
        or request_observation.get("eligibility_decision_sha256") != eligibility_decision_sha256
    ):
        raise ValueError("Result eligibility differs from the admitted prefix observation")
    request_ordinal = request_observation.get("request_ordinal_within_task")
    screening_ordinal = request_observation.get("screening_request_ordinal")
    if (
        request_observation.get("cycle_namespace_strategy") != CACHE_NAMESPACE_STRATEGY
        or type(request_ordinal) is not int
        or not 1 <= request_ordinal <= 10_000
        or screening_ordinal != min(request_ordinal, SCREENING_REQUEST_ORDINALS[-1])
        or any(
            not re.fullmatch(r"[0-9a-f]{64}", request_observation.get(field, ""))
            for field in (
                "cycle_namespace_content_sha256",
                "screening_serialized_prefix_sha256",
                "serialized_prefix_sha256",
                "request_sha256",
            )
        )
    ):
        raise ValueError("Result namespace or prefix evidence is incomplete")
    primary_included = structural_eligibility == "eligible"
    return {
        "schema_version": 1,
        "kind": "cache_reuse_request_observation",
        "run_id": run_id,
        "cycle_id": cycle_id,
        "bundle_id": bundle_id,
        "attempt_id": attempt_id,
        "source_commit": source_commit,
        "ledger_sha256": ledger_sha256,
        "native_ledger_sha256": native_ledger_sha256,
        "runtime_facts_sha256": runtime_facts_sha256,
        "eligibility_decision_sha256": eligibility_decision_sha256,
        "condition": condition,
        "reuse_level": reuse_level,
        "task_id": task_id,
        "request_ordinal_within_task": request_ordinal,
        "screening_request_ordinal": screening_ordinal,
        "denominators": {
            "task": 1,
            "run": 1,
            "request": 1,
            "cache_cycle": 1,
            "primary_cache_task": int(primary_included),
            "full_bundle_descriptive_task": 1,
        },
        "pins": pins,
        "cycle_namespace_strategy": request_observation["cycle_namespace_strategy"],
        "cycle_namespace_content_sha256": request_observation["cycle_namespace_content_sha256"],
        "screening_serialized_prefix_sha256": request_observation["screening_serialized_prefix_sha256"],
        "serialized_prefix_sha256": request_observation["serialized_prefix_sha256"],
        "request_sha256": request_observation["request_sha256"],
        "provider_usage": usage["provider_usage"],
        "local_tokens": local_tokens,
        "computed_price": {
            "kind": "calculated_not_invoice",
            "input_usd": usage["computed_input_cost_usd"],
            "total_usd": usage["computed_total_cost_usd"],
        },
        "invoice": usage["invoice"],
        "native_verdict": native_verdict,
        "flags": {
            "measured": not synthetic,
            "synthetic": synthetic,
            "projected": False,
            "provider": usage["provider_usage"] is not None,
            "local": local_tokens is not None,
            "computed": usage["computed_input_cost_usd"] is not None,
            "invoice": False,
            "cache_field_status": usage["cache_field_status"],
            "cache_opportunity": usage["opportunity"],
            "structural_cache_eligibility": structural_eligibility,
            "primary_cache_estimand_included": primary_included,
        },
    }


def _cycle_rows(ledger: dict, cycle_number: int) -> list[dict]:
    plan = make_plan(ledger, cycle_number)
    return [row for row in plan["rows"] if row["cycle_number"] == cycle_number]


def summarize_native_bundle(
    directory: Path,
    row: dict,
    pricing: dict,
    *,
    cache_ledger_sha256: str,
    runtime_facts_sha256: str,
    eligibility_contract: dict,
    parent_run_id: str,
) -> dict:
    from .native_run import verify_cache_bundle_run
    from .task_metrics import read_events

    summary = verify_cache_bundle_run(directory)
    native_ledger = load_native_ledger(directory / "ledger.toml")
    events = read_events(directory / "transport/events.jsonl")
    execution = load_json(directory / "execution.json")
    provenance = load_json(directory / "provenance.json")
    task_sources_bytes = (directory / "task-sources.json").read_bytes()
    schema_hashes = {
        name: value for name, value in provenance["source_files"].items()
        if name.startswith("schemas/")
    }
    eligibility_contract = validate_eligibility_contract(eligibility_contract)
    eligibility_decision_sha256 = eligibility_contract["decision_sha256"]
    pins = {
        "model": native_ledger["model"]["name"],
        "deployment_sha256": execution["deployment_sha256"],
        "reported_revision": native_ledger["model"]["reported_model"],
        "source_commit": summary["source_commit"],
        "input_sha256": digest(task_sources_bytes),
        "tool_sha256": digest(canonical(execution["compressor"])),
        "schema_sha256": digest(canonical(schema_hashes)),
        "eligibility_decision_sha256": eligibility_decision_sha256,
    }
    responses = [event for event in events if event.get("event") == "http"]
    successful = [event for event in responses if event.get("status") == 200]
    usage_records = [
        provider_usage_record(
            {"usage": event.get("provider_usage")},
            200,
            row["reuse_level"],
            pricing,
            structural_eligibility=task_cache_eligibility(
                eligibility_contract,
                event["trial_id"].removeprefix("r01-"),
            ),
        )
        for event in successful
    ]
    metrics = bundle_metrics(usage_records)
    native = {
        trial["task"]: {
            "verdict": trial["native_outcome"]["primary_failure"],
            "reward": trial["native_outcome"]["native_reward"],
        }
        for trial in summary["trials"]
    }
    technical_costs = [event.get("calculated_cost_usd") for event in responses]
    attempt_started = {
        (event["trial_id"], event["request"], event["attempt"]): event
        for event in events if event.get("event") == "attempt_started"
    }
    observations = []
    for event, usage in zip(successful, usage_records, strict=True):
        task_id = event["trial_id"].removeprefix("r01-")
        started = attempt_started[(event["trial_id"], event["request"], event["attempt"])]
        native_verdict = native[task_id]["verdict"]
        observations.append(result_row(
            run_id=parent_run_id,
            cycle_id=row["cycle_id"],
            bundle_id=row["bundle_id"],
            attempt_id=digest(canonical({
                "native_run_id": summary["run_id"], "trial_id": event["trial_id"],
                "request": event["request"], "attempt": event["attempt"],
            })),
            source_commit=summary["source_commit"],
            ledger_sha256=cache_ledger_sha256,
            native_ledger_sha256=summary["ledger_sha256"],
            runtime_facts_sha256=runtime_facts_sha256,
            eligibility_decision_sha256=eligibility_decision_sha256,
            condition=row["condition"],
            reuse_level=row["reuse_level"],
            task_id=task_id,
            request_observation=event["cache_reuse"],
            usage=usage,
            local_tokens={
                "kind": "calculated_diagnostic_only",
                "unit": "tokens",
                "input_tokens": started.get("local_input_tokens"),
                "output_tokens": (event.get("local_output") or {}).get("content_tokens"),
            },
            native_verdict=native_verdict,
            pins=pins,
        ))
    return {
        "schema_version": 1,
        "kind": "cache_reuse_useful_bundle_summary",
        "cycle_id": row["cycle_id"],
        "bundle_id": row["bundle_id"],
        "condition": row["condition"],
        "reuse_level": row["reuse_level"],
        "eligible_predecessor_count": row["eligible_predecessor_count_required"],
        "task_denominator": len(summary["trials"]),
        "primary_cache_task_denominator": len(STRUCTURALLY_ELIGIBLE_TASKS),
        "not_applicable_cache_task_denominator": len(STRUCTURALLY_INELIGIBLE_TASKS),
        "run_denominator": 1,
        "request_denominator": len(successful),
        "provider_http_attempt_denominator": len(responses),
        "provider_http_429": sum(event.get("status") == 429 for event in responses),
        "technical_attempt_cost": {
            "kind": "provider_usage_times_fixed_ledger_rates_not_invoice",
            "known_usd": sum(value for value in technical_costs if value is not None),
            "unknown_attempts": sum(value is None for value in technical_costs),
        },
        "metrics": metrics,
        "native_verdicts": native,
        "pins": pins,
        "lineage": {
            "source_commit": summary["source_commit"],
            "cache_ledger_sha256": cache_ledger_sha256,
            "native_ledger_sha256": summary["ledger_sha256"],
            "runtime_facts_sha256": runtime_facts_sha256,
            "eligibility_decision_sha256": eligibility_decision_sha256,
            "run_id": parent_run_id,
            "cycle_id": row["cycle_id"],
            "bundle_id": row["bundle_id"],
        },
        "observations": observations,
        "native_run_id": summary["run_id"],
        "native_artifact_manifest_sha256": summary["artifact_manifest_sha256"],
        "estimands": {
            "primary_cache": {
                "task_ids": list(STRUCTURALLY_ELIGIBLE_TASKS),
                "task_denominator": len(STRUCTURALLY_ELIGIBLE_TASKS),
                "scope": eligibility_contract["primary_estimand"],
            },
            "full_bundle_descriptive": {
                "task_ids": list(TASKS),
                "task_denominator": len(TASKS),
                "scope": eligibility_contract["full_bundle_estimand"],
                "cache_generalization": "not_claimed",
            },
            "selection_timing": eligibility_contract["selection_timing"],
            "external_validity_limit": eligibility_contract["external_validity_limit"],
        },
        "flags": {
            "measured": True,
            "synthetic": False,
            "projected": False,
            "provider": True,
            "local": True,
            "computed": metrics["computed_input_cost_usd"] is not None,
            "invoice": False,
        },
    }


def _cycle_contrasts(bundles: list[dict]) -> dict:
    by_cell = {(bundle["condition"], bundle["reuse_level"]): bundle for bundle in bundles}
    if set(by_cell) != {(condition, level) for condition in CONDITIONS for level in REUSE_LEVELS}:
        raise ValueError("A cache cycle needs all six fixed cells")
    contrasts = {}
    for condition in CONDITIONS:
        cold = by_cell[(condition, 0)]["metrics"]
        for level in (1, 2):
            warm = by_cell[(condition, level)]["metrics"]
            if not cold["valid"] or not warm["valid"]:
                raise ValueError("Invalid bundles cannot produce a paired cache contrast")
            contrasts[f"{condition}:{level}-0"] = {
                "cache_share_difference": warm["provider_cache_share"] - cold["provider_cache_share"],
                "input_cost_difference": warm["computed_input_cost_usd"] - cold["computed_input_cost_usd"],
            }
    compression = {}
    for level in REUSE_LEVELS:
        none = by_cell[("none", level)]["metrics"]
        squeez = by_cell[("squeez", level)]["metrics"]
        compression[f"reuse{level}:squeez-none"] = {
            "cache_share_difference": squeez["provider_cache_share"] - none["provider_cache_share"],
            "input_cost_difference": squeez["computed_input_cost_usd"] - none["computed_input_cost_usd"],
        }
    return {"reuse": contrasts, "compression": compression, "diagonal_comparisons": []}


def execute_cycle(
    cache_ledger_path: Path,
    runtime_facts_path: Path,
    native_ledger_path: Path | None,
    source_commit: str,
    cycle_number: int,
    run_id: str,
    output: Path | None = None,
    *,
    native_execute=None,
) -> dict:
    ledger_bytes = cache_ledger_path.read_bytes()
    facts_bytes = runtime_facts_path.read_bytes()
    ledger = parse_json_object(ledger_bytes, cache_ledger_path.name)
    validate_cache_ledger(ledger)
    native_ledger_path = (native_ledger_path or ROOT / ledger["native_ledger"]).resolve()
    native_ledger_bytes = native_ledger_path.read_bytes()
    facts = parse_json_object(facts_bytes, runtime_facts_path.name)
    native = parse_native_ledger(native_ledger_bytes)
    cache_ledger_sha256 = sha256_bytes(ledger_bytes)
    runtime_facts_sha256 = sha256_bytes(facts_bytes)
    native_ledger_sha256 = sha256_bytes(native_ledger_bytes)
    admission = doctor(ledger, facts, native)
    if admission["decision"] != "go":
        raise ValueError("Offline doctor and current-runtime admission must be green before provider dispatch")
    if source_commit != ledger["design_source_commit"]:
        raise ValueError("Execution source differs from the approved cache ledger")
    verify_source_commit(source_commit)
    if not SAFE_ID.fullmatch(run_id):
        raise ValueError("Run ID must be a safe no-clobber identifier")
    rows = _cycle_rows(ledger, cycle_number)
    execution_cycle_id = f"{rows[0]['cycle_id']}-{digest(run_id.encode())}"
    rows = [
        {
            **row,
            "cycle_id": execution_cycle_id,
            "bundle_id": f"{execution_cycle_id}-{row['condition']}-reuse-{row['reuse_level']}",
        }
        for row in rows
    ]
    source_root = ROOT.resolve()
    run_root = source_root / ledger["output_dir"] / run_id
    expected_output = run_root / execution_cycle_id
    if output is not None and output.resolve() != expected_output:
        raise ValueError("Cycle output must use the fixed ledger root and derived run/cycle identity")
    output = expected_output
    if output.exists():
        raise FileExistsError("Cache-reuse run output already exists")
    by_check = validate_runtime_facts(facts, ledger)
    isolation_hash = by_check["R02_NAMESPACE_ISOLATION"].get("evidence_sha256")
    if isolation_hash is None:
        raise ValueError("Isolation must have hash-bound runtime evidence")
    eligibility_contract = validate_eligibility_contract(facts["eligibility_contract"])
    eligibility_decision_hash = eligibility_contract["decision_sha256"]
    tracker = PrefixTracker(
        eligibility_contract,
        rows[0]["cycle_id"],
        isolation_hash,
    )
    run_root.mkdir(parents=True, exist_ok=False)
    output.mkdir(exist_ok=False)
    os.chmod(run_root, 0o700)
    os.chmod(output, 0o700)
    write_bytes_no_clobber(output / "ledger.json", ledger_bytes)
    write_bytes_no_clobber(output / "runtime-facts.json", facts_bytes)
    write_bytes_no_clobber(output / "native-ledger.toml", native_ledger_bytes)
    write_no_clobber(output / "doctor.json", admission)
    write_no_clobber(output / "plan.json", {
        "schema_version": 1,
        "kind": "cache_reuse_single_cycle_plan",
        "cycle_number": cycle_number,
        "rows": rows,
    })
    if native_execute is None:
        from .native_run import execute_native as native_execute
    bundles = []
    try:
        for row in rows:
            context = {
                "cycle_id": row["cycle_id"],
                "bundle_id": row["bundle_id"],
                "condition": row["condition"],
                "reuse_level": row["reuse_level"],
                "eligible_predecessor_count": row["eligible_predecessor_count_required"],
                "cache_ledger_sha256": cache_ledger_sha256,
                "runtime_facts_sha256": runtime_facts_sha256,
                "native_ledger_sha256": native_ledger_sha256,
                "isolation_evidence_sha256": isolation_hash,
            }

            def observe_request(*, task, payload, serialized, **_ignored):
                return tracker.observe(
                    condition=row["condition"], reuse_level=row["reuse_level"], task=task,
                    payload=payload, serialized=serialized,
                )

            native_directory = native_execute(
                native_ledger_path,
                native,
                source_commit,
                row["condition"],
                cache_context=context,
                request_observer=observe_request,
            )
            bundle = summarize_native_bundle(
                native_directory,
                row,
                ledger["pricing"],
                cache_ledger_sha256=cache_ledger_sha256,
                runtime_facts_sha256=runtime_facts_sha256,
                eligibility_contract=eligibility_contract,
                parent_run_id=run_id,
            )
            if bundle["lineage"]["native_ledger_sha256"] != native_ledger_sha256:
                raise ValueError("Native execution ledger differs from the admitted snapshot")
            successful = bundle["metrics"]["valid"] and bundle["task_denominator"] == len(TASKS)
            tracker.finish_bundle(row["condition"], row["reuse_level"], list(TASKS), successful=successful)
            bundles.append(bundle)
            write_no_clobber(output / "bundles" / f"{row['bundle_id']}.json", bundle)
            if not successful:
                raise ValueError("Invalid bundle preserved; replacement requires a new no-clobber cycle ID")
        contrasts = _cycle_contrasts(bundles)
        cycle = {
            "schema_version": 1,
            "kind": "cache_reuse_cycle_summary",
            "run_id": run_id,
            "cycle_id": rows[0]["cycle_id"],
            "cycle_number": cycle_number,
            "source_commit": source_commit,
            "cache_ledger_sha256": cache_ledger_sha256,
            "runtime_facts_sha256": runtime_facts_sha256,
            "native_ledger_sha256": native_ledger_sha256,
            "output_relative": output.relative_to(source_root).as_posix(),
            "pins": {
                "provider": ledger["model"]["provider"],
                "model": ledger["model"]["name"],
                "reported_revision": ledger["model"]["reported_revision"],
                "endpoint_env": ledger["model"]["endpoint_env"],
                "api_surface": ledger["model"]["api_surface"],
                "temperature": ledger["generation"]["temperature"],
                "reasoning_effort": ledger["generation"]["reasoning_effort"],
                "isolation_evidence_sha256": isolation_hash,
                "eligibility_decision_sha256": eligibility_decision_hash,
            },
            "valid": True,
            "bundle_denominator": len(bundles),
            "task_denominator": sum(bundle["task_denominator"] for bundle in bundles),
            "primary_cache_task_denominator": sum(
                bundle["primary_cache_task_denominator"] for bundle in bundles
            ),
            "not_applicable_cache_task_denominator": sum(
                bundle["not_applicable_cache_task_denominator"] for bundle in bundles
            ),
            "request_denominator": sum(bundle["request_denominator"] for bundle in bundles),
            "primary_cache_request_denominator": sum(
                bundle["metrics"]["eligible_request_denominator"] for bundle in bundles
            ),
            "not_applicable_cache_request_denominator": sum(
                bundle["metrics"]["not_applicable_request_denominator"] for bundle in bundles
            ),
            "contrasts": contrasts["reuse"],
            "compression_contrasts": contrasts["compression"],
            "diagonal_comparisons": contrasts["diagonal_comparisons"],
            "full_bundle_descriptive": [
                {
                    "bundle_id": bundle["bundle_id"],
                    "condition": bundle["condition"],
                    "reuse_level": bundle["reuse_level"],
                    **bundle["metrics"]["full_bundle_descriptive"],
                }
                for bundle in bundles
            ],
            "estimands": {
                "primary_cache": eligibility_contract["primary_estimand"],
                "full_bundle_descriptive": eligibility_contract["full_bundle_estimand"],
                "selection_timing": eligibility_contract["selection_timing"],
                "external_validity_limit": eligibility_contract["external_validity_limit"],
            },
            "quality_status": "pending_separate_D3_10_to_20_rule",
        }
        write_no_clobber(output / "cycle.json", cycle)
        return cycle
    except BaseException as error:
        failure = {
            "schema_version": 1,
            "kind": "cache_reuse_cycle_failure",
            "run_id": run_id,
            "cycle_id": rows[0]["cycle_id"],
            "source_commit": source_commit,
            "status": "invalid_preserved",
            "error_type": type(error).__name__,
            "cache_ledger_sha256": cache_ledger_sha256,
            "runtime_facts_sha256": runtime_facts_sha256,
            "native_ledger_sha256": native_ledger_sha256,
            "completed_bundle_denominator": len(bundles),
            "provider_retry_interpretation": "429_and_transport_errors_are_not_cache_misses",
        }
        write_no_clobber(output / "failure.json", failure)
        raise


def write_no_clobber(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def write_bytes_no_clobber(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(content)


def verify_source_commit(source_commit: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("--source-commit requires a full lowercase SHA")
    head = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    if head != source_commit:
        raise ValueError("Checkout HEAD differs from --source-commit")
    status = subprocess.check_output(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=all"],
        text=True,
    )
    if status:
        raise ValueError("Execution requires a clean reviewed checkout")


def _load_native_for_cache(ledger: dict, override: Path | None) -> tuple[Path, dict]:
    path = override or ROOT / ledger["native_ledger"]
    native = load_native_ledger(path)
    return path, native


def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", nargs="?", type=Path, default=ROOT / "ledgers/cache-reuse.template.json")
    parser.add_argument("--runtime-facts", type=Path, default=ROOT / "fixtures/cache-reuse/runtime-facts.template.json")
    parser.add_argument("--native-ledger", type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--cycles", type=int, default=10)
    parser.add_argument("--output", type=Path, help="Plan/doctor file, or the exact derived cycle directory")
    parser.add_argument("--run-id")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--plan", action="store_true", help="Generate the deterministic zero-network plan")
    action.add_argument("--doctor", action="store_true", help="Check dependencies and presence-only runtime admission")
    action.add_argument("--execute-cycle", type=int, help="Execute one admitted six-cell cycle after separate leader approval")
    args = parser.parse_args(arguments)
    try:
        ledger_path = args.ledger.resolve()
        if args.execute_cycle is not None:
            if args.source_commit is None or args.run_id is None:
                raise ValueError("Cycle execution requires --source-commit and a new --run-id")
            result = execute_cycle(
                ledger_path,
                args.runtime_facts.resolve(),
                args.native_ledger.resolve() if args.native_ledger is not None else None,
                args.source_commit,
                args.execute_cycle,
                args.run_id,
                args.output.resolve() if args.output is not None else None,
            )
        else:
            ledger = load_cache_ledger(ledger_path)
            if args.source_commit is not None:
                verify_source_commit(args.source_commit)
            if args.plan:
                result = make_plan(ledger, args.cycles)
            else:
                _native_path, native = _load_native_for_cache(ledger, args.native_ledger)
                facts = load_json(args.runtime_facts)
                result = doctor(ledger, facts, native)
        if args.output is not None and args.execute_cycle is None:
            write_no_clobber(args.output, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if args.doctor and result["decision"] != "go":
            return 3
        return 0
    except (ValueError, OSError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(f"Cache-reuse preflight failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
