"""Validate the private SWE-Lancer carrier before any paid dispatch."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re

from . import swe_lancer_admission as admission


ROOT = Path(__file__).resolve().parents[1]
DEFINITION_PATH = ROOT / "config/swe-lancer-carrier.json"
SHA256 = re.compile(r"[0-9a-f]{64}")
ENVIRONMENT_NAME = re.compile(r"[A-Z][A-Z0-9_]*")
BOUNDED_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
IDENTITY_FIELDS = (
    "SANCTIONED_SWE_LANCER_CARRIER_COMMAND",
    "SANCTIONED_SWE_LANCER_CARRIER_IDENTITY_KIND",
    "SANCTIONED_SWE_LANCER_CARRIER_IDENTITY_SOURCE",
    "SANCTIONED_SWE_LANCER_CARRIER_IDENTITY_SHA256",
    "SANCTIONED_SWE_LANCER_CARRIER_OWNER",
)
EXPECTED_COMMAND = {
    "executable_environment_name": "SWE_LANCER_RUNTIME_PYTHON",
    "arguments": ["-m", "src.swe_lancer_carrier"],
}
EXPECTED_INPUT_ENVIRONMENTS = {
    "attestation": "SWE_LANCER_CARRIER_ATTESTATION",
    "ledger": "SWE_LANCER_ADMISSION_LEDGER",
    "provider_contract_receipt": "SWE_LANCER_PROVIDER_CONTRACT_RECEIPT",
    "price_receipt": "SWE_LANCER_PRICE_RECEIPT",
    "outbound_receipt": "SWE_LANCER_OUTBOUND_RECEIPT",
    "deadline": "SWE_LANCER_DEADLINE_UTC",
    "output": "SWE_LANCER_ADMISSION_RESULT",
}
EXPECTED_ADMISSION_ENVIRONMENTS = {
    "provider_credential": "OPENAI_API_KEY",
    "sandbox_endpoint": "SWE_LANCER_DOCKER_HOST",
    "solver": "SWE_LANCER_SOLVER_PATH",
    "catalog": "SWE_LANCER_CATALOG_PATH",
    "credential_review": "SWE_LANCER_CREDENTIAL_REVIEW_PATH",
    "network_review": "SWE_LANCER_NETWORK_REVIEW_PATH",
    "cleanup_review": "SWE_LANCER_CLEANUP_REVIEW_PATH",
}
FIXED_IMAGE_CONFIG_DIGEST = (
    "sha256:3ac386d8f793eb2c3fdef76766b551bb2c04da8b7dd9703a01b561c293b82400"
)
INPUT_FINGERPRINT_NAMES = {
    "ledger",
    "provider_contract_receipt",
    "price_receipt",
    "outbound_receipt",
}
DEFINITION_FIELDS = {
    "schema_version",
    "kind",
    *IDENTITY_FIELDS,
    "input_environment_names",
    "admission_environment_names",
    "inline_values",
    "provider_model_api_grader_calls",
}
ATTESTATION_FIELDS = {
    "schema_version",
    "kind",
    "observed_at_utc",
    "valid_through_utc",
    "definition_sha256",
    "input_fingerprints",
    *IDENTITY_FIELDS,
}
PROVIDER_RECEIPT_FIELDS = {
    "schema_version",
    "kind",
    "observed_at_utc",
    "valid_through_utc",
    "ledger_sha256",
    "provider_name",
    "model_setting",
    "deployment_identity_sha256",
    "api_version",
    "reported_model_revision",
    "credential_environment_name",
    "endpoint_environment_name",
    "credential_permission_verified",
    "credential_value_recorded",
    "endpoint_value_recorded",
    "provider_model_api_calls",
}
PRICE_RECEIPT_FIELDS = {
    "schema_version",
    "kind",
    "observed_at_utc",
    "valid_through_utc",
    "ledger_sha256",
    "currency",
    "input_usd_per_million_tokens",
    "output_usd_per_million_tokens",
    "price_source_url",
    "price_source_revision_or_retrieved_at",
    "provider_model_api_calls",
}
OUTBOUND_RECEIPT_FIELDS = {
    "schema_version",
    "kind",
    "observed_at_utc",
    "valid_through_utc",
    "ledger_sha256",
    "carrier_instance_identity_sha256",
    "runtime_kind",
    "platform",
    "image_manifest_digest",
    "image_config_digest",
    "paid_provider_outbound_verified",
    "cleanup_contract_verified",
    "credential_value_recorded",
    "endpoint_value_recorded",
    "provider_model_api_grader_calls",
    "network_calls",
    "survivor_count",
}
ADMISSION_SIDE_EFFECT_FIELDS = (
    "worker_or_model_started",
    "provider_called",
    "sandbox_started",
    "container_or_vm_started",
    "network_used",
)


class CarrierFailure(ValueError):
    def __init__(self, code: str, status: str = "invalid", source_error: bool = False):
        super().__init__(code)
        self.code = code
        self.status = status
        self.source_error = source_error


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def payload_fingerprint(payload: bytes) -> dict[str, object]:
    return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def parse_utc(value: object, code: str) -> datetime:
    if not isinstance(value, str):
        raise CarrierFailure(code)
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise CarrierFailure(code) from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise CarrierFailure(code)
    return parsed.astimezone(timezone.utc)


def validate_freshness(value: Mapping[str, object], current_time: datetime, prefix: str) -> None:
    observed = parse_utc(value.get("observed_at_utc"), f"{prefix}.observed_at_utc")
    valid_through = parse_utc(value.get("valid_through_utc"), f"{prefix}.valid_through_utc")
    if observed > current_time or valid_through <= observed or current_time > valid_through:
        raise CarrierFailure(f"{prefix}.freshness", "stale")


def project_path(root: Path, value: object) -> Path:
    if not isinstance(value, str):
        raise CarrierFailure("project_definition.identity_source", source_error=True)
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != value:
        raise CarrierFailure("project_definition.identity_source", source_error=True)
    return root / relative


def validate_definition(
    value: object,
    payload: bytes,
    root: Path,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    if not isinstance(value, dict) or set(value) != DEFINITION_FIELDS:
        raise CarrierFailure("project_definition.fields", source_error=True)
    if value["schema_version"] != 1 or value["kind"] != "swe_lancer_private_carrier_definition":
        raise CarrierFailure("project_definition.identity", source_error=True)
    if value[IDENTITY_FIELDS[0]] != EXPECTED_COMMAND:
        raise CarrierFailure("project_definition.command", source_error=True)
    if value[IDENTITY_FIELDS[1]] != "repository_regular_file":
        raise CarrierFailure("project_definition.identity_kind", source_error=True)
    if value[IDENTITY_FIELDS[2]] != "src/swe_lancer_carrier.py":
        raise CarrierFailure("project_definition.identity_source", source_error=True)
    if value[IDENTITY_FIELDS[4]] != "runtime_owner":
        raise CarrierFailure("project_definition.owner", source_error=True)
    if value["input_environment_names"] != EXPECTED_INPUT_ENVIRONMENTS:
        raise CarrierFailure("project_definition.input_environment_names", source_error=True)
    if value["admission_environment_names"] != EXPECTED_ADMISSION_ENVIRONMENTS:
        raise CarrierFailure("project_definition.admission_environment_names", source_error=True)
    environment_names = {
        EXPECTED_COMMAND["executable_environment_name"],
        *EXPECTED_INPUT_ENVIRONMENTS.values(),
        *EXPECTED_ADMISSION_ENVIRONMENTS.values(),
    }
    if len(environment_names) != 15 or any(
        not ENVIRONMENT_NAME.fullmatch(name) for name in environment_names
    ):
        raise CarrierFailure("project_definition.environment_names", source_error=True)
    if value["inline_values"] is not False or value["provider_model_api_grader_calls"] != 0:
        raise CarrierFailure("project_definition.zero_call_contract", source_error=True)
    declared_sha256 = value[IDENTITY_FIELDS[3]]
    if not isinstance(declared_sha256, str) or not SHA256.fullmatch(declared_sha256):
        raise CarrierFailure("project_definition.identity_sha256", source_error=True)
    source = project_path(root, value[IDENTITY_FIELDS[2]])
    try:
        source_payload = admission.read_regular(source)
    except (OSError, ValueError) as error:
        raise CarrierFailure("project_definition.identity_regular_file", source_error=True) from error
    source_fingerprint = payload_fingerprint(source_payload)
    if source_fingerprint["sha256"] != declared_sha256:
        raise CarrierFailure("project_definition.identity_sha256", "wrong_source", True)
    return value, payload_fingerprint(payload), source_fingerprint


def load_definition(
    path: Path,
    root: Path,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    try:
        payload = admission.read_regular(path)
        value = json.loads(payload)
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise CarrierFailure("project_definition.regular_json", source_error=True) from error
    return validate_definition(value, payload, root)


def validate_fingerprint(value: object, code: str) -> None:
    if not isinstance(value, Mapping) or set(value) != {"bytes", "sha256"}:
        raise CarrierFailure(code)
    if type(value["bytes"]) is not int or value["bytes"] <= 0:
        raise CarrierFailure(code)
    if not isinstance(value["sha256"], str) or not SHA256.fullmatch(value["sha256"]):
        raise CarrierFailure(code)


def validate_attestation(
    value: object,
    definition: Mapping[str, object],
    definition_fingerprint: Mapping[str, object],
    current_time: datetime,
) -> None:
    if not isinstance(value, Mapping) or set(value) != ATTESTATION_FIELDS:
        raise CarrierFailure("context_attestation.fields")
    if value["schema_version"] != 1 or value["kind"] != "swe_lancer_private_carrier_attestation":
        raise CarrierFailure("context_attestation.identity")
    if value["definition_sha256"] != definition_fingerprint["sha256"]:
        raise CarrierFailure("context_attestation.definition_sha256", "wrong_source")
    for field in IDENTITY_FIELDS:
        if value[field] != definition[field]:
            raise CarrierFailure(f"context_attestation.{field}", "wrong_source")
    fingerprints = value["input_fingerprints"]
    if not isinstance(fingerprints, Mapping) or set(fingerprints) != INPUT_FINGERPRINT_NAMES:
        raise CarrierFailure("context_attestation.input_fingerprints")
    for name in sorted(INPUT_FINGERPRINT_NAMES):
        validate_fingerprint(fingerprints[name], f"context_attestation.input_fingerprints.{name}")
    validate_freshness(value, current_time, "context_attestation")


def environment_presence(
    definition: Mapping[str, object] | None,
    environment: Mapping[str, str],
) -> dict[str, bool]:
    names = {
        EXPECTED_COMMAND["executable_environment_name"],
        *EXPECTED_INPUT_ENVIRONMENTS.values(),
        *EXPECTED_ADMISSION_ENVIRONMENTS.values(),
    }
    if definition is not None:
        command = definition[IDENTITY_FIELDS[0]]
        inputs = definition["input_environment_names"]
        admission_names = definition["admission_environment_names"]
        if isinstance(command, Mapping) and isinstance(inputs, Mapping) and isinstance(
            admission_names, Mapping
        ):
            names = {
                command["executable_environment_name"],
                *inputs.values(),
                *admission_names.values(),
            }
    return {name: name in environment for name in sorted(names)}


def base_record(current_time: datetime, presence: dict[str, bool]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "swe_lancer_private_carrier_context_check",
        "recorded_at_utc": format_utc(current_time),
        "status": "not_ready",
        "ready": False,
        "context_status": "invalid",
        "missing_or_invalid": [],
        "context": None,
        "environment_presence": presence,
        "values_stored": False,
        "receipts": None,
        "admission": None,
        "side_effects": {
            "runtime_input_files_read": 0,
            "admission_invocations": 0,
            "worker_or_model_started": False,
            "provider_called": False,
            "provider_model_api_grader_calls": 0,
            "sandbox_started": False,
            "container_or_vm_started": False,
            "network_used": False,
            "credential_values_read": 0,
            "endpoint_values_read": 0,
        },
    }


def failure_record(
    current_time: datetime,
    environment: Mapping[str, str],
    failure: CarrierFailure,
    definition: Mapping[str, object] | None = None,
    context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    result = base_record(current_time, environment_presence(definition, environment))
    result["context_status"] = failure.status
    result["missing_or_invalid"] = [failure.code]
    result["context"] = dict(context) if context is not None else None
    result["failure_class"] = "source" if failure.source_error else "admission"
    return result


def load_private_input(
    environment: Mapping[str, str],
    environment_name: str,
    label: str,
) -> tuple[bytes, dict[str, object]]:
    raw_path = environment.get(environment_name)
    if not isinstance(raw_path, str) or not raw_path:
        raise CarrierFailure(f"environment.{environment_name}.present", "missing")
    try:
        payload = admission.read_regular(Path(raw_path))
    except (OSError, ValueError) as error:
        raise CarrierFailure(f"input.{label}.regular_file") from error
    return payload, payload_fingerprint(payload)


def parse_json_mapping(payload: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CarrierFailure(f"{label}.json") from error
    if not isinstance(value, dict):
        raise CarrierFailure(f"{label}.object")
    return value


def require_nonempty(value: object, code: str) -> str:
    if not isinstance(value, str) or not value:
        raise CarrierFailure(code)
    return value


def require_identifier(value: object, code: str) -> str:
    if not isinstance(value, str) or not BOUNDED_IDENTIFIER.fullmatch(value):
        raise CarrierFailure(code)
    return value


def require_positive_decimal(value: object, code: str) -> str:
    if not isinstance(value, str):
        raise CarrierFailure(code)
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise CarrierFailure(code) from error
    if not parsed.is_finite() or parsed <= 0:
        raise CarrierFailure(code)
    return value


def validate_provider_receipt(
    value: Mapping[str, object],
    ledger: Mapping[str, object],
    ledger_sha256: str,
    current_time: datetime,
) -> dict[str, object]:
    prefix = "provider_contract_receipt"
    if set(value) != PROVIDER_RECEIPT_FIELDS:
        raise CarrierFailure(f"{prefix}.fields")
    if value["schema_version"] != 1 or value["kind"] != "swe_lancer_provider_contract_receipt":
        raise CarrierFailure(f"{prefix}.identity")
    validate_freshness(value, current_time, prefix)
    provider = ledger.get("provider")
    sandbox = ledger.get("sandbox")
    if not isinstance(provider, Mapping) or not isinstance(sandbox, Mapping):
        raise CarrierFailure("admission_ledger.provider_contract")
    expected = {
        "ledger_sha256": ledger_sha256,
        "provider_name": provider.get("name"),
        "model_setting": provider.get("model_setting"),
        "reported_model_revision": provider.get("reported_model_revision"),
        "credential_environment_name": provider.get("credential_env"),
        "endpoint_environment_name": sandbox.get("endpoint_env"),
    }
    for name, expected_value in expected.items():
        if value[name] != expected_value:
            raise CarrierFailure(f"{prefix}.{name}", "wrong_source")
    deployment_identity = require_nonempty(
        value["deployment_identity_sha256"], f"{prefix}.deployment_identity_sha256"
    )
    if not SHA256.fullmatch(deployment_identity):
        raise CarrierFailure(f"{prefix}.deployment_identity_sha256")
    api_version = require_identifier(value["api_version"], f"{prefix}.api_version")
    reported_model_revision = require_identifier(
        value["reported_model_revision"], f"{prefix}.reported_model_revision"
    )
    if (
        value["provider_name"] != "openai"
        or value["model_setting"] != "openai/gpt-4o"
        or value["credential_environment_name"] != "OPENAI_API_KEY"
        or value["endpoint_environment_name"] != "SWE_LANCER_DOCKER_HOST"
        or value["credential_permission_verified"] is not True
        or value["credential_value_recorded"] is not False
        or value["endpoint_value_recorded"] is not False
        or value["provider_model_api_calls"] != 0
    ):
        raise CarrierFailure(f"{prefix}.contract")
    return {
        "fresh": True,
        "deployment_identity_sha256": deployment_identity,
        "api_version": api_version,
        "reported_model_revision": reported_model_revision,
        "credential_permission_verified": True,
        "credential_value_recorded": False,
        "endpoint_value_recorded": False,
    }


def validate_price_receipt(
    value: Mapping[str, object],
    ledger: Mapping[str, object],
    ledger_sha256: str,
    current_time: datetime,
) -> dict[str, object]:
    prefix = "price_receipt"
    if set(value) != PRICE_RECEIPT_FIELDS:
        raise CarrierFailure(f"{prefix}.fields")
    if value["schema_version"] != 1 or value["kind"] != "swe_lancer_fixed_price_receipt":
        raise CarrierFailure(f"{prefix}.identity")
    validate_freshness(value, current_time, prefix)
    provider = ledger.get("provider")
    if not isinstance(provider, Mapping):
        raise CarrierFailure("admission_ledger.provider")
    expected = {
        "ledger_sha256": ledger_sha256,
        "input_usd_per_million_tokens": provider.get("input_usd_per_million_tokens"),
        "output_usd_per_million_tokens": provider.get("output_usd_per_million_tokens"),
        "price_source_url": provider.get("price_source_url"),
        "price_source_revision_or_retrieved_at": provider.get(
            "price_source_revision_or_retrieved_at"
        ),
    }
    for name, expected_value in expected.items():
        if value[name] != expected_value:
            raise CarrierFailure(f"{prefix}.{name}", "wrong_source")
    require_positive_decimal(value["input_usd_per_million_tokens"], f"{prefix}.input_rate")
    require_positive_decimal(value["output_usd_per_million_tokens"], f"{prefix}.output_rate")
    require_nonempty(value["price_source_url"], f"{prefix}.price_source_url")
    require_nonempty(
        value["price_source_revision_or_retrieved_at"],
        f"{prefix}.price_source_revision_or_retrieved_at",
    )
    if value["currency"] != "USD" or value["provider_model_api_calls"] != 0:
        raise CarrierFailure(f"{prefix}.contract")
    return {
        "fresh": True,
        "ledger_bound": True,
        "currency": "USD",
        "provider_model_api_calls": 0,
    }


def validate_outbound_receipt(
    value: Mapping[str, object],
    ledger_sha256: str,
    current_time: datetime,
) -> dict[str, object]:
    prefix = "outbound_receipt"
    if set(value) != OUTBOUND_RECEIPT_FIELDS:
        raise CarrierFailure(f"{prefix}.fields")
    if value["schema_version"] != 1 or value["kind"] != "swe_lancer_outbound_cleanup_receipt":
        raise CarrierFailure(f"{prefix}.identity")
    validate_freshness(value, current_time, prefix)
    if value["ledger_sha256"] != ledger_sha256:
        raise CarrierFailure(f"{prefix}.ledger_sha256", "wrong_source")
    carrier_identity = require_nonempty(
        value["carrier_instance_identity_sha256"],
        f"{prefix}.carrier_instance_identity_sha256",
    )
    if not SHA256.fullmatch(carrier_identity):
        raise CarrierFailure(f"{prefix}.carrier_instance_identity_sha256")
    runtime_kind = require_identifier(value["runtime_kind"], f"{prefix}.runtime_kind")
    if (
        value["platform"] != "linux/amd64"
        or value["image_manifest_digest"] != admission.FIXED_IMAGE_DIGEST
        or value["image_config_digest"] != FIXED_IMAGE_CONFIG_DIGEST
        or value["paid_provider_outbound_verified"] is not True
        or value["cleanup_contract_verified"] is not True
        or value["credential_value_recorded"] is not False
        or value["endpoint_value_recorded"] is not False
        or value["provider_model_api_grader_calls"] != 0
        or value["network_calls"] != 0
        or value["survivor_count"] != 0
    ):
        raise CarrierFailure(f"{prefix}.contract")
    return {
        "fresh": True,
        "carrier_instance_identity_sha256": carrier_identity,
        "runtime_kind": runtime_kind,
        "platform": "linux/amd64",
        "image_manifest_digest": admission.FIXED_IMAGE_DIGEST,
        "image_config_digest": FIXED_IMAGE_CONFIG_DIGEST,
        "paid_provider_outbound_verified": True,
        "cleanup_contract_verified": True,
        "survivor_count": 0,
    }


def admission_side_effects(value: object) -> dict[str, bool]:
    if not isinstance(value, Mapping):
        raise CarrierFailure("admission.side_effects")
    effects: dict[str, bool] = {}
    for name in ADMISSION_SIDE_EFFECT_FIELDS:
        field = value.get(name)
        if type(field) is not bool:
            raise CarrierFailure("admission.side_effects")
        effects[name] = field
    return effects


def preserve_admission_side_effects(
    result: dict[str, object], effects: Mapping[str, bool]
) -> None:
    for name in ADMISSION_SIDE_EFFECT_FIELDS:
        result["side_effects"][name] = effects[name]
    if effects["provider_called"]:
        result["side_effects"]["provider_model_api_grader_calls"] = None


def probe(
    environment: Mapping[str, str],
    *,
    root: Path = ROOT,
    definition_path: Path = DEFINITION_PATH,
    current_time: datetime | None = None,
) -> dict[str, object]:
    observed = utc_now() if current_time is None else current_time.astimezone(timezone.utc)
    try:
        definition, definition_fingerprint, source_fingerprint = load_definition(
            definition_path, root
        )
    except CarrierFailure as failure:
        return failure_record(observed, environment, failure)
    context: dict[str, object] = {
        "command": definition[IDENTITY_FIELDS[0]],
        "identity_kind": definition[IDENTITY_FIELDS[1]],
        "identity_source": definition[IDENTITY_FIELDS[2]],
        "identity_sha256": definition[IDENTITY_FIELDS[3]],
        "identity_bytes": source_fingerprint["bytes"],
        "owner": definition[IDENTITY_FIELDS[4]],
        "definition": definition_fingerprint,
        "attestation": None,
    }
    attestation_name = definition["input_environment_names"]["attestation"]
    try:
        attestation_payload, attestation_fingerprint = load_private_input(
            environment, attestation_name, "attestation"
        )
        attestation = parse_json_mapping(attestation_payload, "context_attestation")
        validate_attestation(attestation, definition, definition_fingerprint, observed)
    except CarrierFailure as failure:
        return failure_record(observed, environment, failure, definition, context)
    context["attestation"] = {**attestation_fingerprint, "fresh": True}

    required_names = {
        definition[IDENTITY_FIELDS[0]]["executable_environment_name"],
        definition["input_environment_names"]["ledger"],
        definition["input_environment_names"]["provider_contract_receipt"],
        definition["input_environment_names"]["price_receipt"],
        definition["input_environment_names"]["outbound_receipt"],
        definition["input_environment_names"]["deadline"],
        *definition["admission_environment_names"].values(),
    }
    missing_names = sorted(name for name in required_names if name not in environment)
    if missing_names:
        return failure_record(
            observed,
            environment,
            CarrierFailure(f"environment.{missing_names[0]}.present", "missing"),
            definition,
            context,
        )

    input_records: dict[str, dict[str, object]] = {}
    loaded = 0
    admission_invocations = 0
    reported_admission_side_effects: dict[str, bool] | None = None
    try:
        payloads: dict[str, bytes] = {}
        for label in (
            "ledger",
            "provider_contract_receipt",
            "price_receipt",
            "outbound_receipt",
        ):
            payload, input_records[label] = load_private_input(
                environment,
                definition["input_environment_names"][label],
                label,
            )
            payloads[label] = payload
            loaded += 1
            if input_records[label] != attestation["input_fingerprints"][label]:
                raise CarrierFailure(
                    f"context_attestation.input_fingerprints.{label}", "wrong_source"
                )

        ledger = parse_json_mapping(payloads["ledger"], "admission_ledger")
        provider_receipt = parse_json_mapping(
            payloads["provider_contract_receipt"], "provider_contract_receipt"
        )
        price_receipt = parse_json_mapping(payloads["price_receipt"], "price_receipt")
        outbound_receipt = parse_json_mapping(payloads["outbound_receipt"], "outbound_receipt")
        ledger_sha256 = input_records["ledger"]["sha256"]
        receipt_records = {
            "provider_contract": {
                **input_records["provider_contract_receipt"],
                **validate_provider_receipt(
                    provider_receipt, ledger, ledger_sha256, observed
                ),
            },
            "price": {
                **input_records["price_receipt"],
                **validate_price_receipt(price_receipt, ledger, ledger_sha256, observed),
            },
            "outbound": {
                **input_records["outbound_receipt"],
                **validate_outbound_receipt(outbound_receipt, ledger_sha256, observed),
            },
        }
        deadline = environment[definition["input_environment_names"]["deadline"]]
        admission_invocations += 1
        admission_result = admission.check_admission(
            ledger,
            input_records["ledger"],
            deadline,
            environment,
            presence_only_environment_names=frozenset(
                {
                    EXPECTED_ADMISSION_ENVIRONMENTS["provider_credential"],
                    EXPECTED_ADMISSION_ENVIRONMENTS["sandbox_endpoint"],
                }
            ),
        )
        reported_admission_side_effects = admission_side_effects(
            admission_result.get("side_effects")
        )
        if any(reported_admission_side_effects.values()):
            raise CarrierFailure("admission.side_effects")
    except CarrierFailure as failure:
        result = failure_record(observed, environment, failure, definition, context)
        result["side_effects"]["runtime_input_files_read"] = loaded
        result["side_effects"]["admission_invocations"] = admission_invocations
        if reported_admission_side_effects is not None:
            preserve_admission_side_effects(result, reported_admission_side_effects)
        return result
    except (InvalidOperation, TypeError, ValueError) as error:
        result = failure_record(
            observed,
            environment,
            CarrierFailure("runtime_inputs.valid"),
            definition,
            context,
        )
        result["side_effects"]["runtime_input_files_read"] = loaded
        result["side_effects"]["admission_invocations"] = admission_invocations
        return result

    result = base_record(observed, environment_presence(definition, environment))
    result["status"] = "ready" if admission_result["ready"] else "not_ready"
    result["ready"] = admission_result["ready"]
    result["context_status"] = "verified"
    result["missing_or_invalid"] = admission_result["missing_or_invalid"]
    result["context"] = context
    result["receipts"] = receipt_records
    result["admission"] = admission_result
    result["side_effects"]["runtime_input_files_read"] = loaded
    result["side_effects"]["admission_invocations"] = admission_invocations
    return result


def run(
    environment: Mapping[str, str] | None = None,
    *,
    root: Path = ROOT,
    definition_path: Path = DEFINITION_PATH,
    current_time: datetime | None = None,
) -> tuple[int, dict[str, object]]:
    values = os.environ if environment is None else environment
    observed = utc_now() if current_time is None else current_time.astimezone(timezone.utc)
    output_value = values.get(EXPECTED_INPUT_ENVIRONMENTS["output"])
    if not isinstance(output_value, str) or not output_value:
        failure = CarrierFailure("environment.SWE_LANCER_ADMISSION_RESULT.present", "missing")
        return 3, failure_record(observed, values, failure)
    try:
        descriptor = admission.reserve_result(Path(output_value))
    except OSError:
        failure = CarrierFailure("output.no_clobber")
        return 2, failure_record(observed, values, failure)
    try:
        result = probe(
            values,
            root=root,
            definition_path=definition_path,
            current_time=observed,
        )
    except BaseException:
        os.close(descriptor)
        raise
    admission.write_reserved(descriptor, result)
    if result.get("failure_class") == "source":
        return 2, result
    return (0 if result["ready"] else 3), result


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(arguments)
    try:
        exit_code, result = run()
    except (OSError, ValueError) as error:
        result = {
            "schema_version": 1,
            "kind": "swe_lancer_private_carrier_context_check",
            "status": "error",
            "ready": False,
            "context_status": "invalid",
            "failure_class": "source",
            "error_type": type(error).__name__,
            "provider_model_api_grader_calls": 0,
            "network_calls": 0,
            "credential_values_read": 0,
            "endpoint_values_read": 0,
        }
        exit_code = 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
