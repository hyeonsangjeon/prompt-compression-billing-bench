"""Reproduce a historical candidate-share chart from reviewed aggregate bytes."""

from __future__ import annotations

import argparse
import csv
from html import escape
import json
from pathlib import Path

from .protection import digest


NUMERIC_FIELDS = (
    "historical_runs", "successful_http_requests", "message_content_utf8_bytes",
    "round1_candidate_utf8_bytes", "round2_candidate_utf8_bytes",
)
FIELDS = ("dataset", "task", *NUMERIC_FIELDS, "kind", "unit")


def load_aggregates(table: Path, lineage_path: Path) -> tuple[list[dict], dict]:
    lineage = json.loads(lineage_path.read_bytes())
    if digest(table.read_bytes()) != lineage["aggregate_sha256"]:
        raise ValueError("Aggregate CSV differs from its reviewed lineage")
    with table.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(FIELDS):
            raise ValueError("Unexpected aggregate fields")
        rows = list(reader)
    for row in rows:
        for name in NUMERIC_FIELDS:
            row[name] = int(row[name])
            if row[name] < 0:
                raise ValueError("Aggregate counts must be nonnegative")
        if row["kind"] != "classification_aggregation" or row["unit"] != "UTF-8 message-content bytes":
            raise ValueError("Aggregate provenance or units differ")
        if not 0 <= row["round1_candidate_utf8_bytes"] <= row["round2_candidate_utf8_bytes"] <= row["message_content_utf8_bytes"]:
            raise ValueError("Candidate byte counts exceed the message-content denominator")
    if not rows or len({row["task"] for row in rows}) != len(rows):
        raise ValueError("Expected distinct task aggregates")
    totals = {name: sum(row[name] for row in rows) for name in NUMERIC_FIELDS}
    if totals != lineage["expected_totals"]:
        raise ValueError("Aggregate totals changed in either direction")
    return rows, lineage


def render(rows: list[dict], lineage: dict) -> str:
    maximum = 40
    plot_left, plot_width = 315, 510
    elements = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="920" height="470" viewBox="0 0 920 470" role="img" aria-labelledby="title desc">',
        '<title id="title">Identified log-candidate bytes by task, two classification rounds</title>',
        f'<desc id="desc">{escape(lineage["selection"])}. {escape(lineage["scope"])}.</desc>',
        '<rect width="920" height="470" fill="#ffffff"/>',
        '<g font-family="sans-serif" fill="#17202a">',
        '<text x="32" y="34" font-size="21">Identified log candidates, not achieved compression</text>',
        '<text x="32" y="60" font-size="13">UTF-8 candidate bytes / complete message-content bytes, including retransmitted history</text>',
        '<rect x="32" y="79" width="14" height="10" fill="#9aafc9"/><text x="53" y="89" font-size="13">Round 1 classification</text>',
        '<rect x="260" y="79" width="14" height="10" fill="#295f99"/><text x="281" y="89" font-size="13">Round 2 classification</text>',
    ]
    for tick in range(0, maximum + 1, 10):
        horizontal = plot_left + plot_width * tick / maximum
        elements.append(f'<path d="M{horizontal:.2f},115 V382" stroke="#dce1e6" stroke-dasharray="3 4"/>')
        elements.append(f'<text x="{horizontal:.2f}" y="401" text-anchor="middle" font-size="12">{tick}%</text>')
    for index, row in enumerate(rows):
        vertical = 130 + index * 52
        elements.append(f'<text x="32" y="{vertical + 10}" font-size="14">{escape(row["task"])}</text>')
        elements.append(f'<text x="32" y="{vertical + 28}" font-size="11" fill="#526171">{row["historical_runs"]} runs; {row["successful_http_requests"]} request occurrences</text>')
        for offset, field, color in ((0, "round1_candidate_utf8_bytes", "#9aafc9"), (17, "round2_candidate_utf8_bytes", "#295f99")):
            share = 100 * row[field] / row["message_content_utf8_bytes"]
            width = plot_width * share / maximum
            elements.append(f'<rect x="{plot_left}" y="{vertical + offset}" width="{width:.3f}" height="12" fill="{color}"/>')
            elements.append(f'<text x="{plot_left + width + 6:.3f}" y="{vertical + offset + 11}" font-size="12">{share:.2f}%</text>')
    elements.extend([
        '<text x="32" y="433" font-size="12">5 purpose-selected tasks, 15 historical runs, 56 successful HTTP request occurrences; not a population estimate.</text>',
        '<text x="32" y="454" font-size="12">Code and code-containing mixed spans remain protected. Identified candidate range, not a validated upper bound.</text>',
        '</g></svg>',
    ])
    return "\n".join(elements) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, default=Path("data/eda/task-candidate-share.csv"))
    parser.add_argument("--lineage", type=Path, default=Path("data/eda/lineage.json"))
    parser.add_argument("--output", type=Path, default=Path("figures/task-candidate-share.svg"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rows, lineage = load_aggregates(args.table, args.lineage)
    generated = render(rows, lineage)
    if args.check:
        if args.output.read_text(encoding="utf-8") != generated:
            raise ValueError("Figure differs from the reviewed aggregate data")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(generated, encoding="utf-8")
    print(f"Verified aggregate lineage and chart: {args.output}")


if __name__ == "__main__":
    main()
