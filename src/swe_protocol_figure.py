"""Generate paired SWE-Lancer protocol-outcome diagrams from the canonical report."""

from __future__ import annotations

import argparse
from copy import deepcopy
from html import escape
import json
from pathlib import Path
import re

from .protection import digest


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs_en/experiment/02-follow-up/swe-lancer/fixed-trace-20260923.md"
REPORT_SHA256 = "1c7308daf6e8066d28e809f86c3bb5373081e4a3066713f128e4079945de0301"
OUTPUTS = {
    "ko": ROOT / "figures/follow-up/swe-protocol-outcome-ko.svg",
    "en": ROOT / "figures/follow-up/swe-protocol-outcome-en.svg",
}
SVG_WIDTH = 390
SVG_HEIGHT = 1408
OUTCOME_BOX_WIDTH = 354
OUTCOME_TEXT_INSET = 16
FACTS = {
    "candidate": "28565_1001",
    "plan": {"fixed_executions": 1},
    "observed": {
        "initial_checks": "27/29",
        "initial_failures": ("task.row", "image.config"),
        "final_checks": "31/31",
        "runner_groups": 2,
        "sandbox_startup_attempts": 2,
        "sandbox_ready": 0,
        "sandbox_startup_timeouts": 2,
        "provider_model_api_grader_calls": "0/0/0/0",
        "valid_protocol_traces": 0,
        "runner_result_rows": 2,
        "cleanup_survivors": 0,
        "runner_group_outcomes": ("computer_startup_timeout", "computer_startup_timeout"),
    },
    "network": {"configured": "disable_internet=true", "observed": "allow_internet=true"},
    "statuses": {
        "grader": "not_run",
        "runner_exit": "unknown",
        "task_quality": "not_measured",
        "invoice": "not_measured",
        "host_cost": "not_measured",
        "calculated_api_cost": "USD 0.000000",
        "error_row_meaning": "startup_error_placeholder_not_graded_failure",
    },
}
REPORT_RECORD = {
    "source_commit": "cf8960a6121e91c8ec6a796d470009a27504bf61",
    "source_tree": "70e0961bf2a3009d9a2c8e36471744be81775daa",
    "upstream_commit": "51052cede8cc608f95bb00346635e03759013e5a",
    "candidate": "28565_1001",
    "split": "diamond",
    "task_type": "ic_swe",
    "task_count": 1,
    "planned_fixed_executions": 1,
    "initial_checks": "27/29",
    "initial_failure_1": "task.row",
    "initial_failure_2": "image.config",
    "final_checks": "31/31",
    "runner_groups": 2,
    "valid_protocol_traces": 0,
    "replacement_attempts": 0,
    "sandbox_startup_attempts": 2,
    "sandbox_ready": 0,
    "sandbox_startup_timeouts": 2,
    "provider_calls": 0,
    "model_calls": 0,
    "api_calls": 0,
    "grader_calls": 0,
    "tool_calls": 0,
    "tool_results": 0,
    "provider_usage_records": 0,
    "trace_events": 3,
    "runner_result_rows": 2,
    "network_configured": "disable_internet=true",
    "network_observed": "allow_internet=true",
    "runner_group_1_outcome": "computer_startup_timeout",
    "runner_group_2_outcome": "computer_startup_timeout",
    "provider_input_tokens": 0,
    "provider_output_tokens": 0,
    "cached_input_status": "not_applicable_no_provider_call",
    "reasoning_status": "not_applicable_no_provider_call",
    "calculated_api_cost": "USD 0.000000",
    "provider_reported_cost_status": "not_measured",
    "invoice_status": "not_measured",
    "host_cost_status": "not_measured",
    "runner_exit_status": "unknown",
    "grader_status": "not_run",
    "task_quality_status": "not_measured",
    "error_row_meaning": "startup_error_placeholder_not_graded_failure",
    "cleanup_survivors": 0,
    "model_revision": "gpt-4o-2024-11-20",
    "model_revision_basis": "pinned_verified_pre_dispatch_no_inference_response",
    "evidence_window_start_utc": "2026-09-23T02:12:29Z",
    "evidence_window_end_utc": "2026-09-23T02:18:27.355804Z",
    "evidence_window_basis": "runner_group_names_and_private_log_mtimes_not_workload_latency",
    "terminal_status": "invalid_protocol_trace",
}
REPORT_SEMANTIC_PATTERNS = {
    "zero valid trace non-finding": r"valid-protocol-trace count (?:is|was) `?0`?",
    "ungraded error rows": r"`correct=False` rows?[^.]{0,180}(?:not graded failures|not (?:a )?grader outcome)",
    "causal uncertainty": (
        r"(?:evidence|record)[^.]{0,100}(?:did not|does not|could not)[^.]{0,100}"
        r"(?:isolate|identify|establish)[^.]{0,220}(?:cause|caused|produced the timeouts|mechanism)"
    ),
    "revision basis": r"gpt-4o-2024-11-20.{0,220}before dispatch.{0,220}No inference response occurred",
    "evidence-window provenance": (
        r"derived from UTC runner-group names and private run-log modification times"
        r"[^.]{0,160}not an independently timed workload duration"
    ),
    "carrier boundary": r"did not validate model or grader quality.{0,180}did not make a later trace valid",
    "network contradiction": r"configured `disable_internet=true`[^.]{0,180}(?:recorded|observed) `allow_internet=true`",
    "runner exit unknown": r"runner process exit code is unknown",
    "grader quality status": r"grader was not invoked[^.]{0,120}task pass is `not_measured`",
    "quality non-claim": r"does not support a candidate pass/fail judgment[^.]{0,500}population cost estimate",
    "usage and cost boundary": (
        r"no provider response existed.{0,160}read token usage"
        r".{0,220}input and output zeros are aggregate counters"
        r".{0,500}not a reconciled invoice"
        r".{0,180}does not establish zero host-compute cost"
    ),
}
REPORT_FORBIDDEN_PATTERNS = {
    "causal promotion": (
        r"(?:evidence|record)[^.]{0,100}(?:established|proved|showed|demonstrated)"
        r"[^.]{0,180}(?:image|network|runtime|container|sandbox)[^.]{0,120}caused"
    ),
    "graded-error promotion": r"`correct=False` rows?[^.]{0,120}(?:are|were) graded failures",
    "inference-observed revision": r"gpt-4o-2024-11-20[^.]{0,120}observed in an inference response",
    "zero-host-cost promotion": r"(?:host cost|host-compute cost)[^.]{0,80}(?:was|is) (?:USD )?0",
    "runner-exit promotion": r"runner process exit code (?:was|is) (?:`?0`?|successful)",
}


def _normalized(value: str) -> str:
    return " ".join(value.split())


def validate_report(markdown: str) -> None:
    record = parse_report_record(markdown)
    if record != REPORT_RECORD:
        raise ValueError("SWE canonical factual record changed")
    if parse_report_facts(markdown) != FACTS:
        raise ValueError("SWE accepted facts differ from the canonical report")

    visible_rows = {
        "planned_fixed_executions": "Planned fixed executions",
        "runner_groups": "Runner groups observed",
        "valid_protocol_traces": "Valid protocol traces",
        "replacement_attempts": "Replacement attempts recorded by the plan",
        "sandbox_startup_attempts": "Sandbox startup attempts",
        "sandbox_ready": "Sandbox ready",
        "provider_calls": "Provider calls",
        "model_calls": "Model calls",
        "api_calls": "API calls",
        "grader_calls": "Grader calls",
        "provider_usage_records": "Provider usage records",
        "trace_events": "Trace events",
        "runner_result_rows": "Runner result rows",
        "sandbox_startup_timeouts": "Sandbox startup timeouts",
    }
    for field, label in visible_rows.items():
        value = _integer(_single_value(markdown, label, 2), label)
        if value != record[field]:
            raise ValueError(f"SWE visible value differs from fact record: {field}")

    tool_cells = _row_cells(markdown, "Tool calls / results")
    expected_tools = f'{record["tool_calls"]} / {record["tool_results"]}'
    if len(tool_cells) != 2 or tool_cells[1] != expected_tools:
        raise ValueError("SWE visible tool counts differ from fact record")

    provider_usage_rows = {
        "provider_input_tokens": "Provider-reported input tokens",
        "provider_output_tokens": "Provider-reported output tokens",
    }
    for field, label in provider_usage_rows.items():
        if _integer(_single_value(markdown, label, 3), label) != record[field]:
            raise ValueError(f"SWE visible usage differs from fact record: {field}")

    initial = _single_value(markdown, "Initial pre-dispatch verification", 2)
    expected_initial = (
        f'{record["initial_checks"]}; failed `{record["initial_failure_1"]}`, '
        f'`{record["initial_failure_2"]}`'
    )
    if initial != expected_initial:
        raise ValueError("SWE visible initial checks differ from fact record")
    if _single_value(markdown, "Final pre-dispatch verification", 2) != record["final_checks"]:
        raise ValueError("SWE visible final checks differ from fact record")

    group_rows = re.findall(
        r"^\|\s*(?:1|2)\s*\|\s*`[^`]+` to `[^`]+`\s*\|\s*`([^`]+)`\s*\|\s*\d+\s*\|$",
        markdown,
        flags=re.MULTILINE,
    )
    expected_group_outcomes = [
        record["runner_group_1_outcome"],
        record["runner_group_2_outcome"],
    ]
    if group_rows != expected_group_outcomes:
        raise ValueError("SWE visible runner-group outcomes differ from fact record")

    source = _row_cells(markdown, "Repository source")
    expected_source = f'Commit `{record["source_commit"]}`; tree `{record["source_tree"]}`'
    if len(source) != 2 or source[1] != expected_source:
        raise ValueError("SWE visible source differs from fact record")

    network = _row_cells(markdown, "Sandbox network setting")
    if (
        len(network) != 2
        or f'`{record["network_configured"]}`' not in network[1]
        or f'`{record["network_observed"]}`' not in network[1]
    ):
        raise ValueError("SWE visible network status differs from fact record")

    status_rows = {
        "cached_input_status": "Provider-reported cached input tokens",
        "reasoning_status": "Provider-reported reasoning tokens",
        "calculated_api_cost": "Calculated API cost",
        "provider_reported_cost_status": "Provider-reported cost",
        "invoice_status": "Invoice",
        "host_cost_status": "Host-compute cost",
    }
    for field, label in status_rows.items():
        if _single_value(markdown, label, 3) != record[field]:
            raise ValueError(f"SWE visible status differs from fact record: {field}")

    narrative = markdown.split("## Factual guard record", 1)[0]
    normalized = _normalized(narrative)
    for label, pattern in REPORT_SEMANTIC_PATTERNS.items():
        if re.search(pattern, normalized, flags=re.IGNORECASE) is None:
            raise ValueError(f"SWE report semantic boundary changed: {label}")
    for label, pattern in REPORT_FORBIDDEN_PATTERNS.items():
        if re.search(pattern, normalized, flags=re.IGNORECASE) is not None:
            raise ValueError(f"SWE report forbidden claim introduced: {label}")


def _row_cells(markdown: str, label: str, columns: int | None = None) -> list[str]:
    matches = []
    for line in markdown.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and cells[0] == label and (columns is None or len(cells) == columns):
            matches.append(cells)
    if len(matches) != 1:
        raise ValueError(f"SWE report row count changed: {label}")
    return matches[0]


def _integer(value: str, label: str) -> int:
    if re.fullmatch(r"[0-9][0-9,]*", value) is None:
        raise ValueError(f"SWE report integer changed: {label}")
    return int(value.replace(",", ""))


def _single_value(markdown: str, label: str, columns: int | None = None) -> str:
    cells = _row_cells(markdown, label, columns)
    if len(cells) < 2:
        raise ValueError(f"SWE report value column changed: {label}")
    value = cells[1]
    if re.fullmatch(r"`[^`]+`", value):
        return value[1:-1]
    return value


def _record_value(markdown: str, field: str) -> str:
    cells = _row_cells(markdown, f"`{field}`", 2)
    if re.fullmatch(r"`[^`]+`", cells[1]) is None:
        raise ValueError(f"SWE report fact record changed: {field}")
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
        "candidate": record["candidate"],
        "plan": {"fixed_executions": record["planned_fixed_executions"]},
        "observed": {
            "initial_checks": record["initial_checks"],
            "initial_failures": (record["initial_failure_1"], record["initial_failure_2"]),
            "final_checks": record["final_checks"],
            "runner_groups": record["runner_groups"],
            "sandbox_startup_attempts": record["sandbox_startup_attempts"],
            "sandbox_ready": record["sandbox_ready"],
            "sandbox_startup_timeouts": record["sandbox_startup_timeouts"],
            "provider_model_api_grader_calls": "/".join(
                str(record[field])
                for field in ("provider_calls", "model_calls", "api_calls", "grader_calls")
            ),
            "valid_protocol_traces": record["valid_protocol_traces"],
            "runner_result_rows": record["runner_result_rows"],
            "cleanup_survivors": record["cleanup_survivors"],
            "runner_group_outcomes": (
                record["runner_group_1_outcome"],
                record["runner_group_2_outcome"],
            ),
        },
        "network": {
            "configured": record["network_configured"],
            "observed": record["network_observed"],
        },
        "statuses": {
            "grader": record["grader_status"],
            "runner_exit": record["runner_exit_status"],
            "task_quality": record["task_quality_status"],
            "invoice": record["invoice_status"],
            "host_cost": record["host_cost_status"],
            "calculated_api_cost": record["calculated_api_cost"],
            "error_row_meaning": record["error_row_meaning"],
        },
    }


def load_facts(path: Path = REPORT, expected_sha256: str = REPORT_SHA256) -> dict:
    report_bytes = path.read_bytes()
    markdown = report_bytes.decode("utf-8")
    validate_report(markdown)
    if digest(report_bytes) != expected_sha256:
        raise ValueError("SWE report SHA-256 changed")
    parsed = parse_report_facts(markdown)
    if parsed != FACTS:
        raise ValueError("SWE accepted facts differ from the canonical report")
    return deepcopy(parsed)


COPY = {
    "ko": {
        "title": "SWE-Lancer 실행: 유효 기록과 모델 평가 전 중단",
        "display_title": "SWE-Lancer 실행이 멈춘 지점",
        "subtitle": "계획 1회와 관측된 두 실행 결과 묶음",
        "sequence_title": "두 실행 결과 묶음의 순서",
        "outcome_title": "중단 뒤 남은 상태",
        "context_title": "이 그림이 보여 주지 못하는 것",
        "claim_boundary": ("통과율·순위 결과 없음", "후보 품질 결과 없음", "안정성 결과 없음"),
    },
    "en": {
        "title": "SWE-Lancer execution: stopped before a valid trace or model evaluation",
        "display_title": "SWE-Lancer execution stop",
        "subtitle": "One plan · two runner groups",
        "sequence_title": "The two runner groups in order",
        "outcome_title": "What remained after the stop",
        "context_title": "What the figure cannot show",
        "claim_boundary": ("No pass-rate or ranking result", "No candidate-quality result", "No stability result"),
    },
}
COPY_SHA256 = {
    "ko": "290f61530f02a10f8474a1247d9c2d3e1aa32a88c338df0d847614ae786e89ec",
    "en": "4d4a0a8bfa2fbec7ceb5955a6a4273b9758f2fc34f20ab201ca9c19482554d95",
}


def validate_copy(language: str) -> None:
    payload = json.dumps(
        COPY[language], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if digest(payload) != COPY_SHA256[language]:
        raise ValueError("SWE localized copy differs from the reviewed display contract")


def build_display(facts: dict, language: str) -> dict:
    validate_copy(language)
    copy = COPY[language]
    plan = facts["plan"]
    observed = facts["observed"]
    network = facts["network"]
    statuses = facts["statuses"]
    group_outcomes = observed["runner_group_outcomes"]
    if observed["runner_groups"] != len(group_outcomes) or len(group_outcomes) != 2:
        raise ValueError("SWE runner-group display count differs from the canonical report")
    group_numbers = tuple(range(1, observed["runner_groups"] + 1))
    outcome_labels = {
        "ko": {"computer_startup_timeout": "격리 실행 환경 시작 시간 초과"},
        "en": {"computer_startup_timeout": "sandbox startup timeout"},
    }
    if any(outcome not in outcome_labels[language] for outcome in group_outcomes):
        raise ValueError("SWE runner-group display status differs from the canonical report")
    if statuses["error_row_meaning"] != "startup_error_placeholder_not_graded_failure":
        raise ValueError("SWE error-row display meaning differs from the canonical report")
    if language == "ko":
        return {
            **copy,
            "description": (
                f'고정 실행 {plan["fixed_executions"]}회 계획과 관측된 실행 결과 묶음 '
                f'{observed["runner_groups"]}개를 순서대로 보여 준다. 두 묶음은 모두 '
                "모델·채점기 호출 전 격리 실행 환경 시작 시간 초과로 끝났다."
            ),
            "summary": (
                f'계획 · 고정 실행 {plan["fixed_executions"]}회',
                f'관측 · 실행 결과 묶음 {observed["runner_groups"]}개',
                f'유효 프로토콜 실행 기록 · {observed["valid_protocol_traces"]}개',
            ),
            "group_one_title": f"실행 결과 묶음 {group_numbers[0]}",
            "group_one_lines": (
                f'초기 검증 {observed["initial_checks"]}',
                f'실패 · {observed["initial_failures"][0]}',
                f'실패 · {observed["initial_failures"][1]}',
                outcome_labels[language][group_outcomes[0]],
            ),
            "group_two_title": f"실행 결과 묶음 {group_numbers[1]}",
            "group_two_lines": (
                f'보정 뒤 검증 {observed["final_checks"]}',
                f'{plan["fixed_executions"]}회 실행 규칙 위반',
                f'설정 · {network["configured"]}',
                f'관측 · {network["observed"]}',
                outcome_labels[language][group_outcomes[1]],
            ),
            "outcomes": (
                (
                    "격리 실행 환경",
                    (
                        f'시작 {observed["sandbox_startup_attempts"]}회 · 준비 {observed["sandbox_ready"]}회',
                        f'시작 시간 초과 {observed["sandbox_startup_timeouts"]}회',
                    ),
                ),
                (
                    "호출과 유효 기록",
                    (
                        "제공자/모델/API/채점기",
                        f'{observed["provider_model_api_grader_calls"]} (관측)',
                        f'유효 기록 {observed["valid_protocol_traces"]}개',
                    ),
                ),
                (
                    "오류 결과 행",
                    (
                        f'{observed["runner_result_rows"]}개 · 시작 오류 표시',
                        "채점 실패 아님",
                    ),
                ),
                (
                    "측정 상태",
                    (
                        f'채점기 {statuses["grader"]}',
                        f'종료 {statuses["runner_exit"]}',
                        f'품질 {statuses["task_quality"]}',
                    ),
                ),
            ),
            "group_outcomes": group_outcomes,
            "context": (
                f'유효 기록 {observed["valid_protocol_traces"]}개 · 채점기 {statuses["grader"]}',
                *copy["claim_boundary"],
                "오류 행과 호출 0만으로",
                "모델 품질 판단 불가",
            ),
        }
    return {
        **copy,
        "description": (
            f'{plan["fixed_executions"]} planned fixed execution and {observed["runner_groups"]} observed runner groups '
            "are shown in order. Both groups ended in sandbox startup timeout before model or grader dispatch."
        ),
        "summary": (
            f'PLAN · {plan["fixed_executions"]} fixed execution',
            f'OBSERVED · {observed["runner_groups"]} runner groups',
            f'VALID PROTOCOL TRACES · {observed["valid_protocol_traces"]}',
        ),
        "group_one_title": f"Runner group {group_numbers[0]}",
        "group_one_lines": (
            f'Initial gate {observed["initial_checks"]}',
            f'failed · {observed["initial_failures"][0]}',
            f'failed · {observed["initial_failures"][1]}',
            outcome_labels[language][group_outcomes[0]],
        ),
        "group_two_title": f"Runner group {group_numbers[1]}",
        "group_two_lines": (
            f'Corrected gate {observed["final_checks"]}',
            f'{plan["fixed_executions"]}-execution rule breached',
            f'configured · {network["configured"]}',
            f'observed · {network["observed"]}',
            outcome_labels[language][group_outcomes[1]],
        ),
        "outcomes": (
            (
                "Sandbox",
                (
                    f'{observed["sandbox_startup_attempts"]} starts · {observed["sandbox_ready"]} ready',
                    f'{observed["sandbox_startup_timeouts"]} startup timeouts',
                ),
            ),
            (
                "Calls and valid traces",
                (
                    "provider/model/API/grader",
                    f'{observed["provider_model_api_grader_calls"]} observed',
                    f'{observed["valid_protocol_traces"]} valid traces',
                ),
            ),
            (
                "Error result rows",
                (
                    f'{observed["runner_result_rows"]} · startup placeholders',
                    "not graded failures",
                ),
            ),
            (
                "Measurement states",
                (
                    f'grader {statuses["grader"]}',
                    f'exit {statuses["runner_exit"]}',
                    f'quality {statuses["task_quality"]}',
                ),
            ),
        ),
        "group_outcomes": group_outcomes,
        "context": (
            f'{observed["valid_protocol_traces"]} valid traces · grader {statuses["grader"]}',
            *copy["claim_boundary"],
            "Error rows and zero calls",
            "do not measure model quality",
        ),
    }


def validate_display(facts: dict, language: str, display: dict) -> None:
    if display != build_display(facts, language):
        raise ValueError("SWE displayed facts differ from the validated fact model")
    if any(outcome != "computer_startup_timeout" for outcome in display["group_outcomes"]):
        raise ValueError("SWE displayed group outcome differs from the canonical report")


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
        raise ValueError("SWE figure facts differ from the accepted specification")
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
    _text(elements, 18, 38, copy["display_title"], size=23, weight=700)
    _text(elements, 18, 68, copy["subtitle"], size=18, fill="#44515f")

    elements.append(
        '<rect x="18" y="92" width="354" height="112" rx="12" fill="#f7f9fb" '
        'stroke="#52708f" stroke-width="2"/>'
    )
    summary_colors = ("#2457a6", "#7c3aed", "#b45309")
    for line_index, (label, color) in enumerate(zip(copy["summary"], summary_colors, strict=True)):
        _text(elements, 34, 124 + 32 * line_index, label, size=18, weight=700, fill=color)

    _text(elements, 18, 246, copy["sequence_title"], size=20, weight=700)
    group_specs = (
        (264, 158, copy["group_one_title"], copy["group_one_lines"], "#b45309"),
        (448, 198, copy["group_two_title"], copy["group_two_lines"], "#b42318"),
    )
    for group_y, group_height, title, lines, color in group_specs:
        elements.append(
            f'<rect x="18" y="{group_y}" width="354" height="{group_height}" rx="12" fill="#fffaf5" '
            f'stroke="{color}" stroke-width="2" stroke-dasharray="8 5"/>'
        )
        _text(elements, 34, group_y + 30, title, size=20, weight=700, fill=color)
        for line_index, line in enumerate(lines):
            _text(elements, 34, group_y + 61 + 25 * line_index, line, size=18, weight=700 if line_index == 0 else 400)
    elements.append('<path d="M195,424 V441" stroke="#44515f" stroke-width="3"/>')
    elements.append('<path d="M195,445 l-7,-10 h14 z" fill="#44515f"/>')

    _text(elements, 18, 690, copy["outcome_title"], size=20, weight=700)
    outcome_positions = (708, 824, 940, 1056)
    for outcome_y, (label, lines) in zip(outcome_positions, copy["outcomes"], strict=True):
        elements.append(
            f'<rect x="18" y="{outcome_y}" width="{OUTCOME_BOX_WIDTH}" height="108" rx="10" '
            'fill="#f7f9fb" stroke="#7a8794" stroke-width="2"/>'
        )
        _text(elements, 18 + OUTCOME_TEXT_INSET, outcome_y + 27, label, size=19, weight=700)
        for line_index, line in enumerate(lines):
            _text(
                elements,
                18 + OUTCOME_TEXT_INSET,
                outcome_y + 55 + 23 * line_index,
                line,
                size=18,
                weight=700 if line_index == 0 else 400,
                fill="#2457a6" if line_index == 0 else "#44515f",
            )

    _text(elements, 18, 1195, copy["context_title"], size=20, weight=700)
    elements.append(
        '<rect x="18" y="1212" width="354" height="175" rx="10" fill="#fff7ed" '
        'stroke="#b45309" stroke-width="2"/>'
    )
    for line_index, line in enumerate(copy["context"]):
        _text(
            elements,
            34,
            1241 + 25 * line_index,
            line,
            size=18,
            weight=700,
            fill="#7c2d12",
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
                raise ValueError(f"Generated SWE figure differs: {output.name}")
        else:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(content, encoding="utf-8")
    print(json.dumps({"figures": len(generated), "source_sha256": REPORT_SHA256}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
