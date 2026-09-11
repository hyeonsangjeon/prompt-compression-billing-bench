"""Compare verified static runs whose ledgers differ only in compressor.name."""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path

from .contracts import load_ledger, save_json
from .measurement import load_encoder, percent, token_count
from .protection import FrozenRequestGuard
from .provenance import capture
from .static_run import aggregate, verify


def differences(first, second, prefix="") -> list[str]:
    if isinstance(first, dict) and isinstance(second, dict):
        return [
            difference
            for key in sorted(set(first) | set(second))
            for difference in differences(first.get(key), second.get(key), f"{prefix}.{key}".lstrip("."))
        ]
    return [] if first == second else [prefix]


def assert_swap(baseline: dict, compressed: dict, baseline_ledger: dict, compressed_ledger: dict) -> None:
    if baseline_ledger["compressor"]["name"] != "none" or compressed_ledger["compressor"]["name"] != "squeez":
        raise ValueError("Compare an explicit none baseline with a squeez run, in that order")
    if differences(baseline_ledger, compressed_ledger) != ["compressor.name"]:
        raise ValueError("Swap changed more than compressor.name")
    for field in ("source_commit", "source_sha256", "manifest_sha256", "sample", "protection", "deletion_reference", "judge", "measured_billed"):
        if baseline[field] != compressed[field]:
            raise ValueError(f"Swap conditions differ: {field}")
    if baseline["measured_local"]["before"] != compressed["measured_local"]["before"]:
        raise ValueError("Original local measurements differ")
    if any(baseline["reductions"]["saved"].values()):
        raise ValueError("No-op baseline was not an identity transformation")


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def compare(baseline_path: Path, compressed_path: Path, output: Path, source_commit: str) -> dict:
    current, _snapshots = capture(baseline_path / "ledger.toml", source_commit)
    baseline, compressed = verify(baseline_path), verify(compressed_path)
    baseline_ledger, compressed_ledger = load_ledger(baseline_path / "ledger.toml"), load_ledger(compressed_path / "ledger.toml")
    assert_swap(baseline, compressed, baseline_ledger, compressed_ledger)
    if current["source_commit"] != compressed["source_commit"] or current["source_sha256"] != compressed["source_sha256"]:
        raise ValueError("Comparison code differs from the measured source commit")
    output.mkdir(parents=True, exist_ok=False)
    pattern_observations = compressed["patterns"]["observations"]
    tool_observations = compressed["tool_reported"]["observations"]
    saved_tokens = compressed["reductions"]["saved"]["message_content_tokens"]
    deleted_tokens = compressed["deletion_reference"]["saved_tokens"]
    saved_percent = compressed["reductions"]["saved_percent"]["message_content_tokens"]
    common = {
        "source_commit": source_commit, "baseline_run_id": baseline["run_id"], "squeez_run_id": compressed["run_id"],
        "baseline_ledger_sha256": baseline["ledger_sha256"], "squeez_ledger_sha256": compressed["ledger_sha256"],
        "manifest_sha256": compressed["manifest_sha256"],
    }
    result = {
        "kind": "calculated", "source": "verified_frozen_static_records", **common,
        "sample": compressed["sample"], "protection": compressed["protection"],
        "measured_local": compressed["measured_local"], "reductions": compressed["reductions"],
        "deletion_reference": compressed["deletion_reference"],
        "deletion_gap": {
            "kind": "calculated", "saved_tokens": deleted_tokens - saved_tokens,
            "percentage_points": compressed["deletion_reference"]["saved_percent"] - saved_percent if saved_percent is not None else None,
            "squeez_percent_of_deletion_reduction": percent(saved_tokens, deleted_tokens),
            "not_an_achievable_or_end_to_end_upper_bound": True,
        },
        "span_occurrences": len(tool_observations),
        "unique_candidate_text_hashes": len({observation["input_sha256"] for observation in tool_observations}),
        "changed_span_occurrences": sum(observation["changed"] for observation in pattern_observations),
        "occurrences_with_tool_header": sum(bool(observation["report"]["headers"]) for observation in tool_observations),
        "tool_reported": {"kind": "tool_reported", "status": compressed["tool_reported"]["status"], "records": "tool-reported.csv" if tool_observations else None, "not_summed_across_different_estimator_units": True},
        "measured_billed": compressed["measured_billed"], "judge": compressed["judge"], "model_calls": 0,
        "limitations": [
            "Identified candidate range, not a validated upper bound. Code and mixed-code spans stay protected.",
            "Counts include retransmitted history and are not independent task observations.",
            "All squeez stdout, including headers, timing text and recovery markers, is counted; no external savings gate.",
            "Pattern counts exclude squeez metadata lines only for diagnostics, not for byte or token measurements.",
            "No model calls, native quality, recovery calls, cache response, billed usage or end-to-end costs are measured.",
        ],
    }
    save_json(output / "comparison.json", result)
    save_json(output / "swap-proof.json", {
        "kind": "verification", **common, "ledger_differences": ["compressor.name"],
        "same_source_input_sample_judge_and_schema": True,
        "schema_sha256": current["source_files"]["schemas/static-result.schema.json"],
        "no_op_identity": True, "protected_spans_unchanged": True, "model_calls": 0,
    })
    grouped = defaultdict(list)
    records = [json.loads(line) for line in (compressed_path / "records.jsonl").read_text().splitlines()]
    for record in records:
        grouped[record["sample"]["tasks"][0]].append(record)
    task_rows = []
    for task, selected in sorted(grouped.items()):
        total = aggregate(selected)
        before, after = (total["measured_local"][phase] for phase in ("before", "after"))
        task_rows.append({
            "task": task, "kind": "calculated", "source_commit": source_commit,
            "historical_runs": len(total["sample"]["historical_runs"]), "request_occurrences": total["sample"]["requests"],
            "candidate_span_occurrences": total["protection"]["candidate_segments"],
            "changed_span_occurrences": sum(observation["changed"] for observation in total["patterns"]["observations"]),
            "body_bytes_before": before["message_content_utf8_bytes"], "body_bytes_after": after["message_content_utf8_bytes"],
            "body_tokens_before": before["message_content_tokens"], "body_tokens_after": after["message_content_tokens"],
            "candidate_bytes_before": before["candidate_utf8_bytes"], "candidate_bytes_after": after["candidate_utf8_bytes"],
            "body_byte_saved_percent": total["reductions"]["saved_percent"]["message_content_utf8_bytes"],
            "body_token_saved_percent": total["reductions"]["saved_percent"]["message_content_tokens"],
            "deletion_body_token_saved_percent": total["deletion_reference"]["saved_percent"],
            "byte_unit": "UTF-8 bytes", "token_unit": "o200k_base message-content tokens",
        })
    write_csv(output / "by-task.csv", task_rows)
    pattern_names = list(pattern_observations[0]["before"]) if pattern_observations else []
    write_csv(output / "patterns.csv", [{
        "pattern": name, "kind": "classification_aggregation", "source_commit": source_commit,
        "span_occurrences": len(pattern_observations),
        "occurrences_with_pattern_before": sum(observation["before"][name] > 0 for observation in pattern_observations),
        "changed_occurrences_with_pattern_before": sum(observation["before"][name] > 0 and observation["changed"] for observation in pattern_observations),
        "matches_before": sum(observation["before"][name] for observation in pattern_observations),
        "matches_after": sum(observation["after"][name] for observation in pattern_observations),
        "unit": "regex matches or duplicate-line excess; overlapping diagnostics, not additive savings",
    } for name in pattern_names])
    tool_rows = []
    for observation in tool_observations:
        reported = observation["report"]
        metrics = reported["metrics"] or [{"name": "unavailable", "value": None, "unit": "unavailable"}]
        for metric in metrics:
            tool_rows.append({
                "request_id": observation["request_id"], "span_index": observation["span_index"],
                "kind": "tool_reported", "source_commit": source_commit, "status": reported["status"],
                "metric": metric["name"], "value": metric["value"], "unit": metric["unit"],
                "header": "\n".join(reported["headers"]), "not_provider_usage": True,
            })
    write_csv(output / "tool-reported.csv", tool_rows)
    manifest = json.loads((compressed_path / "manifest.json").read_bytes())
    encoder = load_encoder(compressed_ledger["measurement"])
    span_rows = []
    for request_index, request in enumerate(manifest["requests"]):
        source = (compressed_path / f"originals/{request_index:04d}.json").read_bytes()
        guard = FrozenRequestGuard(source, request["sha256"], request["segments"])
        for span_index, original in enumerate(guard.candidate_texts()):
            replacement_path = f"replacements/{request_index:04d}/{span_index:04d}.txt"
            replacement = (compressed_path / replacement_path).read_bytes().decode("utf-8")
            span_rows.append({
                "request_id": request["record_id"], "task": request["task"], "span_index": span_index,
                "kind": "measured", "source": "local_utf8_and_tiktoken", "source_commit": source_commit,
                "input_bytes": len(original.encode("utf-8")), "output_bytes": len(replacement.encode("utf-8")),
                "input_local_tokens": token_count(original, encoder), "output_local_tokens": token_count(replacement, encoder),
                "byte_unit": "UTF-8 bytes", "token_unit": "o200k_base tokens; span encoded separately",
                "replacement_artifact": replacement_path,
            })
    write_csv(output / "spans-local.csv", span_rows)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("compressed", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    result = compare(args.baseline, args.compressed, args.output, args.source_commit)
    print(json.dumps({"output": str(args.output), "reductions": result["reductions"], "deletion_gap": result["deletion_gap"]}))


if __name__ == "__main__":
    main()
