"""Aggregate outcome-linked costs without turning unknown values into zero."""

from __future__ import annotations

import argparse
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "data/experiment/outcome-cost-evidence.json"
OUTPUT = ROOT / "data/experiment/outcome-cost-accounting.json"

QUALITY_OUTCOMES = {"pass", "wrong_answer", "wrong_format"}
PRE_QUALITY_OUTCOMES = {
    "technical_incomplete",
    "operator_stopped",
    "stalled_http_response",
}
ALL_OUTCOMES = QUALITY_OUTCOMES | PRE_QUALITY_OUTCOMES | {"cancelled_before_start"}
PRICE_BASIS = {
    "kind": "provider_usage_times_fixed_rates_not_invoice_reconciliation",
    "input_per_million_usd": "2.5",
    "cached_input_per_million_usd": "0.25",
    "output_per_million_usd": "15",
}


def _decimal(value: object, field: str, *, nullable: bool = False) -> Decimal | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{field} is not a decimal") from error
    if not result.is_finite() or result < 0:
        raise ValueError(f"{field} must be finite and nonnegative")
    return result


def _money(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("Outcome-cost evidence must be a JSON object")
    return value


def _new_bucket() -> dict:
    return {
        "quality_results": 0,
        "started_attempts": 0,
        "outcomes": defaultdict(int),
        "known_usage_attempts": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "api_known": Decimal(0),
        "api_unknown_attempts": 0,
        "api_estimate": Decimal(0),
        "api_estimate_records": 0,
        "vm_direct": Decimal(0),
        "vm_direct_unknown_attempts": 0,
        "vm_non_additive": Decimal(0),
        "vm_non_additive_records": 0,
        "blob_known": Decimal(0),
        "blob_unknown_attempts": 0,
    }


def _bucket_name(outcome: str) -> str:
    if outcome == "pass":
        return "pass"
    if outcome in {"wrong_answer", "wrong_format"}:
        return "normal_nonpass"
    if outcome in PRE_QUALITY_OUTCOMES:
        return "pre_quality"
    return "cancelled_before_start"


def _validate_price_basis(value: object) -> None:
    if value != PRICE_BASIS:
        raise ValueError("Provider price basis differs from the fixed public contract")


def _provider_cost(provider_usage: object) -> Decimal:
    required = {
        "known_attempts", "input_tokens", "cached_input_tokens", "output_tokens",
    }
    if not isinstance(provider_usage, dict) or set(provider_usage) != required:
        raise ValueError("Provider usage fields do not match the public contract")
    for field in required:
        if type(provider_usage[field]) is not int or provider_usage[field] < 0:
            raise ValueError(f"provider_usage.{field} must be a nonnegative integer")
    if provider_usage["cached_input_tokens"] > provider_usage["input_tokens"]:
        raise ValueError("Cached input tokens cannot exceed total input tokens")
    uncached_input = (
        provider_usage["input_tokens"] - provider_usage["cached_input_tokens"]
    )
    return (
        Decimal(uncached_input) * Decimal(PRICE_BASIS["input_per_million_usd"])
        + Decimal(provider_usage["cached_input_tokens"])
        * Decimal(PRICE_BASIS["cached_input_per_million_usd"])
        + Decimal(provider_usage["output_tokens"])
        * Decimal(PRICE_BASIS["output_per_million_usd"])
    ) / Decimal(1_000_000)


def _validate_attempt(record: dict, seen_attempts: set[str], quality_trials: set[str]) -> None:
    required = {
        "record_id", "scope", "trial_key", "started", "attempt_outcome",
        "quality_result", "provider_usage", "cost",
    }
    if set(record) != required:
        raise ValueError("Attempt record fields do not match the public contract")
    record_id = record["record_id"]
    trial_key = record["trial_key"]
    if not isinstance(record_id, str) or not record_id or record_id in seen_attempts:
        raise ValueError("Attempt record identifiers must be nonempty and unique")
    if not isinstance(trial_key, str) or not trial_key:
        raise ValueError("Trial keys must be nonempty strings")
    seen_attempts.add(record_id)
    outcome = record["attempt_outcome"]
    if outcome not in ALL_OUTCOMES:
        raise ValueError(f"Unsupported attempt outcome: {outcome}")
    if type(record["started"]) is not bool:
        raise ValueError("started must be boolean")
    quality = record["quality_result"]
    if outcome in QUALITY_OUTCOMES:
        if quality != outcome:
            raise ValueError("Quality-bearing attempt outcome and quality result must match")
        if trial_key in quality_trials:
            raise ValueError("A trial may carry a quality result only once")
        quality_trials.add(trial_key)
    elif quality is not None:
        raise ValueError("Pre-quality and pre-start attempts cannot carry a quality result")
    if record["started"] != (outcome != "cancelled_before_start"):
        raise ValueError("Only cancelled-before-start records may have started=false")

    cost = record["cost"]
    required_cost = {
        "api_known_usd", "api_unknown_attempts", "api_unconfirmed_estimate_usd",
        "vm_direct_attributable_usd", "vm_observed_non_additive_usd",
        "blob_network_known_usd", "invoice_reconciled",
    }
    if not isinstance(cost, dict) or set(cost) != required_cost:
        raise ValueError("Attempt cost fields do not match the public contract")
    api_known = _decimal(cost["api_known_usd"], "cost.api_known_usd")
    provider_usage = record["provider_usage"]
    if api_known != _provider_cost(provider_usage):
        raise ValueError("Known API cost differs from provider usage and fixed rates")
    api_estimate = _decimal(
        cost["api_unconfirmed_estimate_usd"],
        "cost.api_unconfirmed_estimate_usd",
        nullable=True,
    )
    vm_direct = _decimal(
        cost["vm_direct_attributable_usd"],
        "cost.vm_direct_attributable_usd",
        nullable=True,
    )
    vm_observed = _decimal(
        cost["vm_observed_non_additive_usd"],
        "cost.vm_observed_non_additive_usd",
        nullable=True,
    )
    blob_known = _decimal(
        cost["blob_network_known_usd"],
        "cost.blob_network_known_usd",
        nullable=True,
    )
    unknown_attempts = cost["api_unknown_attempts"]
    if type(unknown_attempts) is not int or unknown_attempts < 0:
        raise ValueError("cost.api_unknown_attempts must be a nonnegative integer")
    if unknown_attempts == 0 and api_estimate not in (None, Decimal(0)):
        raise ValueError("An API estimate needs at least one unknown provider attempt")
    if cost["invoice_reconciled"] is not False:
        raise ValueError("Current calculated costs are not invoice-reconciled")
    if not record["started"] and any((
        api_known != 0,
        any(provider_usage.values()),
        unknown_attempts != 0,
        api_estimate not in (None, Decimal(0)),
        vm_direct not in (None, Decimal(0)),
        vm_observed not in (None, Decimal(0)),
        blob_known not in (None, Decimal(0)),
    )):
        raise ValueError("A cancelled-before-start attempt must have zero known cost")


def _aggregate_records(records: list[dict]) -> dict:
    buckets = {name: _new_bucket() for name in (
        "pass", "normal_nonpass", "pre_quality", "cancelled_before_start"
    )}
    seen_attempts: set[str] = set()
    quality_trials: set[str] = set()
    for record in records:
        _validate_attempt(record, seen_attempts, quality_trials)
        bucket = buckets[_bucket_name(record["attempt_outcome"])]
        bucket["quality_results"] += record["quality_result"] is not None
        bucket["started_attempts"] += record["started"]
        bucket["outcomes"][record["attempt_outcome"]] += 1
        provider_usage = record["provider_usage"]
        bucket["known_usage_attempts"] += provider_usage["known_attempts"]
        bucket["input_tokens"] += provider_usage["input_tokens"]
        bucket["cached_input_tokens"] += provider_usage["cached_input_tokens"]
        bucket["output_tokens"] += provider_usage["output_tokens"]
        cost = record["cost"]
        bucket["api_known"] += _decimal(cost["api_known_usd"], "api_known_usd")
        bucket["api_unknown_attempts"] += cost["api_unknown_attempts"]
        estimate = _decimal(cost["api_unconfirmed_estimate_usd"], "api_estimate", nullable=True)
        if estimate is not None:
            bucket["api_estimate"] += estimate
            bucket["api_estimate_records"] += 1
        vm_direct = _decimal(cost["vm_direct_attributable_usd"], "vm_direct", nullable=True)
        if vm_direct is None and record["started"]:
            bucket["vm_direct_unknown_attempts"] += 1
        elif vm_direct is not None:
            bucket["vm_direct"] += vm_direct
        vm_observed = _decimal(cost["vm_observed_non_additive_usd"], "vm_observed", nullable=True)
        if vm_observed is not None:
            bucket["vm_non_additive"] += vm_observed
            bucket["vm_non_additive_records"] += 1
        blob = _decimal(cost["blob_network_known_usd"], "blob_known", nullable=True)
        if blob is None and record["started"]:
            bucket["blob_unknown_attempts"] += 1
        elif blob is not None:
            bucket["blob_known"] += blob
    return {name: _render_bucket(bucket) for name, bucket in buckets.items()}


def _render_bucket(bucket: dict) -> dict:
    api_cost_per_quality_result = None
    if bucket["quality_results"]:
        api_cost_per_quality_result = _money(
            bucket["api_known"] / bucket["quality_results"]
        )
    return {
        "quality_results": bucket["quality_results"],
        "started_attempts": bucket["started_attempts"],
        "outcomes": dict(sorted(bucket["outcomes"].items())),
        "provider_usage_known": {
            "attempts": bucket["known_usage_attempts"],
            "input_tokens": bucket["input_tokens"],
            "cached_input_tokens": bucket["cached_input_tokens"],
            "output_tokens": bucket["output_tokens"],
        },
        "api_calculated_cost_known_usd": _money(bucket["api_known"]),
        "api_calculated_cost_per_quality_result_usd": api_cost_per_quality_result,
        "api_unknown_attempts": bucket["api_unknown_attempts"],
        "api_unconfirmed_estimate_usd": (
            _money(bucket["api_estimate"]) if bucket["api_estimate_records"] else None
        ),
        "vm_direct_attributable_cost_known_usd": (
            _money(bucket["vm_direct"])
            if bucket["vm_direct_unknown_attempts"] == 0 else None
        ),
        "vm_direct_unknown_attempts": bucket["vm_direct_unknown_attempts"],
        "vm_observed_non_additive_usd": (
            _money(bucket["vm_non_additive"])
            if bucket["vm_non_additive_records"] else None
        ),
        "blob_network_cost_known_usd": _money(bucket["blob_known"]),
        "blob_network_unknown_attempts": bucket["blob_unknown_attempts"],
        "invoice_reconciled": False,
    }


def _scope(records: list[dict], name: str) -> list[dict]:
    return [record for record in records if record["scope"] == name]


def build_accounting(evidence: dict, source_sha256: str) -> dict:
    if evidence.get("schema_version") != 1 or evidence.get("currency") != "USD":
        raise ValueError("Unsupported outcome-cost evidence contract")
    if evidence.get("labels") != {"measured": True, "synthetic": False, "projected": False}:
        raise ValueError("Evidence labels must distinguish measured data")
    _validate_price_basis(evidence.get("price_basis"))
    records = evidence.get("attempts")
    if not isinstance(records, list):
        raise ValueError("attempts must be an array")
    _aggregate_records(records)
    completed_records = _scope(records, "completed_cohort_joined")
    long_tail_records = _scope(records, "long_tail_pre_quality")
    cancelled_records = _scope(records, "cancelled_before_start")
    if len(completed_records) + len(long_tail_records) + len(cancelled_records) != len(records):
        raise ValueError("Every public record must belong to a known scope")
    completed = _aggregate_records(completed_records)
    long_tail = _aggregate_records(long_tail_records)
    cancelled = _aggregate_records(cancelled_records)
    long_tail_by_outcome = {
        outcome: _aggregate_records([
            record for record in long_tail_records
            if record["attempt_outcome"] == outcome
        ])["pre_quality"]
        for outcome in (
            "technical_incomplete", "operator_stopped", "stalled_http_response"
        )
    }
    if completed["pre_quality"]["outcomes"] or completed["cancelled_before_start"]["outcomes"]:
        raise ValueError("Joined completed-cohort records must carry quality results")
    if (
        long_tail["pass"]["quality_results"]
        or long_tail["normal_nonpass"]["quality_results"]
        or long_tail["cancelled_before_start"]["outcomes"]
    ):
        raise ValueError("Long-tail records must remain pre-quality")
    if (
        cancelled["pass"]["outcomes"]
        or cancelled["normal_nonpass"]["outcomes"]
        or cancelled["pre_quality"]["outcomes"]
    ):
        raise ValueError("Pre-start scope may contain only cancelled attempts")

    controls = evidence.get("controls")
    if not isinstance(controls, dict):
        raise ValueError("controls must be an object")
    cohort = controls["completed_cohort"]
    long_control = controls["long_tail"]
    total_conditions = cohort["conditions"]
    pass_count = cohort["pass"]
    wrong_answer_count = cohort["wrong_answer"]
    wrong_format_count = cohort["wrong_format"]
    if any(type(value) is not int or value < 0 for value in (
        total_conditions, pass_count, wrong_answer_count, wrong_format_count
    )):
        raise ValueError("Completed-cohort counts must be nonnegative integers")
    if pass_count + wrong_answer_count + wrong_format_count != total_conditions:
        raise ValueError("Completed-cohort quality counts do not reconcile")
    cohort_api = _decimal(cohort["api_calculated_cost_usd"], "cohort API cost")
    arithmetic_control = _decimal(
        cohort["arithmetic_api_cost_per_pass_usd"], "cohort cost-per-pass control"
    )
    if pass_count == 0 or cohort_api / pass_count != arithmetic_control:
        raise ValueError("Completed-cohort cost-per-pass arithmetic control drifted")

    joined_pass = completed["pass"]["quality_results"]
    joined_nonpass = completed["normal_nonpass"]["quality_results"]
    joined_conditions = joined_pass + joined_nonpass
    joined_api = (
        _decimal(completed["pass"]["api_calculated_cost_known_usd"], "joined pass API")
        + _decimal(completed["normal_nonpass"]["api_calculated_cost_known_usd"], "joined nonpass API")
    )
    missing_conditions = total_conditions - joined_conditions
    missing_pass = pass_count - joined_pass
    joined_wrong_answer = completed["normal_nonpass"]["outcomes"].get("wrong_answer", 0)
    joined_wrong_format = completed["normal_nonpass"]["outcomes"].get("wrong_format", 0)
    missing_wrong_answer = wrong_answer_count - joined_wrong_answer
    missing_wrong_format = wrong_format_count - joined_wrong_format
    if min(missing_conditions, missing_pass, missing_wrong_answer, missing_wrong_format) < 0:
        raise ValueError("Joined outcome counts exceed the completed-cohort control")
    unallocated_api = cohort_api - joined_api
    if unallocated_api < 0:
        raise ValueError("Joined API cost exceeds the completed-cohort control")

    long_api = _decimal(long_tail["pre_quality"]["api_calculated_cost_known_usd"], "long-tail API")
    if (
        long_tail["pre_quality"]["started_attempts"] != long_control["started_attempts"]
        or long_tail["pre_quality"]["quality_results"] != long_control["quality_results"]
        or long_tail["pre_quality"]["outcomes"].get("operator_stopped", 0)
        != long_control["operator_stopped"]
        or long_tail["pre_quality"]["outcomes"].get("stalled_http_response", 0)
        != long_control["stalled_http_response"]
        or long_tail["pre_quality"]["api_unknown_attempts"] != long_control["api_unknown_attempts"]
        or long_api != _decimal(long_control["api_calculated_cost_known_usd"], "long-tail control API")
        or _decimal(long_tail["pre_quality"]["api_unconfirmed_estimate_usd"], "long-tail estimate")
        != _decimal(long_control["api_unconfirmed_estimate_usd"], "long-tail control estimate")
    ):
        raise ValueError("Long-tail controls do not match the exact public records")

    pools = evidence.get("shared_cost_pools")
    if not isinstance(pools, list) or len(pools) != 1:
        raise ValueError("One long-tail VM union pool is required")
    pool = pools[0]
    if set(pool) != {"scope", "component", "allocation", "cost_usd"}:
        raise ValueError("Shared cost-pool fields do not match the public contract")
    if (
        pool["scope"] != "long_tail_pre_quality"
        or pool["component"] != "vm_direct_attributable"
        or pool["allocation"] != "single_vm_task_process_union"
    ):
        raise ValueError("Unexpected shared cost-pool definition")
    long_vm = _decimal(pool["cost_usd"], "long-tail VM union")
    long_blob = _decimal(long_tail["pre_quality"]["blob_network_cost_known_usd"], "long-tail Blob")
    long_direct = long_api + long_vm + long_blob

    joined_blob = (
        _decimal(completed["pass"]["blob_network_cost_known_usd"], "joined pass Blob")
        + _decimal(completed["normal_nonpass"]["blob_network_cost_known_usd"], "joined nonpass Blob")
    )
    included_api = cohort_api + long_api
    classified_api = {
        "pass_exact_join_usd": completed["pass"]["api_calculated_cost_known_usd"],
        "normal_nonpass_exact_join_usd": completed["normal_nonpass"]["api_calculated_cost_known_usd"],
        "completed_quality_unallocated_usd": _money(unallocated_api),
        "pre_quality_usd": _money(long_api),
        "cancelled_before_start_usd": cancelled["cancelled_before_start"]["api_calculated_cost_known_usd"],
    }
    classification_sum = sum(_decimal(value, name) for name, value in classified_api.items())
    if classification_sum != included_api:
        raise ValueError("API outcome buckets do not reconcile with the included total")
    known_blob = joined_blob + long_blob
    known_component_subtotal = included_api + long_vm + known_blob

    return {
        "schema_version": 1,
        "kind": "sanitized_outcome_cost_accounting",
        "source": {
            "path": "data/experiment/outcome-cost-evidence.json",
            "sha256": source_sha256,
            "private_paths_published": False,
            "raw_requests_or_responses_published": False,
        },
        "labels": evidence["labels"],
        "currency": "USD",
        "price_basis": evidence["price_basis"],
        "measurement_contract": {
            "quality_result_unit": "one result per trial",
            "cost_unit": "one record per started attempt plus nonduplicated shared pools",
            "provider_cost_kind": "provider usage times fixed rates",
            "invoice_reconciled": False,
            "unknown_values_are_zero": False,
        },
        "completed_cohort": {
            "tasks": cohort["tasks"],
            "conditions": total_conditions,
            "repetitions_per_condition": cohort["repetitions_per_condition"],
            "quality": {
                "pass": pass_count,
                "wrong_answer": wrong_answer_count,
                "wrong_format": wrong_format_count,
            },
            "api_calculated_cost_usd": _money(cohort_api),
            "arithmetic_api_cost_per_pass_usd": _money(arithmetic_control),
            "arithmetic_ratio_scope": "completed 104-condition API cost divided by 40 pass results",
            "program_wide_cost_per_pass_usd": None,
            "program_wide_metric_blocked_by": "exact started-attempt join is incomplete",
            "outcome_attribution": {
                "complete": missing_conditions == 0,
                "joined_conditions": joined_conditions,
                "missing_conditions": missing_conditions,
                "by_quality": {
                    "pass": completed["pass"],
                    "normal_nonpass": completed["normal_nonpass"],
                },
                "unallocated": {
                    "conditions": missing_conditions,
                    "pass": missing_pass,
                    "wrong_answer": missing_wrong_answer,
                    "wrong_format": missing_wrong_format,
                    "api_calculated_cost_known_usd": _money(unallocated_api),
                    "vm_direct_attributable_cost_usd": None,
                    "blob_network_cost_usd": None,
                    "missing_fields": [
                        "exact attempt-to-trial join",
                        "direct VM allocation",
                        "Blob/network cost by outcome",
                    ],
                },
            },
        },
        "pre_quality": {
            "quality_results": 0,
            "started_attempts": long_tail["pre_quality"]["started_attempts"],
            "technical_incomplete_attempts": long_tail["pre_quality"]["started_attempts"],
            "outcomes": long_tail["pre_quality"]["outcomes"],
            "by_outcome": long_tail_by_outcome,
            "api_calculated_cost_known_usd": _money(long_api),
            "api_unknown_attempts": long_tail["pre_quality"]["api_unknown_attempts"],
            "api_unconfirmed_estimate_usd": long_tail["pre_quality"]["api_unconfirmed_estimate_usd"],
            "vm_direct_attributable_cost_known_usd": _money(long_vm),
            "vm_allocation": "single VM task-process union; not the sum of per-attempt VM values",
            "blob_network_cost_known_usd": _money(long_blob),
            "known_direct_cost_subtotal_usd": _money(long_direct),
            "final_total_usd": None,
            "invoice_reconciled": False,
        },
        "cancelled_before_start": cancelled["cancelled_before_start"],
        "included_scope_reconciliation": {
            "api_by_classification": classified_api,
            "api_classification_sum_usd": _money(classification_sum),
            "api_included_known_total_usd": _money(included_api),
            "api_bidirectional_match": classification_sum == included_api,
            "blob_network_known_partial_usd": _money(known_blob),
            "vm_direct_known_partial_usd": _money(long_vm),
            "cross_component_known_partial_subtotal_usd": _money(known_component_subtotal),
            "cross_component_total_is_final": False,
            "component_coverage_differs": True,
        },
        "known_gaps": evidence["known_gaps"],
        "claim_limits": evidence["claim_limits"],
    }


def render(path: Path = EVIDENCE) -> str:
    evidence = _load(path)
    result = build_accounting(evidence, _sha256(path))
    return json.dumps(result, ensure_ascii=False, indent=2) + "\n"


def check(path: Path = OUTPUT) -> None:
    expected = render()
    if not path.exists():
        raise ValueError(f"Missing generated accounting file: {path}")
    if path.read_text() != expected:
        raise ValueError("Outcome-cost accounting output does not match its evidence")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    if args.check == args.print_output:
        parser.error("choose exactly one of --check or --print")
    if args.check:
        check()
    else:
        print(render(), end="")


if __name__ == "__main__":
    main()
