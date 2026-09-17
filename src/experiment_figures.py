"""Generate public preliminary-comparison charts from one reviewed aggregate."""

from __future__ import annotations

import argparse
from html import escape
import json
import math
from pathlib import Path
import re

from .protection import digest


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/experiment/preliminary-comparison-summary.json"
OUTPUTS = {
    "quality": ROOT / "figures/preliminary-quality.svg",
    "changed_conditions": ROOT / "figures/preliminary-changed-conditions.svg",
    "changed_spans": ROOT / "figures/preliminary-changed-spans.svg",
    "requests": ROOT / "figures/preliminary-request-events.svg",
    "provider_usage": ROOT / "figures/preliminary-provider-usage.svg",
    "calculated_cost": ROOT / "figures/preliminary-calculated-cost.svg",
}
COLORS = ("#2457a6", "#d97706", "#16856b", "#8b5cf6")


def _integer(value: str) -> int:
    return int(value.replace(",", "").removesuffix("건"))


def _money(value: str) -> float:
    return float(value.removeprefix("$").replace(",", ""))


def _table_after(markdown: str, heading: str) -> tuple[list[str], list[list[str]]]:
    start = markdown.index(heading)
    lines = markdown[start:].splitlines()
    table = []
    started = False
    candidates = lines if lines[0].startswith("|") else lines[1:]
    for line in candidates:
        if line.startswith("|"):
            started = True
            table.append([cell.strip().strip("`") for cell in line.strip()[1:-1].split("|")])
        elif started:
            break
    if len(table) < 3:
        raise ValueError(f"Missing public aggregate table after {heading}")
    return table[0], table[2:]


def _rows(rows: list[list[str]]) -> dict[str, list[str]]:
    return {row[0]: row[1:] for row in rows if row[0] != "합계"}


def load_aggregate(path: Path = DATA) -> dict:
    value = json.loads(path.read_bytes())
    if value.get("schema_version") != 1 or value.get("kind") != "public_preliminary_comparison_aggregate":
        raise ValueError("Unexpected preliminary aggregate contract")
    source = ROOT / value["source"]["path"]
    markdown_bytes = source.read_bytes()
    if digest(markdown_bytes) != value["source"]["sha256"]:
        raise ValueError("Public aggregate source document changed")
    markdown = markdown_bytes.decode()
    conditions = value["conditions"]

    _, quality_rows = _table_after(markdown, "### 답을 맞힌 조건은 몇 개인가")
    quality = _rows(quality_rows)
    for condition in conditions:
        expected = value["quality"]["by_condition"][condition]
        if [_integer(item) for item in quality[condition][:2]] != [expected["pass"], expected["wrong_answer"]]:
            raise ValueError("Quality aggregate differs from its public table")

    _, change_rows = _table_after(markdown, "### 실제 문자열은 얼마나 바뀌었나")
    changes = _rows(change_rows)
    for condition in conditions:
        expected = value["changes"]["by_condition"][condition]
        if [_integer(item) for item in changes[condition]] != [
            expected["changed_conditions"], expected["unchanged_conditions"], expected["changed_spans"],
        ]:
            raise ValueError("Change aggregate differs from its public table")
    token_match = re.search(r"738건.*209건.*529건.*`97,723 → 50,824`토큰.*166건", markdown)
    if token_match is None:
        raise ValueError("Changed-span token scope differs from the public report")

    _, request_rows = _table_after(markdown, "### 요청, API 사용량과 비용은 어떻게 읽나")
    requests = _rows(request_rows)
    request_fields = ("logical_model_calls", "provider_http_attempts", "successful_http_responses", "delivered_responses")
    for condition in conditions:
        if [_integer(item) for item in requests[condition]] != [
            value["requests"]["by_condition"][condition][field] for field in request_fields
        ]:
            raise ValueError("Request aggregate differs from its public table")

    usage_heading = "| 조건 | 입력 토큰 | 캐시 토큰 | 출력 토큰 |"
    _, usage_rows = _table_after(markdown, usage_heading)
    usage = _rows(usage_rows)
    usage_fields = ("input_tokens", "cached_input_tokens", "output_tokens")
    for condition in conditions:
        if [_integer(item) for item in usage[condition]] != [
            value["provider_usage"]["by_condition"][condition][field] for field in usage_fields
        ]:
            raise ValueError("Provider-usage aggregate differs from its public table")

    cost_heading = "| 조건 | API 계산 비용 | HTTP 시도 | HTTP 시도당 비용 |"
    _, cost_rows = _table_after(markdown, cost_heading)
    costs = _rows(cost_rows)
    for condition in conditions:
        if _money(costs[condition][0]) != value["calculated_cost"]["by_condition"][condition]:
            raise ValueError("Calculated-cost aggregate differs from its public table")
    return value


def _format(value: float, unit: str) -> str:
    if unit == "USD":
        return f"${value:,.7f}".rstrip("0").rstrip(".")
    return f"{int(value):,}"


def _axis_maximum(value: float, unit: str) -> float:
    if unit == "USD":
        return value
    return math.ceil(value / 4) * 4


def render_chart(
    *,
    title: str,
    description: str,
    unit: str,
    conditions: list[str],
    series: list[tuple[str, list[float]]],
    source_sha256: str,
) -> str:
    width = 1040
    row_height = 58 + 22 * max(0, len(series) - 1)
    height = 155 + row_height * len(conditions) + 75
    plot_left, plot_width = 260, 690
    maximum = max(value for _, values in series for value in values) or 1
    axis_maximum = _axis_maximum(maximum, unit)
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(title)}</title>',
        f'<desc id="desc">{escape(description)}</desc>',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<g font-family="Arial, sans-serif" font-variant-numeric="tabular-nums" fill="#17202a">',
        f'<text x="32" y="38" font-size="23" font-weight="600">{escape(title)}</text>',
        f'<text x="32" y="65" font-size="13">Unit: {escape(unit)}</text>',
    ]
    for index, (label, _) in enumerate(series):
        x = 32 + index * 210
        elements.extend((
            f'<rect x="{x}" y="84" width="14" height="12" fill="{COLORS[index]}"/>',
            f'<text x="{x + 21}" y="95" font-size="13">{escape(label)}</text>',
        ))
    for tick in range(5):
        value = axis_maximum * tick / 4
        x = plot_left + plot_width * tick / 4
        elements.append(f'<path d="M{x:.2f},116 V{height - 66}" stroke="#dce1e6"/>')
        elements.append(f'<text x="{x:.2f}" y="{height - 46}" text-anchor="middle" font-size="11">{escape(_format(value, unit))}</text>')
    bar_height = 15
    for condition_index, condition in enumerate(conditions):
        top = 130 + condition_index * row_height
        elements.append(f'<text x="32" y="{top + 18}" font-size="14" font-weight="600">{escape(condition)}</text>')
        for series_index, (_, values) in enumerate(series):
            value = values[condition_index]
            y = top + series_index * 22
            bar_width = plot_width * value / axis_maximum
            elements.append(f'<rect x="{plot_left}" y="{y}" width="{bar_width:.3f}" height="{bar_height}" fill="{COLORS[series_index]}"/>')
            elements.append(f'<text x="{plot_left + bar_width + 7:.3f}" y="{y + 12}" font-size="12">{escape(_format(value, unit))}</text>')
    elements.extend((
        f'<text x="32" y="{height - 20}" font-size="11">Aggregate source SHA-256: {escape(source_sha256)}</text>',
        '</g></svg>',
    ))
    return "\n".join(elements) + "\n"


def render_all(value: dict) -> dict[str, str]:
    conditions = value["conditions"]
    source_sha256 = digest(DATA.read_bytes())
    quality = value["quality"]["by_condition"]
    changes = value["changes"]["by_condition"]
    requests = value["requests"]["by_condition"]
    usage = value["provider_usage"]["by_condition"]
    costs = value["calculated_cost"]["by_condition"]
    return {
        "quality": render_chart(
            title="Preliminary quality outcomes by condition",
            description="Pass and wrong-answer counts among 104 completed conditions. One run per condition; not a compressor ranking.",
            unit="conditions",
            conditions=conditions,
            series=[
                ("pass", [quality[name]["pass"] for name in conditions]),
                ("wrong_answer", [quality[name]["wrong_answer"] for name in conditions]),
            ],
            source_sha256=source_sha256,
        ),
        "changed_conditions": render_chart(
            title="Conditions with and without string changes",
            description="Changed and unchanged condition counts among 104 completed conditions. Change presence does not establish quality or cost causation.",
            unit="conditions",
            conditions=conditions,
            series=[
                ("changed", [changes[name]["changed_conditions"] for name in conditions]),
                ("unchanged", [changes[name]["unchanged_conditions"] for name in conditions]),
            ],
            source_sha256=source_sha256,
        ),
        "changed_spans": render_chart(
            title="Recorded changed spans by condition",
            description="Counts of changed string spans, separate from changed-condition counts and API usage. Missing source pairs are not zero.",
            unit="changed spans",
            conditions=conditions,
            series=[("changed spans", [changes[name]["changed_spans"] for name in conditions])],
            source_sha256=source_sha256,
        ),
        "requests": render_chart(
            title="Four separately recorded request events",
            description="Logical model calls, provider HTTP attempts, successful responses, and delivered responses. Equal observed counts do not make them the same event or a progress percentage.",
            unit="events",
            conditions=conditions,
            series=[
                ("logical calls", [requests[name]["logical_model_calls"] for name in conditions]),
                ("HTTP attempts", [requests[name]["provider_http_attempts"] for name in conditions]),
                ("success responses", [requests[name]["successful_http_responses"] for name in conditions]),
                ("delivered responses", [requests[name]["delivered_responses"] for name in conditions]),
            ],
            source_sha256=source_sha256,
        ),
        "provider_usage": render_chart(
            title="Provider-reported token usage by condition",
            description="Input, cached-input, and output token totals for the 104 completed conditions. These are whole API usage, not changed-span local tokens.",
            unit="provider-reported tokens",
            conditions=conditions,
            series=[
                ("input", [usage[name]["input_tokens"] for name in conditions]),
                ("cached input", [usage[name]["cached_input_tokens"] for name in conditions]),
                ("output", [usage[name]["output_tokens"] for name in conditions]),
            ],
            source_sha256=source_sha256,
        ),
        "calculated_cost": render_chart(
            title="API usage multiplied by the fixed price table",
            description="Calculated US-dollar costs for the 104 completed conditions. The values are not reconciled invoices and do not establish savings caused by compression.",
            unit="USD",
            conditions=conditions,
            series=[("calculated cost", [costs[name] for name in conditions])],
            source_sha256=source_sha256,
        ),
    }


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(arguments)
    generated = render_all(load_aggregate())
    for name, content in generated.items():
        path = OUTPUTS[name]
        if args.check:
            if path.read_text() != content:
                raise ValueError(f"Generated experiment figure differs: {path.name}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    print(json.dumps({"figures": len(generated), "source": DATA.relative_to(ROOT).as_posix()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
