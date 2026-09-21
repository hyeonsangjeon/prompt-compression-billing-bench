"""Verify a sanctioned project runtime context before running the offline doctor."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .cache_reuse import doctor, parse_json_object, validate_cache_ledger
from .native_contract import parse_native_ledger


ROOT = Path(__file__).resolve().parents[1]
DEFINITION_PATH = ROOT / "config/cache-runtime-context.json"
SHA256 = re.compile(r"[0-9a-f]{64}")
ENVIRONMENT_NAME = re.compile(r"[A-Z][A-Z0-9_]*")
IDENTITY_FIELDS = (
    "SANCTIONED_PROJECT_RUNTIME_CONTEXT_COMMAND",
    "SANCTIONED_PROJECT_RUNTIME_CONTEXT_IDENTITY_KIND",
    "SANCTIONED_PROJECT_RUNTIME_CONTEXT_IDENTITY_SOURCE",
    "SANCTIONED_PROJECT_RUNTIME_CONTEXT_IDENTITY_SHA256",
    "SANCTIONED_PROJECT_RUNTIME_CONTEXT_OWNER",
)
EXPECTED_COMMAND = {
    "executable_environment_name": "CACHE_RUNTIME_PYTHON",
    "arguments": ["-m", "src.cache_runtime_context"],
}
EXPECTED_INPUT_ENVIRONMENTS = {
    "attestation": "CACHE_RUNTIME_CONTEXT_ATTESTATION",
    "cache_ledger": "CACHE_REUSE_LEDGER",
    "runtime_facts": "CACHE_RUNTIME_FACTS",
    "native_ledger": "NATIVE_CACHE_LEDGER",
    "output": "CACHE_REUSE_DOCTOR",
}
DEFINITION_FIELDS = {
    "schema_version",
    "kind",
    *IDENTITY_FIELDS,
    "input_environment_names",
    "inline_values",
    "provider_model_api_calls",
}
ATTESTATION_FIELDS = {
    "schema_version",
    "kind",
    "observed_at_utc",
    "valid_through_utc",
    "definition_sha256",
    *IDENTITY_FIELDS,
}


class ContextFailure(ValueError):
    def __init__(self, code: str, status: str = "invalid", source_error: bool = False):
        super().__init__(code)
        self.code = code
        self.status = status
        self.source_error = source_error


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def read_regular(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("not a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(descriptor)


def fingerprint(content: bytes) -> dict[str, object]:
    return {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def parse_utc(value: object, code: str) -> datetime:
    if not isinstance(value, str):
        raise ContextFailure(code)
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ContextFailure(code) from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ContextFailure(code)
    return parsed.astimezone(timezone.utc)


def project_path(root: Path, value: object) -> Path:
    if not isinstance(value, str):
        raise ContextFailure("project_definition.identity_source", source_error=True)
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != value:
        raise ContextFailure("project_definition.identity_source", source_error=True)
    return root / relative


def validate_definition(
    value: object,
    payload: bytes,
    root: Path,
) -> tuple[dict, dict[str, object], dict[str, object]]:
    if not isinstance(value, dict) or set(value) != DEFINITION_FIELDS:
        raise ContextFailure("project_definition.fields", source_error=True)
    if value["schema_version"] != 1 or value["kind"] != "cache_reuse_runtime_context_definition":
        raise ContextFailure("project_definition.identity", source_error=True)
    if value[IDENTITY_FIELDS[0]] != EXPECTED_COMMAND:
        raise ContextFailure("project_definition.command", source_error=True)
    if value[IDENTITY_FIELDS[1]] != "repository_regular_file":
        raise ContextFailure("project_definition.identity_kind", source_error=True)
    if value[IDENTITY_FIELDS[2]] != "src/cache_runtime_context.py":
        raise ContextFailure("project_definition.identity_source", source_error=True)
    if value[IDENTITY_FIELDS[4]] != "runtime_owner":
        raise ContextFailure("project_definition.owner", source_error=True)
    if value["input_environment_names"] != EXPECTED_INPUT_ENVIRONMENTS:
        raise ContextFailure("project_definition.input_environment_names", source_error=True)
    environment_names = {
        EXPECTED_COMMAND["executable_environment_name"],
        *EXPECTED_INPUT_ENVIRONMENTS.values(),
    }
    if len(environment_names) != 6 or any(not ENVIRONMENT_NAME.fullmatch(name) for name in environment_names):
        raise ContextFailure("project_definition.environment_names", source_error=True)
    if value["inline_values"] is not False or value["provider_model_api_calls"] != 0:
        raise ContextFailure("project_definition.zero_call_contract", source_error=True)
    declared_sha256 = value[IDENTITY_FIELDS[3]]
    if not isinstance(declared_sha256, str) or not SHA256.fullmatch(declared_sha256):
        raise ContextFailure("project_definition.identity_sha256", source_error=True)
    source = project_path(root, value[IDENTITY_FIELDS[2]])
    try:
        source_payload = read_regular(source)
    except (OSError, ValueError) as error:
        raise ContextFailure("project_definition.identity_regular_file", source_error=True) from error
    source_fingerprint = fingerprint(source_payload)
    if source_fingerprint["sha256"] != declared_sha256:
        raise ContextFailure("project_definition.identity_sha256", "wrong_source", True)
    return value, fingerprint(payload), source_fingerprint


def load_definition(path: Path, root: Path) -> tuple[dict, dict[str, object], dict[str, object]]:
    try:
        payload = read_regular(path)
        value = json.loads(payload)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ContextFailure("project_definition.regular_json", source_error=True) from error
    return validate_definition(value, payload, root)


def validate_attestation(
    value: object,
    definition: dict,
    definition_fingerprint: dict[str, object],
    current_time: datetime,
) -> None:
    if not isinstance(value, dict):
        raise ContextFailure("context_attestation.object")
    missing = ATTESTATION_FIELDS - set(value)
    if missing:
        raise ContextFailure("context_attestation.fields", "missing")
    if set(value) != ATTESTATION_FIELDS:
        raise ContextFailure("context_attestation.fields")
    if value["schema_version"] != 1 or value["kind"] != "cache_reuse_runtime_context_attestation":
        raise ContextFailure("context_attestation.identity")
    if value["definition_sha256"] != definition_fingerprint["sha256"]:
        raise ContextFailure("context_attestation.definition_sha256", "wrong_source")
    for field in IDENTITY_FIELDS:
        if value[field] != definition[field]:
            raise ContextFailure(f"context_attestation.{field}", "wrong_source")
    observed = parse_utc(value["observed_at_utc"], "context_attestation.observed_at_utc")
    valid_through = parse_utc(value["valid_through_utc"], "context_attestation.valid_through_utc")
    if observed > current_time or valid_through <= observed or current_time > valid_through:
        raise ContextFailure("context_attestation.freshness", "stale")


def environment_presence(definition: dict | None, environment: Mapping[str, str]) -> dict[str, bool]:
    names = {
        EXPECTED_COMMAND["executable_environment_name"],
        *EXPECTED_INPUT_ENVIRONMENTS.values(),
    }
    if definition is not None:
        names = {
            definition[IDENTITY_FIELDS[0]]["executable_environment_name"],
            *definition["input_environment_names"].values(),
        }
    return {name: name in environment for name in sorted(names)}


def base_record(current_time: datetime, presence: dict[str, bool]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "cache_reuse_runtime_context_probe",
        "observed_at_utc": format_utc(current_time),
        "decision": "no_go",
        "context_status": "invalid",
        "missing_or_invalid": [],
        "context": None,
        "environment_presence": presence,
        "values_stored": False,
        "doctor": None,
        "side_effects": {
            "runtime_input_files_read": 0,
            "doctor_invocations": 0,
            "provider_dispatch_started": False,
            "provider_model_api_calls": 0,
            "network_calls": 0,
            "credential_values_read": 0,
        },
    }


def failure_record(
    current_time: datetime,
    environment: Mapping[str, str],
    failure: ContextFailure,
    definition: dict | None = None,
    context: dict[str, object] | None = None,
) -> dict[str, object]:
    result = base_record(current_time, environment_presence(definition, environment))
    result["context_status"] = failure.status
    result["missing_or_invalid"] = [failure.code]
    result["context"] = context
    result["failure_class"] = "source" if failure.source_error else "admission"
    return result


def load_private_input(
    environment: Mapping[str, str],
    environment_name: str,
    label: str,
) -> tuple[bytes, dict[str, object]]:
    raw_path = environment.get(environment_name)
    if not isinstance(raw_path, str) or not raw_path:
        raise ContextFailure(f"environment.{environment_name}.present", "missing")
    try:
        payload = read_regular(Path(raw_path))
    except (OSError, ValueError) as error:
        raise ContextFailure(f"input.{label}.regular_file") from error
    return payload, fingerprint(payload)


def probe(
    environment: Mapping[str, str],
    *,
    root: Path = ROOT,
    definition_path: Path = DEFINITION_PATH,
    current_time: datetime | None = None,
) -> dict[str, object]:
    observed = utc_now() if current_time is None else current_time.astimezone(timezone.utc)
    try:
        definition, definition_fingerprint, source_fingerprint = load_definition(definition_path, root)
    except ContextFailure as failure:
        return failure_record(observed, environment, failure)
    context = {
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
        try:
            attestation = json.loads(attestation_payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ContextFailure("context_attestation.json") from error
        validate_attestation(attestation, definition, definition_fingerprint, observed)
    except ContextFailure as failure:
        return failure_record(observed, environment, failure, definition, context)
    context["attestation"] = {**attestation_fingerprint, "fresh": True}

    required_names = {
        definition[IDENTITY_FIELDS[0]]["executable_environment_name"],
        definition["input_environment_names"]["cache_ledger"],
        definition["input_environment_names"]["runtime_facts"],
        definition["input_environment_names"]["native_ledger"],
        definition["input_environment_names"]["output"],
    }
    missing_names = sorted(
        name for name in required_names
        if not isinstance(environment.get(name), str) or not environment.get(name)
    )
    if missing_names:
        return failure_record(
            observed,
            environment,
            ContextFailure(f"environment.{missing_names[0]}.present", "missing"),
            definition,
            context,
        )

    input_records: dict[str, dict[str, object]] = {}
    loaded = 0
    try:
        cache_payload, input_records["cache_ledger"] = load_private_input(
            environment,
            definition["input_environment_names"]["cache_ledger"],
            "cache_ledger",
        )
        loaded += 1
        facts_payload, input_records["runtime_facts"] = load_private_input(
            environment,
            definition["input_environment_names"]["runtime_facts"],
            "runtime_facts",
        )
        loaded += 1
        native_payload, input_records["native_ledger"] = load_private_input(
            environment,
            definition["input_environment_names"]["native_ledger"],
            "native_ledger",
        )
        loaded += 1
        cache_ledger = parse_json_object(cache_payload, "cache_ledger")
        validate_cache_ledger(cache_ledger)
        runtime_facts = parse_json_object(facts_payload, "runtime_facts")
        native_ledger = parse_native_ledger(native_payload)
        doctor_result = doctor(cache_ledger, runtime_facts, native_ledger, environment)
    except ContextFailure as failure:
        result = failure_record(observed, environment, failure, definition, context)
        result["side_effects"]["runtime_input_files_read"] = loaded
        return result
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        result = failure_record(
            observed,
            environment,
            ContextFailure("runtime_inputs.valid"),
            definition,
            context,
        )
        result["side_effects"]["runtime_input_files_read"] = loaded
        return result

    result = base_record(observed, environment_presence(definition, environment))
    result["decision"] = doctor_result["decision"]
    result["context_status"] = "verified"
    result["context"] = context
    result["runtime_inputs"] = input_records
    result["doctor"] = doctor_result
    result["side_effects"]["runtime_input_files_read"] = loaded
    result["side_effects"]["doctor_invocations"] = 1
    return result


def reserve_result(path: Path) -> int:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    os.fchmod(descriptor, 0o600)
    return descriptor


def write_reserved(descriptor: int, value: object) -> None:
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
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
        failure = ContextFailure("environment.CACHE_REUSE_DOCTOR.present", "missing")
        return 3, failure_record(observed, values, failure)
    try:
        descriptor = reserve_result(Path(output_value))
    except OSError:
        failure = ContextFailure("output.no_clobber")
        return 2, failure_record(observed, values, failure)
    try:
        result = probe(values, root=root, definition_path=definition_path, current_time=observed)
    except BaseException:
        os.close(descriptor)
        raise
    write_reserved(descriptor, result)
    if result.get("failure_class") == "source":
        return 2, result
    return (0 if result["decision"] == "go" else 3), result


def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(arguments)
    try:
        exit_code, result = run()
    except (OSError, ValueError) as error:
        result = {
            "schema_version": 1,
            "kind": "cache_reuse_runtime_context_probe",
            "decision": "no_go",
            "context_status": "invalid",
            "failure_class": "source",
            "error_type": type(error).__name__,
            "provider_model_api_calls": 0,
            "network_calls": 0,
            "credential_values_read": 0,
        }
        exit_code = 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
