"""Resolve private provider throughput limits without publishing their values."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping


COMMON_QUEUE_FIELDS = {
    "state_path_env",
    "limits_checked_at_utc",
    "limits_source_reference",
    "deployment_isolation_reference",
}
ENVIRONMENT_NAME = re.compile(r"[A-Z][A-Z0-9_]*")


def queue_fields(schema_version: int) -> set[str]:
    limit_fields = {"rpm_env", "tpm_env"} if schema_version in (3, 4) else {"rpm", "tpm"}
    return COMMON_QUEUE_FIELDS | limit_fields


def validate_queue_limits(queue: dict, schema_version: int) -> None:
    if set(queue) != queue_fields(schema_version):
        raise ValueError("Unexpected or missing queue fields")
    if schema_version in (3, 4):
        for field in ("rpm_env", "tpm_env"):
            if not isinstance(queue[field], str) or not ENVIRONMENT_NAME.fullmatch(queue[field]):
                raise ValueError("Provider limits must use environment variable names")
        if queue["rpm_env"] == queue["tpm_env"]:
            raise ValueError("Request and token limits need distinct environment variables")
        return
    if schema_version not in (1, 2):
        raise ValueError("Unsupported queue-limit schema")
    rpm, tpm = queue["rpm"], queue["tpm"]
    if type(rpm) is not int or type(tpm) is not int or rpm <= 0 or tpm <= 0:
        raise ValueError("Legacy provider limits must be positive integers")


def runtime_queue_limits(
    queue: dict,
    schema_version: int,
    environment: Mapping[str, str] | None = None,
) -> tuple[int, int]:
    validate_queue_limits(queue, schema_version)
    if schema_version in (1, 2):
        return queue["rpm"], queue["tpm"]
    values = environment if environment is not None else os.environ
    resolved = []
    for field in ("rpm_env", "tpm_env"):
        name = queue[field]
        value = values.get(name)
        if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
            raise ValueError(f"Set {name} to the private positive integer provider limit")
        resolved.append(int(value))
    return resolved[0], resolved[1]


def public_queue_record(queue: dict, schema_version: int) -> dict:
    common = {
        "checked_at_utc": queue["limits_checked_at_utc"],
        "source_reference": queue["limits_source_reference"],
    }
    if schema_version in (1, 2):
        return {"rpm": queue["rpm"], "tpm": queue["tpm"], **common}
    return {
        "rpm_env": queue["rpm_env"],
        "tpm_env": queue["tpm_env"],
        "values_recorded": False,
        **common,
    }
