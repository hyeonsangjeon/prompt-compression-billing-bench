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
REPORT_SHA256 = "9c07682a067aea18d253c869f5fe0711dc3c695de5b1636b7bfe7d95b0f907f3"
OUTPUTS = {
    "ko": ROOT / "figures/follow-up/cache-execution-denominators-ko.svg",
    "en": ROOT / "figures/follow-up/cache-execution-denominators-en.svg",
}
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
REPORT_CLAUSES = (
    (
        "source",
        "| Source | Commit `e78a32edca9d5ce4f991700e3a299d72164e94be`; tree `63f969519c93a58faf800ed91cc464f9b955fe2b` |",
    ),
    ("plan units", "10 valid cycles; 60 useful bundles; 300 task trials"),
    ("task strata", "two eligible and three `not_applicable` for the primary cache denominator"),
    ("terminal status", "The terminal status was `stopped_invalid_cycle`."),
    ("cycle counts", "| Cycles | 10 initially | 1 | 0 | 1 | 0 |"),
    ("bundle counts", "| Bundles | 60 initially | 2 | 1 | 1 | 0 |"),
    ("task-trial counts", "| Task trials | 300 initially | 6 | 5 | 1 | 0 |"),
    ("provider calls", "| Successful provider calls | 18 |"),
    (
        "cached-input boundary",
        "| Cached input | 0 | API-reported, partial invalid cycle; not a Cache-effect estimate or miss rate |",
    ),
    (
        "quality boundary",
        "Five completed task trials produced native quality outcomes, and 3 of 5 passed. The sixth started task trial was incomplete.",
    ),
    (
        "ordinal stop",
        "`cancel-async-tasks` reached logical request ordinal `3`, while its reuse `0` predecessor had only `2` requests.",
    ),
    (
        "missing predecessor",
        "Prefix validation therefore had no same-task predecessor at ordinal `3` and rejected the request before provider dispatch.",
    ),
    (
        "invalid treatment",
        "The cycle was preserved as invalid. No outer retry or replacement was performed.",
    ),
    (
        "non-claim boundary",
        "With zero valid cycles, the run cannot support a cache comparison, a Cache-effect estimate, a reuse contrast, or the predeclared stability comparison.",
    ),
)


def _normalized(value: str) -> str:
    return " ".join(value.split())


def validate_report(markdown: str) -> None:
    normalized = _normalized(markdown)
    for label, clause in REPORT_CLAUSES:
        if _normalized(clause) not in normalized:
            raise ValueError(f"Cache report changed: {label}")


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


def parse_report_facts(markdown: str) -> dict:
    number_words = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
    strata = re.search(
        r"Task population\s*\|\s*Five fixed tasks in every cell; "
        r"(\w+) eligible and (\w+) `not_applicable` for the primary cache denominator\s*\|",
        markdown,
    )
    if strata is None or strata.group(1) not in number_words or strata.group(2) not in number_words:
        raise ValueError("Cache report task strata changed")

    cycle_cells = _row_cells(markdown, "Cycles")
    bundle_cells = _row_cells(markdown, "Bundles")
    trial_cells = _row_cells(markdown, "Task trials")
    if any(len(cells) != 6 for cells in (cycle_cells, bundle_cells, trial_cells)):
        raise ValueError("Cache report denominator columns changed")

    stop = re.search(
        r"During `(?P<condition>[^`]+)`, reuse\s*`(?P<reuse>\d+)`, "
        r"`(?P<task>[^`]+)` reached logical request ordinal `(?P<ordinal>\d+)`, "
        r"while its reuse\s*`(?P<predecessor_reuse>\d+)` predecessor had only "
        r"`(?P<predecessor_requests>\d+)` requests\.",
        markdown,
    )
    if stop is None:
        raise ValueError("Cache report ordinal stop changed")
    if (
        "rejected the request before provider dispatch" not in _normalized(markdown)
        or "No outer retry or replacement was performed" not in _normalized(markdown)
    ):
        raise ValueError("Cache report stop treatment changed")

    terminal = re.search(r"The terminal status was `([^`]+)`\.", markdown)
    quality = re.search(
        r"(\d+) of (\d+) passed\.\s+The sixth started task trial was incomplete\.",
        markdown,
    )
    if terminal is None or quality is None:
        raise ValueError("Cache report terminal or quality status changed")

    provider_calls = _row_cells(markdown, "Successful provider calls")
    cached_input = _row_cells(markdown, "Cached input")
    if len(provider_calls) != 2 or len(cached_input) != 3:
        raise ValueError("Cache report descriptive columns changed")

    return {
        "plan": {
            "cycles": _initial_count(cycle_cells[1], "cycles"),
            "bundles": _initial_count(bundle_cells[1], "bundles"),
            "task_trials": _initial_count(trial_cells[1], "task trials"),
        },
        "observed": {
            "cycles_attempted": _integer(cycle_cells[2], "cycles attempted"),
            "cycles_valid": _integer(cycle_cells[3], "cycles valid"),
            "cycles_invalid": _integer(cycle_cells[4], "cycles invalid"),
            "replacement": _integer(cycle_cells[5], "cycle replacement"),
            "bundles_started": _integer(bundle_cells[2], "bundles started"),
            "bundles_complete": _integer(bundle_cells[3], "bundles complete"),
            "bundles_incomplete": _integer(bundle_cells[4], "bundles incomplete"),
            "task_trials_started": _integer(trial_cells[2], "task trials started"),
            "task_trials_complete": _integer(trial_cells[3], "task trials complete"),
            "task_trials_incomplete": _integer(trial_cells[4], "task trials incomplete"),
        },
        "stop": {
            "condition": stop.group("condition"),
            "reuse": int(stop.group("reuse")),
            "predecessor_reuse": int(stop.group("predecessor_reuse")),
            "task": stop.group("task"),
            "ordinal": int(stop.group("ordinal")),
            "predecessor_requests": int(stop.group("predecessor_requests")),
            "dispatch": "rejected_before_dispatch",
        },
        "descriptive": {
            "successful_provider_calls": _integer(provider_calls[1], "successful provider calls"),
            "completed_trial_quality": f"{quality.group(1)}/{quality.group(2)}",
            "eligible_tasks": number_words[strata.group(1)],
            "not_applicable_tasks": number_words[strata.group(2)],
            "cached_input_tokens": _integer(cached_input[1], "cached input"),
        },
        "terminal_status": terminal.group(1),
    }


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
        "title": "Cache 실행 분모와 무효 중단",
        "description_start": "사이클, 실행 묶음, 과제 실행의 계획과 관측을 서로 다른 단위로 표시하고,",
        "subtitle": "첫 불완전 무효 사이클 · 단위별 계획과 관측",
        "section_denominators": "1. 단위별 분모",
        "section_context": "3. 무효 부분 실행의 설명값",
        "claim_boundary": "Cache 효과, 절감, 순위, 재사용 대비, 안정성은 계산하지 않음",
    },
    "en": {
        "title": "Cache execution denominators and invalid stop",
        "description_start": "Cycles, bundles, and task trials keep separate plan and observation units.",
        "subtitle": "First incomplete invalid cycle · plan and observation by unit",
        "section_denominators": "1. Denominators by unit",
        "section_context": "3. Descriptive values from the invalid partial run",
        "claim_boundary": "no Cache effect, savings, ranking, reuse contrast, or stability result",
    },
}
COPY_SHA256 = {
    "ko": "754faa03259959fbe90f9bb8e9fc63f5b398c4dceb2deac4a305385baaa2a2e6",
    "en": "93bfb5edb19b929dbd2f7e126dcfb98d20a8a962b53ab895f01f03e4b547dae8",
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
    if language == "ko":
        return {
            **copy,
            "description": (
                f'{copy["description_start"]} 선행 요청이 없었던 논리 요청 순번 '
                f'{stop["ordinal"]}의 제공자 전송 전 중단을 보인다.'
            ),
            "cards": (
                ("사이클", f'계획 · 유효 {plan["cycles"]}개', (
                    f'관측 · {observed["cycles_attempted"]}개 시도',
                    f'{observed["cycles_valid"]}개 유효 (관측)',
                    f'{observed["cycles_invalid"]}개 무효 · 대체 {observed["replacement"]}개',
                )),
                ("실행 묶음", f'계획 · {plan["bundles"]}개', (
                    f'관측 · {observed["bundles_started"]}개 시작',
                    f'{observed["bundles_complete"]}개 완결',
                    f'{observed["bundles_incomplete"]}개 미완결·무효',
                )),
                ("과제 실행", f'계획 · {plan["task_trials"]}개', (
                    f'관측 · {observed["task_trials_started"]}개 시작',
                    f'{observed["task_trials_complete"]}개 완결',
                    f'{observed["task_trials_incomplete"]}개 미완결',
                )),
            ),
            "section_stop": f'2. 논리 요청 순번 {stop["ordinal"]}에서 중단',
            "flow": (
                (
                    f'{stop["condition"]} · 재사용 {stop["predecessor_reuse"]}',
                    "실행 묶음 완결",
                    f'선행 요청 {stop["predecessor_requests"]}개',
                ),
                (
                    f'{stop["condition"]} · 재사용 {stop["reuse"]}',
                    stop["task"],
                    f'현재 순번 {stop["ordinal"]} 도달',
                ),
                (
                    "비교할 선행 요청 없음",
                    f'재사용 {stop["predecessor_reuse"]}에는',
                    f'순번 {stop["ordinal"]} 요청이 없음',
                ),
                ("제공자 전송 전 거부", "접두부 비교·길이", "측정하지 않음"),
            ),
            "context": (
                ("성공한 제공자 호출", (f'{descriptive["successful_provider_calls"]}회',), "조건·재사용 비교 아님"),
                ("완결 과제 실행 품질", (f'{descriptive["completed_trial_quality"]} 통과',), "조건별 품질 비교 아님"),
                (
                    "과제 층",
                    (
                        f'대상 {descriptive["eligible_tasks"]}',
                        f'not_applicable {descriptive["not_applicable_tasks"]}',
                    ),
                    "서로 다른 상태",
                ),
            ),
            "cached_note": (
                f'cached input {descriptive["cached_input_tokens"]} tokens · '
                "API 사용량이며 미스율 또는 Cache 효과 추정값이 아님"
            ),
            "claim_boundary": f'유효 사이클 {observed["cycles_valid"]}개 · {copy["claim_boundary"]}',
        }
    return {
        **copy,
        "description": (
            f'{copy["description_start"]} The flow shows the pre-dispatch stop at ordinal '
            f'{stop["ordinal"]} when no predecessor request existed.'
        ),
        "cards": (
            ("Cycles", f'PLAN · {plan["cycles"]} valid', (
                f'OBSERVED · {observed["cycles_attempted"]} attempted',
                f'{observed["cycles_valid"]} valid (observed)',
                f'{observed["cycles_invalid"]} invalid · {observed["replacement"]} replacement',
            )),
            ("Bundles", f'PLAN · {plan["bundles"]}', (
                f'OBSERVED · {observed["bundles_started"]} started',
                f'{observed["bundles_complete"]} complete',
                f'{observed["bundles_incomplete"]} incomplete / invalid',
            )),
            ("Task trials", f'PLAN · {plan["task_trials"]}', (
                f'OBSERVED · {observed["task_trials_started"]} started',
                f'{observed["task_trials_complete"]} complete',
                f'{observed["task_trials_incomplete"]} incomplete',
            )),
        ),
        "section_stop": f'2. Stop at logical request ordinal {stop["ordinal"]}',
        "flow": (
            (
                f'{stop["condition"]} · reuse {stop["predecessor_reuse"]}',
                "bundle complete",
                f'{stop["predecessor_requests"]} predecessor requests',
            ),
            (
                f'{stop["condition"]} · reuse {stop["reuse"]}',
                stop["task"],
                f'current ordinal {stop["ordinal"]} reached',
            ),
            (
                "No request to pair",
                f'reuse {stop["predecessor_reuse"]} had no',
                f'request at ordinal {stop["ordinal"]}',
            ),
            ("Rejected pre-dispatch", "no prefix comparison", "or length measurement"),
        ),
        "context": (
            ("Successful provider calls", (str(descriptive["successful_provider_calls"]),), "not a condition contrast"),
            ("Completed-trial quality", (f'{descriptive["completed_trial_quality"]} passed',), "not condition quality"),
            (
                "Task strata",
                (
                    f'{descriptive["eligible_tasks"]} eligible',
                    f'{descriptive["not_applicable_tasks"]} not_applicable',
                ),
                "distinct statuses",
            ),
        ),
        "cached_note": (
            f'cached input {descriptive["cached_input_tokens"]} tokens · '
            "API usage, not a miss rate or Cache-effect estimate"
        ),
        "claim_boundary": f'{observed["cycles_valid"]} valid cycles · {copy["claim_boundary"]}',
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
        '<svg xmlns="http://www.w3.org/2000/svg" width="1040" height="900" viewBox="0 0 1040 900" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(copy["title"])}</title>',
        f'<desc id="desc">{escape(copy["description"])}</desc>',
        f'<metadata>source-report-sha256:{REPORT_SHA256}</metadata>',
        '<rect width="1040" height="900" fill="#ffffff"/>',
        '<g font-family="sans-serif" font-variant-numeric="tabular-nums">',
    ]
    _text(elements, 30, 42, copy["title"], size=27, weight=700)
    _text(elements, 30, 72, copy["subtitle"], size=17, fill="#44515f")
    _text(elements, 30, 112, copy["section_denominators"], size=20, weight=700)

    card_positions = (30, 370, 710)
    for card_x, (name, plan, observations) in zip(card_positions, copy["cards"], strict=True):
        elements.append(
            f'<rect x="{card_x}" y="130" width="300" height="205" rx="12" fill="#f7f9fb" stroke="#7a8794" stroke-width="2"/>'
        )
        _text(elements, card_x + 18, 162, name, size=21, weight=700)
        _text(elements, card_x + 18, 194, plan, size=17, weight=700, fill="#2457a6")
        for line_index, line in enumerate(observations):
            _text(elements, card_x + 18, 230 + 30 * line_index, line, size=16)

    _text(elements, 30, 385, copy["section_stop"], size=20, weight=700)
    flow_positions = (30, 280, 530, 780)
    for flow_index, (flow_x, lines) in enumerate(zip(flow_positions, copy["flow"], strict=True)):
        border = "#b45309" if flow_index >= 2 else "#52708f"
        dash = ' stroke-dasharray="7 5"' if flow_index >= 2 else ""
        elements.append(
            f'<rect x="{flow_x}" y="405" width="225" height="145" rx="10" fill="#ffffff" '
            f'stroke="{border}" stroke-width="2"{dash}/>'
        )
        for line_index, line in enumerate(lines):
            _text(
                elements,
                flow_x + 112,
                442 + 34 * line_index,
                line,
                size=16,
                weight=700 if line_index == 0 else 400,
                anchor="middle",
            )
        if flow_index < 3:
            elements.append(
                f'<path d="M{flow_x + 229},478 H{flow_x + 245}" stroke="#44515f" stroke-width="3"/>'
            )
            elements.append(
                f'<path d="M{flow_x + 245},478 l-8,-6 v12 z" fill="#44515f"/>'
            )

    _text(elements, 30, 605, copy["section_context"], size=20, weight=700)
    for card_x, (label, values, qualifier) in zip(card_positions, copy["context"], strict=True):
        elements.append(
            f'<rect x="{card_x}" y="625" width="300" height="120" rx="10" fill="#f7f9fb" stroke="#7a8794" stroke-width="2"/>'
        )
        _text(elements, card_x + 18, 657, label, size=16, weight=700)
        value_y = 684 if len(values) == 2 else 691
        for line_index, value in enumerate(values):
            _text(elements, card_x + 18, value_y + 25 * line_index, value, size=20, weight=700, fill="#2457a6")
        _text(elements, card_x + 18, 735 if len(values) == 2 else 722, qualifier, size=16, fill="#44515f")

    elements.append(
        '<rect x="30" y="775" width="980" height="95" rx="10" fill="#fff7ed" stroke="#b45309" stroke-width="2"/>'
    )
    _text(elements, 50, 811, copy["cached_note"], size=16, weight=700, fill="#7c2d12")
    _text(elements, 50, 847, copy["claim_boundary"], size=16, weight=700, fill="#7c2d12")
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
