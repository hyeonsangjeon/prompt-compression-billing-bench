"""Validate local schemas without remote schema resolution."""

from __future__ import annotations

import json
from pathlib import Path
import tomllib

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"


def validate(value: dict, schema_name: str) -> None:
    schema = json.loads((SCHEMAS / schema_name).read_bytes())
    registry = Registry()
    for path in SCHEMAS.glob("*.json"):
        resource = Resource.from_contents(json.loads(path.read_bytes()))
        registry = registry.with_resource(path.name, resource)
    errors = list(Draft202012Validator(schema, registry=registry).iter_errors(value))
    if errors:
        location = ".".join(str(part) for part in errors[0].absolute_path) or "root"
        raise ValueError(f"{schema_name}: invalid contract at {location}: {errors[0].validator}")


def load_ledger(path: Path) -> dict:
    return parse_ledger(path.read_bytes())


def parse_ledger(content: bytes) -> dict:
    ledger = tomllib.loads(content.decode("utf-8"))
    validate(ledger, "static-ledger.schema.json")
    return ledger


def safe_child(root: Path, name: str) -> Path:
    relative = Path(name)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts or relative.as_posix() != name:
        raise ValueError("Artifact names must be normalized relative paths")
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root.resolve()) or resolved == root.resolve():
        raise ValueError("Artifact escapes its declared root")
    return resolved


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
