"""Check one private SWE-Lancer attempt without starting a worker or provider."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Mapping


ENVIRONMENT_NAME = re.compile(r"[A-Z][A-Z0-9_]*")
SHA256 = re.compile(r"[0-9a-f]{64}")
FIXED_TASK = {"task_id": "28565_1001", "split": "diamond", "task_type": "ic_swe"}
FIXED_UPSTREAM = {
    "repository": "https://github.com/openai/frontier-evals",
    "commit": "51052cede8cc608f95bb00346635e03759013e5a",
}
FIXED_IMAGE_DIGEST = "sha256:b6ee529bbc589b251d2e287aa28068ea4f7e69b3eac2927b393091ac968e7587"
FIXED_IMAGE_REFERENCE = "swelancer/swelancer_x86_28565_1001:releasev1"
FIXED_SOURCE_PINS = {
    "solver": {
        "path_env": "SWE_LANCER_SOLVER_PATH",
        "bytes": 15177,
        "sha256": "860c8bf2e65d02de9d768ff36fee6d80bb8d3dfa9955e6b83ad983ea49c62012",
    },
    "catalog": {
        "path_env": "SWE_LANCER_CATALOG_PATH",
        "bytes": 8403631,
        "sha256": "5c3a6d4570b49be0d9fced98f5b32487420b16f25c98d6658830e31fa03f049a",
    },
}
FIXED_EVIDENCE_BINDINGS = {
    "credential_permission_review": {
        "path_env": "SWE_LANCER_CREDENTIAL_REVIEW_PATH",
    },
    "network_isolation_review": {
        "path_env": "SWE_LANCER_NETWORK_REVIEW_PATH",
    },
    "cleanup_review": {
        "path_env": "SWE_LANCER_CLEANUP_REVIEW_PATH",
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_regular(path: Path) -> bytes:
    status = path.lstat()
    if not stat.S_ISREG(status.st_mode):
        raise ValueError("declared input must be a regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(descriptor)


def fingerprint(path: Path) -> dict[str, object]:
    payload = read_regular(path)
    return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def reserve_result(path: Path) -> int:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    os.fchmod(descriptor, 0o600)
    return descriptor


def write_reserved(descriptor: int, value: object) -> None:
    payload = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    view = memoryview(payload)
    offset = 0
    try:
        while offset < len(view):
            written = os.write(descriptor, view[offset:])
            if written <= 0:
                raise OSError("exclusive result write made no progress")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def load_ledger(path: Path) -> tuple[dict[str, object], dict[str, object]]:
    payload = read_regular(path)
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("admission ledger must contain one JSON object")
    return value, {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def parse_deadline(value: str, attempt_wall_seconds: int, cleanup_seconds: int) -> dict[str, object]:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    deadline = datetime.fromisoformat(normalized)
    if deadline.tzinfo is None or deadline.utcoffset() != timezone.utc.utcoffset(deadline):
        raise ValueError("deadline must be timezone-aware UTC")
    now = datetime.now(timezone.utc)
    remaining = (deadline.astimezone(timezone.utc) - now).total_seconds()
    if remaining <= cleanup_seconds:
        raise ValueError("deadline is stale or leaves no cleanup reserve")
    if remaining > attempt_wall_seconds:
        raise ValueError("deadline exceeds the fixed attempt wall limit")
    return {
        "admitted_at_utc": now.isoformat().replace("+00:00", "Z"),
        "absolute_deadline_utc": deadline.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "attempt_wall_seconds": attempt_wall_seconds,
        "cleanup_reserve_seconds": cleanup_seconds,
    }


def _mapping(ledger: Mapping[str, object], name: str, missing: set[str]) -> Mapping[str, object]:
    value = ledger.get(name)
    if not isinstance(value, Mapping):
        missing.add(name)
        return {}
    return value


def _required(mapping: Mapping[str, object], prefix: str, names: tuple[str, ...], missing: set[str]) -> None:
    for name in names:
        if mapping.get(name) is None or mapping.get(name) == "":
            missing.add(f"{prefix}.{name}")


def _positive_decimal(value: object) -> bool:
    try:
        parsed = Decimal(str(value))
        return parsed.is_finite() and parsed > 0
    except (InvalidOperation, ValueError):
        return False


def _pin_checks(
    pins: object,
    category: str,
    environment: Mapping[str, str],
    missing: set[str],
    expected: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    if not isinstance(pins, list) or not pins:
        missing.add(category)
        return []
    records = []
    names: set[str] = set()
    for index, pin in enumerate(pins):
        prefix = f"{category}[{index}]"
        if not isinstance(pin, Mapping):
            missing.add(prefix)
            continue
        name = pin.get("name")
        path_environment = pin.get("path_env")
        expected_bytes = pin.get("bytes")
        expected_sha256 = pin.get("sha256")
        if not isinstance(name, str) or not name or name in names:
            missing.add(f"{prefix}.name")
            continue
        names.add(name)
        expected_pin = expected.get(name)
        if expected_pin is None:
            missing.add(f"{category}.set")
            expected_pin = {}
        if not isinstance(path_environment, str) or not ENVIRONMENT_NAME.fullmatch(path_environment):
            missing.add(f"{prefix}.path_env")
            continue
        if path_environment != expected_pin.get("path_env"):
            missing.add(f"{category}.{name}.path_env")
        if type(expected_bytes) is not int or expected_bytes <= 0:
            missing.add(f"{prefix}.bytes")
        if not isinstance(expected_sha256, str) or not SHA256.fullmatch(expected_sha256):
            missing.add(f"{prefix}.sha256")
        for field in ("bytes", "sha256"):
            if field in expected_pin and pin.get(field) != expected_pin[field]:
                missing.add(f"{category}.{name}.{field}")
        supplied = environment.get(path_environment)
        record = {
            "name": name,
            "path_environment_name": path_environment,
            "path_value_recorded": False,
            "present": bool(supplied),
            "expected": {"bytes": expected_bytes, "sha256": expected_sha256},
            "actual": None,
            "match": False,
        }
        if not supplied:
            missing.add(f"environment.{path_environment}.present")
        elif type(expected_bytes) is int and isinstance(expected_sha256, str):
            try:
                actual = fingerprint(Path(supplied))
            except (OSError, ValueError):
                missing.add(f"{category}.{name}.regular_file")
            else:
                record["actual"] = actual
                record["match"] = actual == {
                    "bytes": expected_bytes,
                    "sha256": expected_sha256,
                }
                if not record["match"]:
                    missing.add(f"{category}.{name}.fingerprint")
        records.append(record)
    if names != set(expected):
        missing.add(f"{category}.set")
    return records


def check_admission(
    ledger: Mapping[str, object],
    ledger_fingerprint: Mapping[str, object],
    deadline_utc: str,
    environment: Mapping[str, str],
) -> dict[str, object]:
    missing: set[str] = set()
    if ledger.get("schema_version") != 1:
        missing.add("schema_version")
    if ledger.get("kind") != "swe_lancer_one_trace_admission_template":
        missing.add("kind")

    selection = _mapping(ledger, "selection", missing)
    for name, expected in FIXED_TASK.items():
        if selection.get(name) != expected:
            missing.add(f"selection.{name}")
    if selection.get("task_count") != 1:
        missing.add("selection.task_count")

    source = _mapping(ledger, "source", missing)
    for name, expected in FIXED_UPSTREAM.items():
        if source.get(name) != expected:
            missing.add(f"source.{name}")
    source_pins = _pin_checks(
        source.get("pins"), "source.pins", environment, missing, FIXED_SOURCE_PINS
    )

    provider = _mapping(ledger, "provider", missing)
    if provider.get("name") != "openai":
        missing.add("provider.name")
    if provider.get("model_setting") != "openai/gpt-4o":
        missing.add("provider.model_setting")
    credential_name = provider.get("credential_env")
    if credential_name != "OPENAI_API_KEY":
        missing.add("provider.credential_env")
    credential_present = isinstance(credential_name, str) and credential_name in environment
    if not credential_present:
        missing.add("environment.OPENAI_API_KEY.present")
    _required(
        provider,
        "provider",
        ("reported_model_revision", "price_source_url", "price_source_revision_or_retrieved_at"),
        missing,
    )
    for name in ("input_usd_per_million_tokens", "output_usd_per_million_tokens"):
        if not _positive_decimal(provider.get(name)):
            missing.add(f"provider.{name}")

    sandbox = _mapping(ledger, "sandbox", missing)
    if sandbox.get("runtime") != "nanoeval_alcatraz.alcatraz_computer_interface:AlcatrazComputerRuntime":
        missing.add("sandbox.runtime")
    if sandbox.get("environment") != "alcatraz.clusters.local:LocalConfig":
        missing.add("sandbox.environment")
    if sandbox.get("image_manifest_digest") != FIXED_IMAGE_DIGEST:
        missing.add("sandbox.image_manifest_digest")
    if sandbox.get("image_reference") != FIXED_IMAGE_REFERENCE:
        missing.add("sandbox.image_reference")
    endpoint_name = sandbox.get("endpoint_env")
    if endpoint_name != "SWE_LANCER_DOCKER_HOST":
        missing.add("sandbox.endpoint_env")
        endpoint_present = False
    else:
        endpoint_present = endpoint_name in environment
        if not endpoint_present:
            missing.add(f"environment.{endpoint_name}.present")
    evidence_pins = _pin_checks(
        sandbox.get("evidence_pins"),
        "sandbox.evidence_pins",
        environment,
        missing,
        FIXED_EVIDENCE_BINDINGS,
    )

    approval = _mapping(ledger, "approval", missing)
    if approval.get("cost_approved") is not True:
        missing.add("approval.cost_approved")
    if approval.get("execution_approved") is not True:
        missing.add("approval.execution_approved")
    if not isinstance(approval.get("approval_record"), str) or not approval.get("approval_record"):
        missing.add("approval.approval_record")

    limits = _mapping(ledger, "limits", missing)
    expected_limits = {
        "attempt_cost_cap_usd": "20.00",
        "run_cost_cap_usd": "20.00",
        "attempt_wall_seconds": 4920,
        "cleanup_reserve_seconds": 120,
        "logical_request_timeout_seconds": 1200,
        "http_attempt_limit": 40,
        "sdk_retry_count": 0,
    }
    for name, expected in expected_limits.items():
        if limits.get(name) != expected:
            missing.add(f"limits.{name}")
    try:
        deadline = parse_deadline(
            deadline_utc,
            expected_limits["attempt_wall_seconds"],
            expected_limits["cleanup_reserve_seconds"],
        )
    except (TypeError, ValueError):
        missing.add("deadline.fresh_absolute_utc")
        deadline = None

    return {
        "schema_version": 1,
        "kind": "swe_lancer_one_trace_admission_check",
        "recorded_at_utc": utc_now(),
        "status": "ready" if not missing else "not_ready",
        "ready": not missing,
        "missing_or_invalid": sorted(missing),
        "ledger": dict(ledger_fingerprint),
        "selection": FIXED_TASK,
        "source_pins": source_pins,
        "provider": {
            "name": provider.get("name"),
            "model_setting": provider.get("model_setting"),
            "credential_environment_name": credential_name,
            "credential_present": credential_present,
            "credential_value_recorded": False,
            "reported_model_revision": provider.get("reported_model_revision"),
        },
        "sandbox": {
            "endpoint_environment_name": endpoint_name,
            "endpoint_present": endpoint_present,
            "endpoint_value_recorded": False,
            "image_manifest_digest": sandbox.get("image_manifest_digest"),
            "evidence_pins": evidence_pins,
        },
        "deadline": deadline,
        "limits": expected_limits,
        "side_effects": {
            "worker_or_model_started": False,
            "provider_called": False,
            "sandbox_started": False,
            "container_or_vm_started": False,
            "network_used": False,
        },
    }


def validate_public_evaluation(value: Mapping[str, object]) -> None:
    if value.get("kind") != "swe_lancer_third_benchmark_candidate_evaluation":
        raise ValueError("unexpected SWE-Lancer evaluation kind")
    if value.get("candidate_conclusion") != "defer" or value.get("trace_obtained") is not False:
        raise ValueError("public evaluation must preserve the deferred no-trace conclusion")
    attempt = value.get("attempt")
    counts = value.get("counts")
    usage = value.get("provider_usage")
    cost = value.get("cost")
    privacy = value.get("privacy")
    observations = value.get("direct_observations")
    selection = value.get("selection")
    pins = value.get("pins")
    if not all(
        isinstance(item, Mapping)
        for item in (attempt, counts, usage, cost, privacy, observations, selection, pins)
    ):
        raise ValueError("public evaluation mappings are incomplete")
    if (
        attempt.get("status") != "not_ready"
        or attempt.get("exit_code") != 2
        or attempt.get("outcome") != "technical_preflight_failure"
        or attempt.get("grader_status") != "not_started"
        or attempt.get("grader_outcome") is not None
    ):
        raise ValueError("public attempt outcome drift")
    expected_counts = {
        "logical_model_requests": 0,
        "http_attempts": 0,
        "model_visible_message_snapshots": 0,
        "tool_calls": 0,
        "tool_results": 0,
        "retries": 0,
        "trace_events": 0,
        "provider_usage_records": 0,
    }
    if counts != expected_counts:
        raise ValueError("no provider, tool, retry, usage, or trace count may be nonzero")
    if usage != {
        "status": "not_observed",
        "input_tokens": None,
        "output_tokens": None,
        "usage_is_invoice": False,
    }:
        raise ValueError("provider usage boundary drift")
    if (
        cost.get("calculated_provider_cost_usd") != "0.00"
        or cost.get("calculation_basis") != "zero provider requests started"
        or cost.get("invoice_observed") is not False
        or cost.get("host_compute_cost_measured") is not False
        or cost.get("input_unit_price_usd_per_million_tokens") is not None
        or cost.get("output_unit_price_usd_per_million_tokens") is not None
        or cost.get("price_source") is not None
    ):
        raise ValueError("public cost boundary drift")
    expected_privacy = {
        "container_identifier_included": False,
        "credential_value_included": False,
        "private_endpoint_included": False,
        "private_path_included": False,
        "raw_messages_included": False,
        "reference_answer_included": False,
        "task_body_included": False,
    }
    if privacy != expected_privacy:
        raise ValueError("private payload marker is true")
    expected_observations = {
        "container_or_vm_started": False,
        "image_body_downloaded": False,
        "image_manifest_head_http_status": 200,
        "provider_called": False,
        "result_no_clobber_verified": True,
        "sandbox_started": False,
        "source_catalog_task_and_runtime_pins_matched": True,
        "worker_or_model_started": False,
    }
    if observations != expected_observations:
        raise ValueError("public direct-observation boundary drift")
    if any(selection.get(name) != expected for name, expected in FIXED_TASK.items()):
        raise ValueError("public task selection drift")
    if selection.get("selection_fixed_before_task_content") is not True:
        raise ValueError("public task selection timing drift")
    if (
        pins.get("upstream_commit") != FIXED_UPSTREAM["commit"]
        or pins.get("solver_sha256") != FIXED_SOURCE_PINS["solver"]["sha256"]
        or pins.get("catalog_sha256") != FIXED_SOURCE_PINS["catalog"]["sha256"]
        or pins.get("image_manifest_digest") != FIXED_IMAGE_DIGEST
    ):
        raise ValueError("public source pin drift")
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    for marker in ("/tmp/", "/home/", "Bearer ", "Authorization:"):
        if marker in serialized:
            raise ValueError("public evaluation contains a private-path or credential marker")
    if re.search(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{8,}", serialized):
        raise ValueError("public evaluation contains an API-key-shaped value")


def run(
    ledger_path: Path,
    result_path: Path,
    deadline_utc: str,
    environment: Mapping[str, str] | None = None,
) -> int:
    try:
        descriptor = reserve_result(result_path)
    except FileExistsError:
        print(json.dumps({"status": "error", "error": "result_collision", "side_effects_started": 0}))
        return 3
    except OSError:
        print(
            json.dumps(
                {"status": "error", "error": "result_reservation_failed", "side_effects_started": 0}
            )
        )
        return 3
    try:
        ledger, ledger_fingerprint = load_ledger(ledger_path)
        result = check_admission(
            ledger,
            ledger_fingerprint,
            deadline_utc,
            environment if environment is not None else os.environ,
        )
        code = 0 if result["ready"] else 2
    except (InvalidOperation, json.JSONDecodeError, OSError, TypeError, ValueError) as error:
        result = {
            "schema_version": 1,
            "kind": "swe_lancer_one_trace_admission_check",
            "recorded_at_utc": utc_now(),
            "status": "error",
            "ready": False,
            "error_type": type(error).__name__,
            "side_effects": {
                "worker_or_model_started": False,
                "provider_called": False,
                "sandbox_started": False,
                "container_or_vm_started": False,
                "network_used": False,
            },
        }
        code = 3
    write_reserved(descriptor, result)
    return code


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--deadline-utc", required=True)
    args = parser.parse_args(arguments)
    return run(args.ledger, args.result, args.deadline_utc)


if __name__ == "__main__":
    raise SystemExit(main())
