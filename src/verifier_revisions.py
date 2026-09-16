"""Hash-bound benchmark verifier revisions applied before native execution."""

from copy import deepcopy
from hashlib import sha256


NGINX_TASK = "nginx-request-logging"
NGINX_VERIFIER_SPEC = {
    "revision": "nginx-request-logging-verifier-v2",
    "source_path": "tests/test_outputs.py",
    "source_sha256": "045cc716c14efde3b0dcff5fc7c85ec5d18bfc6ce66f8b40a418fa2a3a4acda0",
    "effective_sha256": "20812107bc3bfc541728a2d10e3da0552e907d949e1347a03d33aa26954f8902",
}
VERIFIER_SPECS = {NGINX_TASK: NGINX_VERIFIER_SPEC}

UPSTREAM_LOG_FIELD_CHECK = b'''    # Check custom logging format - look for any log_format with required fields
    required_fields = ["$time_local", "$request_method", "$status", "$http_user_agent"]
    missing_fields = [field for field in required_fields if field not in config_content]
'''
REVISED_LOG_FIELD_CHECK = b'''    # Check custom logging format - look for any log_format with required fields
    required_variables = ["time_local", "request_method", "status", "http_user_agent"]
    missing_fields = [
        f"${variable}"
        for variable in required_variables
        if not re.search(
            rf"\\$(?:{variable}(?![A-Za-z0-9_])|\\{{{variable}\\}})",
            config_content,
        )
    ]
'''


def file_sha256(content: bytes) -> str:
    return sha256(content).hexdigest()


def nginx_variable_present(config: str, variable: str) -> bool:
    import re

    return re.search(
        rf"\$(?:{variable}(?![A-Za-z0-9_])|\{{{variable}\}})",
        config,
    ) is not None


def _revise_nginx_source(source: bytes) -> bytes:
    if source.count(UPSTREAM_LOG_FIELD_CHECK) != 1:
        raise ValueError("The pinned nginx verifier field check is absent or ambiguous")
    return source.replace(UPSTREAM_LOG_FIELD_CHECK, REVISED_LOG_FIELD_CHECK)


def apply_verifier_revision(task: str, files: dict[str, bytes], specifications: dict) -> tuple[dict[str, bytes], dict]:
    effective = deepcopy(files)
    specification = specifications.get(task)
    if specification is None:
        return effective, {"revision": "upstream", "modified": False}
    if task != NGINX_TASK or specification != NGINX_VERIFIER_SPEC:
        raise ValueError("Unknown or changed benchmark verifier revision")
    source_path = specification["source_path"]
    source = effective.get(source_path)
    if source is None or file_sha256(source) != specification["source_sha256"]:
        raise ValueError("The nginx verifier source differs from the approved revision base")
    revised = _revise_nginx_source(source)
    if file_sha256(revised) != specification["effective_sha256"]:
        raise ValueError("The effective nginx verifier differs from the approved revision")
    effective[source_path] = revised
    return effective, {**specification, "modified": True}
