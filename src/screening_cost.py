"""Calculate screening costs without replacing missing charges with zero."""

from __future__ import annotations

from collections import defaultdict
import math


def provider_cost(events: list[dict], transport_trial_id: str) -> dict:
    started = {}
    responses = {}
    for event in events:
        if event.get("trial_id") != transport_trial_id:
            continue
        if event.get("event") == "attempt_started":
            key = (event.get("request"), event.get("attempt"))
            if key in started or any(type(value) is not int or value < 1 for value in key):
                raise ValueError("Provider attempt identity is invalid or duplicated")
            started[key] = event
        elif event.get("event") == "http":
            key = (event.get("request"), event.get("attempt"))
            if key in responses:
                raise ValueError("Provider response identity is duplicated")
            responses[key] = event
    if set(responses) - set(started):
        raise ValueError("Provider response lacks a matching dispatch record")
    records = []
    for key, dispatch in sorted(started.items()):
        response = responses.get(key)
        value = None if response is None else response.get("calculated_cost_usd")
        known = type(value) in (int, float) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
        if value is not None and not known:
            raise ValueError("Provider calculated cost is invalid")
        records.append({
            "logical_request": key[0],
            "http_attempt": key[1],
            "request_sha256": dispatch.get("request_sha256"),
            "http_status": None if response is None else response.get("status"),
            "response_sha256": None if response is None else response.get("response_sha256"),
            "provider_request_id": None if response is None else response.get("provider_response_id"),
            "tokens": None if response is None else response.get("tokens"),
            "calculated_cost_usd": value if known else None,
            "billing_unknown": not known,
        })
    known = [record["calculated_cost_usd"] for record in records if not record["billing_unknown"]]
    return {
        "kind": "provider_usage_times_fixed_rates_not_invoice_reconciliation",
        "currency": "USD",
        "http_attempts": len(records),
        "known_attempts": len(known),
        "unknown_attempts": len(records) - len(known),
        "known_cost_usd": sum(known),
        "calculated_cost_usd": sum(known) if len(known) == len(records) else None,
        "requests": records,
    }


def allocate_active_vm_cost(intervals: list[dict], hourly_rate_usd: float) -> dict:
    if type(hourly_rate_usd) not in (int, float) or isinstance(hourly_rate_usd, bool) or not math.isfinite(hourly_rate_usd) or hourly_rate_usd < 0:
        raise ValueError("VM hourly rate must be finite and nonnegative")
    points = []
    seen = set()
    for interval in intervals:
        attempt_id = interval.get("attempt_id")
        start = interval.get("started_epoch")
        finish = interval.get("finished_epoch")
        if not isinstance(attempt_id, str) or not attempt_id or attempt_id in seen:
            raise ValueError("VM allocation needs unique attempt identifiers")
        if any(type(value) not in (int, float) or isinstance(value, bool) or not math.isfinite(value) for value in (start, finish)):
            raise ValueError("VM allocation timestamps must be finite")
        if finish < start:
            raise ValueError("VM allocation interval finishes before it starts")
        seen.add(attempt_id)
        if finish > start:
            points.extend(((start, 1, attempt_id), (finish, -1, attempt_id)))
    points.sort(key=lambda point: (point[0], point[1]))
    allocations = defaultdict(float)
    active = set()
    prior = None
    total_seconds = 0.0
    for at, direction, attempt_id in points:
        if prior is not None and at > prior and active:
            duration = at - prior
            total_seconds += duration
            share = duration / len(active)
            for active_attempt in active:
                allocations[active_attempt] += share
        if direction == -1:
            active.discard(attempt_id)
        else:
            active.add(attempt_id)
        prior = at
    rate_per_second = hourly_rate_usd / 3600
    records = {
        attempt_id: {
            "allocated_active_seconds": allocations[attempt_id],
            "calculated_cost_usd": allocations[attempt_id] * rate_per_second,
        }
        for attempt_id in sorted(seen)
    }
    return {
        "kind": "equal_share_of_each_concurrent_active_vm_segment",
        "currency": "USD",
        "hourly_rate_usd": hourly_rate_usd,
        "union_active_seconds": total_seconds,
        "calculated_cost_usd": total_seconds * rate_per_second,
        "attempts": records,
        "reconciles": math.isclose(
            sum(record["calculated_cost_usd"] for record in records.values()),
            total_seconds * rate_per_second,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ),
    }


def _operation_component(states: list[dict], names: tuple[str, ...], rate_per_10k_usd: float) -> dict:
    if type(rate_per_10k_usd) not in (int, float) or isinstance(rate_per_10k_usd, bool):
        raise ValueError("Blob operation rate must be a number")
    if not math.isfinite(rate_per_10k_usd) or rate_per_10k_usd < 0:
        raise ValueError("Blob operation rate must be finite and nonnegative")
    started = succeeded = unknown_records = 0
    for state in states:
        operations = state.get("operations")
        if not isinstance(operations, dict):
            unknown_records += 1
            continue
        for name in names:
            operation = operations.get(name)
            if not isinstance(operation, dict):
                unknown_records += 1
                continue
            current_started = operation.get("started")
            current_succeeded = operation.get("succeeded")
            if (
                type(current_started) is not int
                or type(current_succeeded) is not int
                or current_started < 0
                or not 0 <= current_succeeded <= current_started
            ):
                raise ValueError("Blob operation counts are invalid")
            started += current_started
            succeeded += current_succeeded
    ambiguous = started - succeeded
    rate = rate_per_10k_usd / 10_000
    exact = ambiguous == 0 and unknown_records == 0
    return {
        "rate_per_10000_operations_usd": rate_per_10k_usd,
        "started_operations": started,
        "confirmed_successful_operations": succeeded,
        "ambiguous_operations": ambiguous,
        "items_missing_operation_records": unknown_records,
        "confirmed_cost_usd": succeeded * rate,
        "maximum_started_cost_usd": started * rate,
        "calculated_cost_usd": succeeded * rate if exact else None,
    }


def blob_operation_cost(
    states: list[dict],
    write_per_10k_usd: float,
    read_per_10k_usd: float,
    network_per_gb_usd: float,
) -> dict:
    writes = _operation_component(states, ("payload_write", "manifest_write"), write_per_10k_usd)
    reads = _operation_component(
        states, ("payload_verify_read", "manifest_verify_read"), read_per_10k_usd
    )
    if type(network_per_gb_usd) not in (int, float) or isinstance(network_per_gb_usd, bool):
        raise ValueError("Network transfer rate must be a number")
    if not math.isfinite(network_per_gb_usd) or network_per_gb_usd < 0:
        raise ValueError("Network transfer rate must be finite and nonnegative")
    confirmed_bytes = maximum_started_bytes = 0
    byte_records_complete = True
    for state in states:
        payload_bytes = (state.get("payload") or {}).get("bytes")
        manifest_bytes = state.get("manifest_bytes")
        operations = state.get("operations")
        if type(payload_bytes) is not int or payload_bytes < 0 or not isinstance(operations, dict):
            byte_records_complete = False
            continue
        sizes = {
            "payload_write": payload_bytes,
            "payload_verify_read": payload_bytes,
            "manifest_write": manifest_bytes,
            "manifest_verify_read": manifest_bytes,
        }
        for name, size in sizes.items():
            operation = operations.get(name)
            if not isinstance(operation, dict):
                byte_records_complete = False
                continue
            started = operation.get("started")
            succeeded = operation.get("succeeded")
            if type(started) is not int or type(succeeded) is not int:
                byte_records_complete = False
                continue
            if started and (type(size) is not int or size < 0):
                byte_records_complete = False
                continue
            if type(size) is int:
                confirmed_bytes += succeeded * size
                maximum_started_bytes += started * size
    network_exact = network_per_gb_usd == 0 or (
        byte_records_complete
        and writes["ambiguous_operations"] == 0
        and reads["ambiguous_operations"] == 0
        and writes["items_missing_operation_records"] == 0
        and reads["items_missing_operation_records"] == 0
    )
    network_confirmed = confirmed_bytes / 1_000_000_000 * network_per_gb_usd
    network = {
        "rate_per_gb_usd": network_per_gb_usd,
        "confirmed_bytes": confirmed_bytes,
        "maximum_started_bytes": maximum_started_bytes if byte_records_complete else None,
        "byte_records_complete": byte_records_complete,
        "confirmed_cost_usd": network_confirmed,
        "calculated_cost_usd": network_confirmed if network_exact else None,
    }
    components = {
        "blob_writes": writes["calculated_cost_usd"],
        "blob_verification_reads": reads["calculated_cost_usd"],
        "network_transfer": network["calculated_cost_usd"],
    }
    known = writes["confirmed_cost_usd"] + reads["confirmed_cost_usd"] + network_confirmed
    return {
        "kind": "blob_and_network_operations_from_local_spool_state",
        "currency": "USD",
        "writes": writes,
        "verification_reads": reads,
        "network_transfer": network,
        "calculated_cost_usd": sum(components.values()) if all(
            value is not None for value in components.values()
        ) else None,
        "confirmed_cost_usd": known,
        "unknown_component_count": sum(value is None for value in components.values()),
        "items_not_remotely_verified": sum(
            state.get("upload_state") != "uploaded" or not state.get("remote_verified_at")
            for state in states
        ),
        "storage_retention_cost_included": False,
    }


def blob_write_cost(states: list[dict], write_per_10k_usd: float) -> dict:
    return _operation_component(states, ("payload_write", "manifest_write"), write_per_10k_usd)


def combined_direct_cost(provider: dict, vm: dict, blob: dict) -> dict:
    components = {
        "provider": provider.get("calculated_cost_usd"),
        "active_vm": vm.get("calculated_cost_usd"),
        "blob_and_network": blob.get("calculated_cost_usd"),
    }
    known = {
        "provider": provider.get("known_cost_usd", 0),
        "active_vm": vm.get("calculated_cost_usd", 0),
        "blob_and_network": blob.get("confirmed_cost_usd", 0),
    }
    unknown = sorted(name for name, value in components.items() if value is None)
    return {
        "kind": "direct_attributable_variable_cost",
        "currency": "USD",
        "calculated_cost_usd": sum(components.values()) if not unknown else None,
        "known_cost_subtotal_usd": sum(known.values()),
        "unknown_components": unknown,
        "components": components,
        "excluded_separate_costs": [
            "shared_vm_idle", "approval_wait", "one_time_setup", "blob_storage_retention", "network_without_meter",
        ],
    }
