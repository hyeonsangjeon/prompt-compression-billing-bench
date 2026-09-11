"""Measure stored observation spans; no provider or native judge is invoked."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import signal
import sys
import tempfile
import time

from .compressors import CompressionResult, CompressorError, make_compressor, report
from .contracts import load_ledger, parse_ledger, safe_child, save_json, validate
from .measurement import UNITS, billed_unavailable, counts, load_encoder, pattern_observation, percent, prepare_tokenizer, reductions
from .pipeline import ObservationPipeline
from .protection import FrozenRequestGuard, ProtectionViolation, canonical, digest
from .provenance import ROOT, capture, verify_snapshot


@contextmanager
def time_limit(seconds: float):
    def expired(signum, frame):
        raise TimeoutError("The ledger's static measurement deadline was exceeded")

    previous = signal.signal(signal.SIGALRM, expired)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous)


def read_inputs(ledger: dict, encoder, input_root: Path | None = None) -> tuple[dict, bytes, list[bytes]]:
    if input_root is None:
        value = os.environ.get(ledger["inputs"]["root_env"])
        if not value:
            raise ValueError(f"Set {ledger['inputs']['root_env']} to the frozen input directory")
        input_root = Path(value).resolve()
    manifest_path = safe_child(input_root, "manifest.json")
    if manifest_path.stat().st_size > ledger["limits"]["max_input_bytes"]:
        raise ValueError("Frozen manifest exceeds max_input_bytes")
    manifest_bytes = manifest_path.read_bytes()
    if digest(manifest_bytes) != ledger["inputs"]["manifest_sha256"]:
        raise ValueError("Frozen manifest SHA-256 differs from the ledger")
    manifest = json.loads(manifest_bytes)
    validate(manifest, "frozen-input.schema.json")
    for field in ("dataset", "kind"):
        if manifest[field] != ledger["inputs"][field]:
            raise ValueError(f"Frozen input {field} differs from the ledger")
    requests = manifest["requests"]
    identities = [row["record_id"] for row in requests]
    if len(set(identities)) != len(identities):
        raise ValueError("Frozen request IDs must be unique")
    positions = {(row["task"], row["historical_run"], row["sequence"]) for row in requests}
    if len(positions) != len(requests):
        raise ValueError("Frozen historical request positions must be unique")
    expected = ledger["inputs"]
    if sorted({row["task"] for row in requests}) != sorted(expected["tasks"]):
        raise ValueError("Frozen task selection differs from the ledger")
    if len({row["historical_run"] for row in requests}) != expected["historical_runs"] or len(requests) != expected["request_count"]:
        raise ValueError("Frozen sample counts differ from the ledger")
    original_total = {name: 0 for name in UNITS}
    deleted_tokens = 0
    candidate_segments = 0
    protected_segments = 0
    sources = []
    consumed_bytes = len(manifest_bytes)
    for request in requests:
        path = safe_child(input_root, request["path"])
        consumed_bytes += path.stat().st_size
        if consumed_bytes > ledger["limits"]["max_input_bytes"]:
            raise ValueError("Frozen inputs exceed max_input_bytes")
        source = path.read_bytes()
        guard = FrozenRequestGuard(source, request["sha256"], request["segments"])
        original = json.loads(source)
        before = counts(original, guard.candidate_texts(), encoder)
        for name in UNITS:
            original_total[name] += before[name]
        deleted = guard.prepare([""] * guard.candidate_count)
        guard.verify(deleted)
        deleted_tokens += counts(deleted, [], encoder)["message_content_tokens"]
        candidate_segments += guard.candidate_count
        protected_segments += guard.protected_count
        sources.append(source)
    observed = {
        "message_content_utf8_bytes": original_total["message_content_utf8_bytes"],
        "message_content_tokens": original_total["message_content_tokens"],
        "candidate_utf8_bytes": original_total["candidate_utf8_bytes"],
        "deleted_content_tokens": deleted_tokens,
    }
    if observed != ledger["expect"]:
        raise ValueError(f"Frozen measurement contract changed in either direction: {observed}")
    if candidate_segments != expected["candidate_segments"] or protected_segments != expected["protected_segments"]:
        raise ValueError("Frozen partition counts differ from the ledger")
    return manifest, manifest_bytes, sources


def local_record(before: dict, after: dict, ledger: dict) -> dict:
    return {
        "kind": "measured", "source": "local_utf8_and_tiktoken",
        "tokenizer": ledger["measurement"]["tokenizer"],
        "tiktoken_version": ledger["measurement"]["tiktoken_version"],
        "tokenizer_table_sha256": ledger["measurement"]["table_sha256"],
        "scope": "message_content_only; no role framing, tools schema or provider billing",
        "units": UNITS, "before": before, "after": after,
    }


def deletion_record(before: dict, deleted: dict) -> dict:
    saved_tokens = before["message_content_tokens"] - deleted["message_content_tokens"]
    return {
        "kind": "calculated", "method": "retokenize_messages_after_hypothetical_complete_candidate_deletion",
        "after_message_content_tokens": deleted["message_content_tokens"],
        "after_message_content_utf8_bytes": deleted["message_content_utf8_bytes"],
        "saved_tokens": saved_tokens, "saved_percent": percent(saved_tokens, before["message_content_tokens"]),
        "token_unit": "o200k_base message-content tokens", "percent_unit": "percent_of_original_message_content_tokens",
        "not_an_achievable_or_end_to_end_upper_bound": True,
    }


def request_record(request: dict, source: bytes, originals: list[str], compressed: list, transformed: dict, checked: dict, ledger: dict, manifest: dict, encoder, lineage: dict) -> dict:
    before = counts(json.loads(source), originals, encoder)
    after = counts(transformed, [result.text for result in compressed], encoder)
    deletion_guard = FrozenRequestGuard(source, request["sha256"], request["segments"])
    deleted = deletion_guard.prepare([""] * deletion_guard.candidate_count)
    deletion_guard.verify(deleted)
    observations = [
        {
            "request_id": request["record_id"], "span_index": index,
            "input_sha256": digest(original.encode("utf-8")),
            "output_sha256": digest(result.text.encode("utf-8")), "report": result.tool_reported,
        }
        for index, (original, result) in enumerate(zip(originals, compressed, strict=True))
    ]
    record = {
        "schema_version": 2, "record_type": "static_request", "kind": "measured",
        "source": "local_compressor_on_frozen_requests", "input_kind": manifest["kind"], **lineage,
        "sample": {
            "tasks": [request["task"]], "historical_runs": [request["historical_run"]],
            "request_ids": [request["record_id"]], "requests": 1, "static_passes": 1,
            "selection": manifest["selection"], "retransmitted_history": manifest["retransmitted_history"],
        },
        "measured_local": local_record(before, after, ledger), "reductions": reductions(before, after),
        "deletion_reference": deletion_record(before, counts(deleted, [], encoder)),
        "tool_reported": {
            "kind": "tool_reported", "status": tool_status(observations, lineage["compressor"]["name"]),
            "observations": observations, "not_provider_usage": True,
        },
        "patterns": {
            "kind": "classification", "observations": [
                {"request_id": request["record_id"], "span_index": index, **pattern_observation(original, result.text)}
                for index, (original, result) in enumerate(zip(originals, compressed, strict=True))
            ],
        },
        "protection": {"kind": "verification", "status": "passed", **{name: checked[name] for name in ("candidate_segments", "candidate_utf8_bytes", "protected_segments", "protected_utf8_bytes")}},
        "measured_billed": billed_unavailable(), "judge": {"kind": "unavailable", "status": "not_run", "score": None},
        "model_calls": 0, "artifacts": {},
    }
    return record


def tool_status(observations: list[dict], name: str) -> str:
    if any(observation["report"]["status"] == "reported" for observation in observations):
        return "reported"
    return "not_applicable" if name == "none" else "not_reported"


def aggregate(records: list[dict]) -> dict:
    if not records:
        raise ValueError("Cannot aggregate an empty or incomplete static run")
    summary = deepcopy(records[0])
    summary["record_type"] = "static_summary"
    for field in ("run_id", "source_commit", "source_sha256", "ledger_sha256", "manifest_sha256", "compressor", "input_kind", "measured_billed", "judge"):
        if any(record[field] != summary[field] for record in records):
            raise ValueError(f"Static conditions differ across records: {field}")
    summary["sample"].update({
        "tasks": sorted({task for record in records for task in record["sample"]["tasks"]}),
        "historical_runs": sorted({run for record in records for run in record["sample"]["historical_runs"]}),
        "request_ids": [identifier for record in records for identifier in record["sample"]["request_ids"]],
        "requests": len(records),
    })
    for phase in ("before", "after"):
        summary["measured_local"][phase] = {name: sum(record["measured_local"][phase][name] for record in records) for name in UNITS}
    before, after = (summary["measured_local"][phase] for phase in ("before", "after"))
    summary["reductions"] = reductions(before, after)
    summary["deletion_reference"] = deletion_record(before, {
        "message_content_tokens": sum(record["deletion_reference"]["after_message_content_tokens"] for record in records),
        "message_content_utf8_bytes": sum(record["deletion_reference"]["after_message_content_utf8_bytes"] for record in records),
    })
    for name in ("candidate_segments", "candidate_utf8_bytes", "protected_segments", "protected_utf8_bytes"):
        summary["protection"][name] = sum(record["protection"][name] for record in records)
    for section in ("tool_reported", "patterns"):
        summary[section]["observations"] = [observation for record in records for observation in record[section]["observations"]]
    summary["tool_reported"]["status"] = tool_status(summary["tool_reported"]["observations"], summary["compressor"]["name"])
    summary["artifacts"] = {}
    validate(summary, "static-result.schema.json")
    return summary


def execute(ledger_path: Path, source_commit: str) -> Path:
    provenance, snapshots = capture(ledger_path, source_commit)
    ledger = parse_ledger(snapshots["ledger.toml"])
    encoder = load_encoder(ledger["measurement"])
    manifest, manifest_bytes, sources = read_inputs(ledger, encoder)
    run_id = datetime.now(timezone.utc).strftime("static-%Y%m%dT%H%M%SZ-") + secrets.token_hex(4)
    directory = Path(ledger["output_dir"]).resolve() / run_id
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    for name, content in snapshots.items():
        target = safe_child(directory, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    save_json(directory / "provenance.json", provenance)
    (directory / "manifest.json").write_bytes(manifest_bytes)
    started = time.monotonic()
    try:
        with time_limit(ledger["limits"]["max_wall_seconds"]):
            compressor = make_compressor(ledger["compressor"], directory / "compressor")
            lineage = {
                "run_id": run_id, **{field: provenance[field] for field in ("source_commit", "source_sha256", "ledger_sha256")},
                "manifest_sha256": digest(manifest_bytes),
                "compressor": {**compressor.metadata, "target": ledger["compressor"]["target"]},
            }
            pipeline = ObservationPipeline(compressor)
            records = []
            with (directory / "records.jsonl").open("x", encoding="utf-8") as output:
                for request_index, (request, source) in enumerate(zip(manifest["requests"], sources, strict=True)):
                    transformed, checked, originals, compressed = pipeline.transform(source, request["sha256"], request["segments"])
                    record = request_record(request, source, originals, compressed, transformed, checked, ledger, manifest, encoder, lineage)
                    artifacts = {
                        f"originals/{request_index:04d}.json": source,
                        f"transformed/{request_index:04d}.json": canonical(transformed),
                        **{f"replacements/{request_index:04d}/{span_index:04d}.txt": result.text.encode("utf-8") for span_index, result in enumerate(compressed)},
                    }
                    for name, content in artifacts.items():
                        target = safe_child(directory, name)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(content)
                    record["artifacts"] = {name: digest(content) for name, content in artifacts.items()}
                    validate(record, "static-result.schema.json")
                    output.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                    output.flush()
                    records.append(record)
            summary = aggregate(records)
            summary["artifacts"] = {name: digest((directory / name).read_bytes()) for name in ("records.jsonl", "manifest.json", "ledger.toml", "provenance.json")}
            validate(summary, "static-result.schema.json")
            save_json(directory / "summary.json", summary)
        save_json(directory / "execution.json", {
            "kind": "measured", "source": "monotonic_clock", "status": "completed", "source_commit": source_commit,
            "run_id": run_id, "elapsed_seconds": time.monotonic() - started,
            "scope": "compression_and_recording_after_input_preflight", "model_calls": 0,
            "network_isolation": "No provider transport; no credentials inherited by squeez. Not an OS network sandbox.",
        })
    except Exception as error:
        save_json(directory / "failure.json", {
            "kind": "execution_error", "status": "failed", "source_commit": source_commit, "run_id": run_id,
            "error_type": type(error).__name__, "message": str(error), "model_calls": 0,
            "measured_billed": billed_unavailable(),
        })
        raise
    return directory


def verify(directory: Path) -> dict:
    if (directory / "failure.json").exists() or not (directory / "execution.json").is_file():
        raise ValueError("Static run failed or is incomplete")
    provenance = verify_snapshot(directory)
    ledger = load_ledger(directory / "ledger.toml")
    summary = json.loads((directory / "summary.json").read_bytes())
    validate(summary, "static-result.schema.json")
    for name, expected_hash in summary["artifacts"].items():
        if digest(safe_child(directory, name).read_bytes()) != expected_hash:
            raise ValueError(f"Static summary artifact hash differs: {name}")
    if set(summary["artifacts"]) != {"records.jsonl", "manifest.json", "ledger.toml", "provenance.json"}:
        raise ValueError("Incomplete summary artifact inventory")
    for field in ("source_commit", "source_sha256", "ledger_sha256"):
        if summary[field] != provenance[field]:
            raise ValueError(f"Static summary lineage differs: {field}")
    name = ledger["compressor"]["name"]
    specification = ledger["compressor"]["tools"][name]
    if summary["compressor"] != {
        "name": name, "version": specification["version"], "binary_sha256": specification.get("sha256"),
        "options": specification["options"], "target": ledger["compressor"]["target"],
    }:
        raise ValueError("Recorded compressor differs from the ledger")
    execution = json.loads((directory / "execution.json").read_bytes())
    if execution["status"] != "completed" or execution["source_commit"] != provenance["source_commit"] or execution["run_id"] != summary["run_id"] or execution["model_calls"] != 0:
        raise ValueError("Static completion record differs")
    manifest_bytes = (directory / "manifest.json").read_bytes()
    if digest(manifest_bytes) != ledger["inputs"]["manifest_sha256"] or summary["manifest_sha256"] != digest(manifest_bytes):
        raise ValueError("Frozen input lineage differs")
    manifest = json.loads(manifest_bytes)
    validate(manifest, "frozen-input.schema.json")
    records = [json.loads(line) for line in (directory / "records.jsonl").read_text().splitlines()]
    if len(records) != len(manifest["requests"]):
        raise ValueError("Static results do not cover the complete frozen manifest")
    encoder = load_encoder(ledger["measurement"])
    for request_index, (request, record) in enumerate(zip(manifest["requests"], records, strict=True)):
        validate(record, "static-result.schema.json")
        for name, expected_hash in record["artifacts"].items():
            if digest(safe_child(directory, name).read_bytes()) != expected_hash:
                raise ValueError(f"Static request artifact hash differs: {name}")
        source_name = f"originals/{request_index:04d}.json"
        transformed_name = f"transformed/{request_index:04d}.json"
        source = safe_child(directory, source_name).read_bytes()
        guard = FrozenRequestGuard(source, request["sha256"], request["segments"])
        originals = guard.candidate_texts()
        replacement_names = [f"replacements/{request_index:04d}/{span_index:04d}.txt" for span_index in range(guard.candidate_count)]
        if set(record["artifacts"]) != {source_name, transformed_name, *replacement_names}:
            raise ValueError("Incomplete request artifact inventory")
        replacements = [safe_child(directory, name).read_bytes().decode("utf-8") for name in replacement_names]
        guard.prepare(replacements)
        transformed = json.loads(safe_child(directory, transformed_name).read_bytes())
        checked = guard.verify(transformed)
        compressed = [CompressionResult(text=text, tool_reported=report([line for line in text.splitlines() if line.startswith("# squeez ")] if summary["compressor"]["name"] == "squeez" else [], summary["compressor"]["name"])) for text in replacements]
        lineage = {field: summary[field] for field in ("run_id", "source_commit", "source_sha256", "ledger_sha256", "manifest_sha256", "compressor")}
        reproduced = request_record(request, source, originals, compressed, transformed, checked, ledger, manifest, encoder, lineage)
        reproduced["artifacts"] = record["artifacts"]
        if reproduced != record:
            raise ValueError("Static record differs in either direction from its artifacts")
        if summary["compressor"]["name"] == "none" and (replacements != originals or any(record["reductions"]["saved"].values())):
            raise ValueError("No-op is not an exact identity transformation")
    reproduced_summary = aggregate(records)
    reproduced_summary["artifacts"] = summary["artifacts"]
    if reproduced_summary != summary:
        raise ValueError("Static aggregate differs in either direction from its records")
    before = summary["measured_local"]["before"]
    if ledger["expect"] != {
        "message_content_utf8_bytes": before["message_content_utf8_bytes"],
        "message_content_tokens": before["message_content_tokens"],
        "candidate_utf8_bytes": before["candidate_utf8_bytes"],
        "deleted_content_tokens": summary["deletion_reference"]["after_message_content_tokens"],
    }:
        raise ValueError("Verified input measurements differ from ledger expectations")
    if len(summary["sample"]["historical_runs"]) != ledger["inputs"]["historical_runs"] or summary["sample"]["tasks"] != sorted(ledger["inputs"]["tasks"]) or summary["sample"]["requests"] != ledger["inputs"]["request_count"]:
        raise ValueError("Verified sample differs from the ledger")
    if any(summary["protection"][field] != ledger["inputs"][field] for field in ("candidate_segments", "protected_segments")):
        raise ValueError("Verified partition counts differ from the ledger")
    return summary


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", nargs="?", type=Path, default=Path("ledgers/static.toml"))
    parser.add_argument("--source-commit")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--check", action="store_true")
    actions.add_argument("--verify", type=Path)
    actions.add_argument("--prepare-tokenizer", type=Path, metavar="CACHE_DIR")
    args = parser.parse_args(arguments)
    try:
        if args.prepare_tokenizer:
            print(prepare_tokenizer(args.prepare_tokenizer))
            return 0
        if args.verify:
            checked = verify(args.verify.resolve())
            if args.source_commit and checked["source_commit"] != args.source_commit:
                raise ValueError("Verified commit differs from independently designated SHA")
            print(json.dumps({"status": "verified", "run_id": checked["run_id"], "source_commit": checked["source_commit"]}))
            return 0
        if args.check:
            provenance, snapshots = capture(args.ledger, args.source_commit)
            ledger = parse_ledger(snapshots["ledger.toml"])
            encoder = load_encoder(ledger["measurement"])
            read_inputs(ledger, encoder)
            cache = ROOT / ".cache"
            cache.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(dir=cache, prefix="static-check-") as temporary:
                compressor = make_compressor(ledger["compressor"], Path(temporary) / "compressor")
                print(json.dumps({"status": "checked", "source_commit": provenance["source_commit"], "compressor": compressor.metadata, "model_calls": 0}))
            return 0
        directory = execute(args.ledger, args.source_commit)
        checked = verify(directory)
        print(json.dumps({"directory": str(directory), "source_commit": checked["source_commit"], "reductions": checked["reductions"], "model_calls": 0}))
        return 0
    except (ValueError, OSError, KeyError, CompressorError, ProtectionViolation) as error:
        print(f"Static execution stopped: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
