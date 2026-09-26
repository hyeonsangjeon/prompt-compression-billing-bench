"""Generate paired Cache execution-denominator diagrams from the canonical report."""

from __future__ import annotations

import argparse
from copy import deepcopy
from html import escape
import json
from pathlib import Path
import re

from .protection import digest


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs_en/experiment/02-follow-up/cache-reuse/execution-20260923.md"
REPORT_SHA256 = "9639c2f21142378727082d0b3b142348b15941b8e1c538232c9b10f5075f058c"
OUTPUTS = {
    "ko": ROOT / "figures/follow-up/cache-execution-denominators-ko.svg",
    "en": ROOT / "figures/follow-up/cache-execution-denominators-en.svg",
}
SVG_WIDTH = 390
SVG_HEIGHT = 1152
CARD_X = 18
CARD_WIDTH = 354
FACTS = {
    "plan": {"cycles": 10, "bundles": 60, "task_trials": 300},
    "observed": {
        "cycles_attempted": 1,
        "cycles_valid": 0,
        "cycles_invalid": 1,
        "replacement": 0,
        "bundles_started": 2,
        "bundles_complete": 1,
        "bundles_incomplete": 1,
        "task_trials_started": 6,
        "task_trials_complete": 5,
        "task_trials_incomplete": 1,
    },
    "stop": {
        "condition": "none",
        "reuse": 1,
        "predecessor_reuse": 0,
        "task": "cancel-async-tasks",
        "ordinal": 3,
        "predecessor_requests": 2,
        "dispatch": "rejected_before_dispatch",
    },
    "descriptive": {
        "successful_provider_calls": 18,
        "completed_trial_quality": "3/5",
        "eligible_tasks": 2,
        "not_applicable_tasks": 3,
        "cached_input_tokens": 0,
    },
    "terminal_status": "stopped_invalid_cycle",
}
REPORT_RECORD = {
    "source_commit": "e78a32edca9d5ce4f991700e3a299d72164e94be",
    "source_tree": "63f969519c93a58faf800ed91cc464f9b955fe2b",
    "conditions": "none,squeez",
    "reuse_order": "0,1,2",
    "tasks_per_cell": 5,
    "concurrency": 1,
    "initial_valid_cycles": 10,
    "initial_bundles": 60,
    "initial_task_trials": 300,
    "maximum_valid_cycles": 20,
    "cycles_attempted": 1,
    "cycles_valid": 0,
    "cycles_invalid": 1,
    "replacement_cycles": 0,
    "bundles_started": 2,
    "bundles_complete": 1,
    "bundles_incomplete": 1,
    "task_trials_started": 6,
    "task_trials_complete": 5,
    "task_trials_incomplete": 1,
    "successful_provider_calls": 18,
    "input_tokens": 65423,
    "cached_input_tokens": 0,
    "output_tokens": 9690,
    "input_cost_usd": "0.1635575",
    "output_cost_usd": "0.14535",
    "total_cost_usd": "0.3089075",
    "invoice_status": "not_measured",
    "completed_trial_quality": "3/5",
    "eligible_tasks": 2,
    "not_applicable_tasks": 3,
    "stop_condition": "none",
    "stop_reuse": 1,
    "predecessor_reuse": 0,
    "stop_task": "cancel-async-tasks",
    "stop_ordinal": 3,
    "predecessor_request_count": 2,
    "dispatch_status": "rejected_before_dispatch",
    "terminal_status": "stopped_invalid_cycle",
    "execution_time_status": "date_window_timezone_not_retained",
    "cache_comparison_status": "not_computed_zero_valid_cycles",
    "cached_input_interpretation": "input_subset_not_additive_not_effect_or_miss_rate",
    "quality_scope": "completed_trials_only_not_condition_or_general_quality",
}
REPORT_SEMANTIC_PATTERNS = {
    "comparison non-finding": r"no Cache-effect (?:estimate|comparison)[^.]*computed",
    "cached-input boundary": (
        r"cached input[^.]{0,250}not (?:an |a Cache-)?effect estimate"
        r"[^.]{0,120}not (?:a )?miss rate"
    ),
    "invoice boundary": r"not a reconciled invoice",
    "quality boundary": r"not a `none` versus `squeez` comparison[^.]*general model-quality claim",
    "absent pair": r"No differing prefix or prefix length was measured for the absent ordinal-3 pair",
    "time boundary": r"does not retain an execution date, time window, or timezone",
    "task strata": r"two eligible and three `not_applicable` for the primary cache denominator",
    "causal uncertainty": (
        r"(?:evidence|record|run)[^.]{0,80}(?:did not|could not)[^.]{0,80}"
        r"(?:isolate|determine|establish)[^.]{0,240}"
        r"(?:request-count difference|difference in request counts)"
    ),
}
REPORT_FORBIDDEN_PATTERNS = {
    "causal promotion": (
        r"(?:evidence|record|run)[^.]{0,80}"
        r"(?:established|proved|showed|demonstrated)[^.]{0,120}"
        r"compression caused[^.]{0,120}(?:request-count difference|difference in request counts)"
    ),
}


def _normalized(value: str) -> str:
    return " ".join(value.split())


def _row_cells(markdown: str, label: str) -> list[str]:
    matches = []
    for line in markdown.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and cells[0] == label:
            matches.append(cells)
    if len(matches) != 1:
        raise ValueError(f"Cache report row count changed: {label}")
    return matches[0]


def _integer(value: str, label: str) -> int:
    if re.fullmatch(r"[0-9][0-9,]*", value) is None:
        raise ValueError(f"Cache report integer changed: {label}")
    return int(value.replace(",", ""))


def _initial_count(value: str, label: str) -> int:
    match = re.fullmatch(r"([0-9][0-9,]*) initially", value)
    if match is None:
        raise ValueError(f"Cache report planned count changed: {label}")
    return _integer(match.group(1), label)


def _record_value(markdown: str, field: str) -> str:
    cells = _row_cells(markdown, f"`{field}`")
    if len(cells) != 2 or re.fullmatch(r"`[^`]+`", cells[1]) is None:
        raise ValueError(f"Cache report fact record changed: {field}")
    return cells[1][1:-1]


def parse_report_record(markdown: str) -> dict:
    parsed = {}
    for field, expected in REPORT_RECORD.items():
        value = _record_value(markdown, field)
        parsed[field] = _integer(value, field) if isinstance(expected, int) else value
    return parsed


def parse_report_facts(markdown: str) -> dict:
    record = parse_report_record(markdown)
    return {
        "plan": {
            "cycles": record["initial_valid_cycles"],
            "bundles": record["initial_bundles"],
            "task_trials": record["initial_task_trials"],
        },
        "observed": {
            "cycles_attempted": record["cycles_attempted"],
            "cycles_valid": record["cycles_valid"],
            "cycles_invalid": record["cycles_invalid"],
            "replacement": record["replacement_cycles"],
            "bundles_started": record["bundles_started"],
            "bundles_complete": record["bundles_complete"],
            "bundles_incomplete": record["bundles_incomplete"],
            "task_trials_started": record["task_trials_started"],
            "task_trials_complete": record["task_trials_complete"],
            "task_trials_incomplete": record["task_trials_incomplete"],
        },
        "stop": {
            "condition": record["stop_condition"],
            "reuse": record["stop_reuse"],
            "predecessor_reuse": record["predecessor_reuse"],
            "task": record["stop_task"],
            "ordinal": record["stop_ordinal"],
            "predecessor_requests": record["predecessor_request_count"],
            "dispatch": record["dispatch_status"],
        },
        "descriptive": {
            "successful_provider_calls": record["successful_provider_calls"],
            "completed_trial_quality": record["completed_trial_quality"],
            "eligible_tasks": record["eligible_tasks"],
            "not_applicable_tasks": record["not_applicable_tasks"],
            "cached_input_tokens": record["cached_input_tokens"],
        },
        "terminal_status": record["terminal_status"],
    }


def _visible_denominators(markdown: str) -> dict:
    cycle_cells = _row_cells(markdown, "Cycles")
    bundle_cells = _row_cells(markdown, "Bundles")
    trial_cells = _row_cells(markdown, "Task trials")
    if any(len(cells) != 6 for cells in (cycle_cells, bundle_cells, trial_cells)):
        raise ValueError("Cache report denominator columns changed")
    return {
        "initial_valid_cycles": _initial_count(cycle_cells[1], "cycles"),
        "cycles_attempted": _integer(cycle_cells[2], "cycles attempted"),
        "cycles_valid": _integer(cycle_cells[3], "cycles valid"),
        "cycles_invalid": _integer(cycle_cells[4], "cycles invalid"),
        "replacement_cycles": _integer(cycle_cells[5], "cycle replacement"),
        "initial_bundles": _initial_count(bundle_cells[1], "bundles"),
        "bundles_started": _integer(bundle_cells[2], "bundles started"),
        "bundles_complete": _integer(bundle_cells[3], "bundles complete"),
        "bundles_incomplete": _integer(bundle_cells[4], "bundles incomplete"),
        "initial_task_trials": _initial_count(trial_cells[1], "task trials"),
        "task_trials_started": _integer(trial_cells[2], "task trials started"),
        "task_trials_complete": _integer(trial_cells[3], "task trials complete"),
        "task_trials_incomplete": _integer(trial_cells[4], "task trials incomplete"),
    }


def validate_report(markdown: str) -> None:
    record = parse_report_record(markdown)
    if record != REPORT_RECORD:
        raise ValueError("Cache canonical factual record changed")
    if parse_report_facts(markdown) != FACTS:
        raise ValueError("Cache accepted facts differ from the canonical report")

    visible = _visible_denominators(markdown)
    for field, value in visible.items():
        if value != record[field]:
            raise ValueError(f"Cache visible denominator differs from fact record: {field}")

    source = _row_cells(markdown, "Source")
    source_match = (
        re.fullmatch(r"Commit `([0-9a-f]{40})`; tree `([0-9a-f]{40})`", source[1])
        if len(source) == 2
        else None
    )
    if (
        len(source) != 2
        or source_match is None
        or source_match.groups() != (record["source_commit"], record["source_tree"])
    ):
        raise ValueError("Cache visible source differs from fact record")

    visible_rows = {
        "successful_provider_calls": ("Successful provider calls", 1),
        "input_tokens": ("Input", 1),
        "cached_input_tokens": ("Cached input", 1),
        "output_tokens": ("Output", 1),
    }
    for field, (label, column) in visible_rows.items():
        cells = _row_cells(markdown, label)
        if _integer(cells[column], field) != record[field]:
            raise ValueError(f"Cache visible value differs from fact record: {field}")

    visible_costs = {
        "input_cost_usd": "Input cost",
        "output_cost_usd": "Output cost",
        "total_cost_usd": "Total calculated cost",
    }
    for field, label in visible_costs.items():
        cells = _row_cells(markdown, label)
        if len(cells) != 3 or cells[1] != f'${record[field]}':
            raise ValueError(f"Cache visible cost differs from fact record: {field}")

    narrative = markdown.split("## Factual guard record", 1)[0]
    normalized = _normalized(narrative)
    for label, pattern in REPORT_SEMANTIC_PATTERNS.items():
        if re.search(pattern, normalized, flags=re.IGNORECASE) is None:
            raise ValueError(f"Cache report semantic boundary changed: {label}")
    for label, pattern in REPORT_FORBIDDEN_PATTERNS.items():
        if re.search(pattern, normalized, flags=re.IGNORECASE) is not None:
            raise ValueError(f"Cache report forbidden claim introduced: {label}")


def load_facts(path: Path = REPORT, expected_sha256: str = REPORT_SHA256) -> dict:
    report_bytes = path.read_bytes()
    markdown = report_bytes.decode("utf-8")
    validate_report(markdown)
    if digest(report_bytes) != expected_sha256:
        raise ValueError("Cache report SHA-256 changed")
    parsed = parse_report_facts(markdown)
    if parsed != FACTS:
        raise ValueError("Cache accepted facts differ from the canonical report")
    return deepcopy(parsed)


COPY = {
    "ko": {
        "title": "Cache 비교: 계획, 부분 실행과 중단",
        "display_title": "Cache 비교가 멈춘 지점",
        "subtitle": "계획과 관측을 같은 단위 안에서 비교",
        "section_denominators": "계획과 관측",
        "section_stop": "짝이 없는 요청에서 멈춘 순서",
        "context_title": "부분 실행이 말해 주는 범위",
        "claim_boundary": ("Cache·재사용 효과 계산 안 함", "압축 효과 계산 안 함"),
    },
    "en": {
        "title": "Cache comparison: plan, partial run, and stop",
        "display_title": "Cache comparison stop",
        "subtitle": "Plan and observation by unit",
        "section_denominators": "Plan and observation",
        "section_stop": "Stop at the unmatched request",
        "context_title": "What the partial run shows",
        "claim_boundary": ("No Cache/reuse effect computed", "No compression effect computed"),
    },
}
COPY_SHA256 = {
    "ko": "26ad1c3c8597705e2bab90ebbaee7a18e7f8c6fbd0d133560709587212e245d3",
    "en": "b5b220ed974d5e19e8a3bfa4e3e0d31f54102f855624bc17a61c79380842919d",
}


def validate_copy(language: str) -> None:
    payload = json.dumps(
        COPY[language], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if digest(payload) != COPY_SHA256[language]:
        raise ValueError("Cache localized copy differs from the reviewed display contract")


def build_display(facts: dict, language: str) -> dict:
    validate_copy(language)
    copy = COPY[language]
    plan = facts["plan"]
    observed = facts["observed"]
    stop = facts["stop"]
    descriptive = facts["descriptive"]
    if stop["dispatch"] != "rejected_before_dispatch":
        raise ValueError("Cache stop display differs from the canonical dispatch status")
    if language == "ko":
        return {
            **copy,
            "description": (
                f'사이클, 실행 묶음, 과제 실행의 계획과 관측을 단위별로 비교하고, '
                f'선행 요청이 없었던 논리 요청 순번 {stop["ordinal"]}에서 현재 요청을 '
                "제공자 전송 전에 거부한 흐름을 보여 준다."
            ),
            "cards": (
                (
                    "사이클",
                    f'계획 · 유효 {plan["cycles"]}개',
                    (
                        f'관측 · {observed["cycles_attempted"]}개 시도 · {observed["cycles_valid"]}개 유효',
                        f'{observed["cycles_invalid"]}개 무효 · 대체 {observed["replacement"]}개',
                    ),
                ),
                (
                    "실행 묶음",
                    f'계획 · {plan["bundles"]}개',
                    (
                        f'관측 · {observed["bundles_started"]}개 시작 · {observed["bundles_complete"]}개 완결',
                        f'{observed["bundles_incomplete"]}개 미완결·무효',
                    ),
                ),
                (
                    "과제 실행",
                    f'계획 · {plan["task_trials"]}개',
                    (
                        f'관측 · {observed["task_trials_started"]}개 시작 · {observed["task_trials_complete"]}개 완결',
                        f'{observed["task_trials_incomplete"]}개 미완결',
                    ),
                ),
            ),
            "flow": (
                (
                    "1. 선행 실행",
                    f'{stop["condition"]} · 재사용 {stop["predecessor_reuse"]}',
                    f'선행 요청 {stop["predecessor_requests"]}개',
                ),
                (
                    "2. 현재 실행",
                    f'{stop["condition"]} · 재사용 {stop["reuse"]}',
                    f'{stop["task"]} · 순번 {stop["ordinal"]}',
                ),
                (
                    "3. 비교 쌍 없음",
                    f'선행 실행에는 요청 {stop["predecessor_requests"]}개',
                    f'순번 {stop["ordinal"]}의 선행 요청 없음',
                ),
                (
                    "4. 검증 중단",
                    "현재 요청을 제공자 전송 전 거부",
                    "접두부 차이·길이 측정 없음",
                ),
            ),
            "context": (
                "부분 실행 설명값",
                f'성공한 제공자 응답 {descriptive["successful_provider_calls"]}회',
                f'완결 과제: {descriptive["completed_trial_quality"]} 통과',
                f'유효 사이클 {observed["cycles_valid"]}개',
                *copy["claim_boundary"],
            ),
        }
    return {
        **copy,
        "description": (
            "Cycles, bundles, and task trials compare plan with observation within each unit. "
            f'The sequence ends before provider dispatch at ordinal {stop["ordinal"]}, where '
            "no predecessor request existed."
        ),
        "cards": (
            (
                "Cycles",
                f'PLAN · {plan["cycles"]} valid',
                (
                    f'OBSERVED · {observed["cycles_attempted"]} attempted · {observed["cycles_valid"]} valid',
                    f'{observed["cycles_invalid"]} invalid · {observed["replacement"]} replacement',
                ),
            ),
            (
                "Bundles",
                f'PLAN · {plan["bundles"]}',
                (
                    f'OBSERVED · {observed["bundles_started"]} started · {observed["bundles_complete"]} complete',
                    f'{observed["bundles_incomplete"]} incomplete / invalid',
                ),
            ),
            (
                "Task trials",
                f'PLAN · {plan["task_trials"]}',
                (
                    f'OBSERVED · {observed["task_trials_started"]} started · {observed["task_trials_complete"]} complete',
                    f'{observed["task_trials_incomplete"]} incomplete',
                ),
            ),
        ),
        "flow": (
            (
                "1. Predecessor run",
                f'{stop["condition"]} · reuse {stop["predecessor_reuse"]}',
                f'{stop["predecessor_requests"]} predecessor requests',
            ),
            (
                "2. Current run",
                f'{stop["condition"]} · reuse {stop["reuse"]}',
                f'{stop["task"]} · ordinal {stop["ordinal"]}',
            ),
            (
                "3. No request pair",
                f'predecessor run had {stop["predecessor_requests"]} requests',
                f'no request at ordinal {stop["ordinal"]}',
            ),
            (
                "4. Validation stop",
                "current request rejected pre-dispatch",
                "no prefix difference/length measured",
            ),
        ),
        "context": (
            "Partial-run context",
            f'{descriptive["successful_provider_calls"]} successful provider responses',
            f'Completed trials: {descriptive["completed_trial_quality"]} passed',
            f'{observed["cycles_valid"]} valid cycles',
            *copy["claim_boundary"],
        ),
    }


def validate_display(facts: dict, language: str, display: dict) -> None:
    if display != build_display(facts, language):
        raise ValueError("Cache displayed facts differ from the validated fact model")


def _text(
    elements: list[str],
    x: int,
    y: int,
    value: str,
    *,
    size: int = 16,
    weight: int = 400,
    fill: str = "#17202a",
    anchor: str | None = None,
) -> None:
    anchor_attribute = f' text-anchor="{anchor}"' if anchor else ""
    elements.append(
        f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
        f'fill="{fill}"{anchor_attribute}>{escape(value)}</text>'
    )


def render_svg_from_display(facts: dict, language: str, display: dict) -> str:
    if facts != load_facts():
        raise ValueError("Cache figure facts differ from the accepted specification")
    validate_display(facts, language, display)
    copy = display
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SVG_WIDTH}" height="{SVG_HEIGHT}" viewBox="0 0 {SVG_WIDTH} {SVG_HEIGHT}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(copy["title"])}</title>',
        f'<desc id="desc">{escape(copy["description"])}</desc>',
        f'<metadata>source-report-sha256:{REPORT_SHA256}</metadata>',
        f'<rect width="{SVG_WIDTH}" height="{SVG_HEIGHT}" fill="#ffffff"/>',
        '<g font-family="sans-serif" font-variant-numeric="tabular-nums">',
    ]
    _text(elements, CARD_X, 38, copy["display_title"], size=24, weight=700)
    _text(elements, CARD_X, 68, copy["subtitle"], size=18, fill="#44515f")
    _text(elements, CARD_X, 108, copy["section_denominators"], size=20, weight=700)

    for card_index, (name, plan, observations) in enumerate(copy["cards"]):
        card_y = 124 + 124 * card_index
        elements.append(
            f'<rect x="{CARD_X}" y="{card_y}" width="{CARD_WIDTH}" height="114" rx="12" '
            'fill="#f7f9fb" stroke="#7a8794" stroke-width="2"/>'
        )
        _text(elements, CARD_X + 16, card_y + 28, name, size=20, weight=700)
        _text(elements, CARD_X + 16, card_y + 56, plan, size=18, weight=700, fill="#2457a6")
        for line_index, line in enumerate(observations):
            _text(elements, CARD_X + 16, card_y + 82 + 22 * line_index, line, size=18)

    _text(elements, CARD_X, 522, copy["section_stop"], size=20, weight=700)
    flow_y_positions = (544, 644, 744, 844)
    for flow_index, (flow_y, lines) in enumerate(zip(flow_y_positions, copy["flow"], strict=True)):
        border = "#b45309" if flow_index >= 2 else "#52708f"
        dash = ' stroke-dasharray="7 5"' if flow_index >= 2 else ""
        elements.append(
            f'<rect x="{CARD_X}" y="{flow_y}" width="{CARD_WIDTH}" height="82" rx="10" fill="#ffffff" '
            f'stroke="{border}" stroke-width="2"{dash}/>'
        )
        for line_index, line in enumerate(lines):
            _text(
                elements,
                SVG_WIDTH // 2,
                flow_y + 25 + 23 * line_index,
                line,
                size=18,
                weight=700 if line_index == 0 else 400,
                anchor="middle",
            )
        if flow_index < 3:
            elements.append(
                f'<path d="M{SVG_WIDTH // 2},{flow_y + 84} V{flow_y + 96}" stroke="#44515f" stroke-width="3"/>'
            )
            elements.append(
                f'<path d="M{SVG_WIDTH // 2},{flow_y + 99} l-6,-9 h12 z" fill="#44515f"/>'
            )

    _text(elements, CARD_X, 946, copy["context_title"], size=20, weight=700)
    elements.append(
        f'<rect x="{CARD_X}" y="962" width="{CARD_WIDTH}" height="170" rx="10" '
        'fill="#fff7ed" stroke="#b45309" stroke-width="2"/>'
    )
    context_colors = ("#7c2d12", "#17202a", "#44515f", "#7c2d12", "#7c2d12", "#7c2d12")
    for line_index, (line, color) in enumerate(zip(copy["context"], context_colors, strict=True)):
        _text(
            elements,
            CARD_X + 16,
            990 + 24 * line_index,
            line,
            size=18,
            weight=700 if line_index in (0, 3, 4, 5) else 400,
            fill=color,
        )
    elements.append("</g></svg>")
    return "\n".join(elements) + "\n"


def render_svg(facts: dict, language: str) -> str:
    return render_svg_from_display(facts, language, build_display(facts, language))


def render_all(facts: dict) -> dict[str, str]:
    return {language: render_svg(facts, language) for language in OUTPUTS}


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(arguments)
    generated = render_all(load_facts())
    for language, content in generated.items():
        output = OUTPUTS[language]
        if args.check:
            if not output.is_file() or output.read_text(encoding="utf-8") != content:
                raise ValueError(f"Generated Cache figure differs: {output.name}")
        else:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(content, encoding="utf-8")
    print(json.dumps({"figures": len(generated), "source_sha256": REPORT_SHA256}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
