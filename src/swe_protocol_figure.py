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
REPORT_SHA256 = "fbb6c7feae38c5fefc6251c5445116099af945284f6b5825a56e4a3213ba4ea4"
OUTPUTS = {
    "ko": ROOT / "figures/follow-up/swe-protocol-outcome-ko.svg",
    "en": ROOT / "figures/follow-up/swe-protocol-outcome-en.svg",
}
OUTCOME_BOX_WIDTH = 300
OUTCOME_TEXT_INSET = 18
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
    },
}
REPORT_CLAUSES = (
    (
        "source",
        "| Repository source | Commit `cf8960a6121e91c8ec6a796d470009a27504bf61`; tree `70e0961bf2a3009d9a2c8e36471744be81775daa` |",
    ),
    ("one-execution plan", "| Planned fixed executions | 1 |"),
    ("initial checks", "| Initial pre-dispatch verification | 27/29; failed `task.row`, `image.config` |"),
    ("final checks", "| Final pre-dispatch verification | 31/31 |"),
    ("runner groups", "| Runner groups observed | 2 |"),
    ("valid traces", "| Valid protocol traces | 0 |"),
    ("sandbox starts", "| Sandbox startup attempts | 2 |"),
    ("sandbox ready", "| Sandbox ready | 0 |"),
    ("timeouts", "| Sandbox startup timeouts | 2 |"),
    (
        "network contradiction",
        "The command configured `disable_internet=true`; the guarded start observed `allow_internet=true`, so the isolation predicate did not hold",
    ),
    ("provider calls", "| Provider calls | 0 |"),
    ("model calls", "| Model calls | 0 |"),
    ("API calls", "| API calls | 0 |"),
    ("grader calls", "| Grader calls | 0 |"),
    ("runner exit", "the runner process exit code is unknown"),
    (
        "usage status",
        "| Provider-reported cached input tokens | `not_applicable_no_provider_call` | No provider response existed |",
    ),
    ("calculated cost", "| Calculated API cost | `USD 0.000000` | Zero dispatched provider requests and zero provider usage; not an invoice |"),
    ("invoice", "| Invoice | `not_measured` | No billing reconciliation was performed |"),
    ("host cost", "| Host-compute cost | `not_measured` | No independent host-cost observation was sealed |"),
    (
        "ungraded rows",
        "Those rows are error placeholders and must not be quoted as two graded failures or as a quality denominator.",
    ),
    (
        "quality status",
        "The benchmark grader was not invoked, so task pass is `not_measured`.",
    ),
    (
        "cleanup",
        "Post-result verification found `0` container, process, workspace, Docker-network, and network-rule survivors.",
    ),
    (
        "non-claim boundary",
        "It does not support a candidate pass/fail judgment, provider reliability claim, model-quality claim, token or cost distribution, causal explanation, stability estimate, pass rate, ranking, non-inferiority conclusion, representative performance claim, or population cost estimate.",
    ),
)


def _normalized(value: str) -> str:
    return " ".join(value.split())


def validate_report(markdown: str) -> None:
    normalized = _normalized(markdown)
    for label, clause in REPORT_CLAUSES:
        if _normalized(clause) not in normalized:
            raise ValueError(f"SWE report changed: {label}")


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


def parse_report_facts(markdown: str) -> dict:
    candidate_cells = _row_cells(markdown, "Candidate")
    candidate = re.fullmatch(r"`([^`]+)`; split `diamond`; type `ic_swe`; task count `1`", candidate_cells[1])
    initial = re.fullmatch(
        r"(\d+/\d+); failed `([^`]+)`, `([^`]+)`",
        _single_value(markdown, "Initial pre-dispatch verification"),
    )
    network = re.search(
        r"The command configured `([^`]+)`; the guarded start observed `([^`]+)`, "
        r"so the isolation predicate did not hold",
        markdown,
    )
    group_rows = re.findall(
        r"^\|\s*(?:1|2)\s*\|\s*`[^`]+` to `[^`]+`\s*\|\s*`([^`]+)`\s*\|\s*\d+\s*\|$",
        markdown,
        flags=re.MULTILINE,
    )
    calculated_cost = _single_value(markdown, "Calculated API cost", 3)
    cleanup = re.search(
        r"Post-result verification found `([0-9]+)` container, process, workspace, Docker-network,\s+"
        r"and network-rule survivors\.",
        markdown,
    )
    if candidate is None or initial is None or network is None or len(group_rows) != 2 or cleanup is None:
        raise ValueError("SWE report structured fact changed")
    normalized = _normalized(markdown)
    if "the runner process exit code is unknown" not in normalized:
        raise ValueError("SWE report runner exit changed")
    if "The benchmark grader was not invoked, so task pass is `not_measured`." not in normalized:
        raise ValueError("SWE report grader or quality status changed")

    calls = [
        _integer(_single_value(markdown, label), label)
        for label in ("Provider calls", "Model calls", "API calls", "Grader calls")
    ]
    return {
        "candidate": candidate.group(1),
        "plan": {"fixed_executions": _integer(_single_value(markdown, "Planned fixed executions"), "planned executions")},
        "observed": {
            "initial_checks": initial.group(1),
            "initial_failures": (initial.group(2), initial.group(3)),
            "final_checks": _single_value(markdown, "Final pre-dispatch verification"),
            "runner_groups": _integer(_single_value(markdown, "Runner groups observed"), "runner groups"),
            "sandbox_startup_attempts": _integer(
                _single_value(markdown, "Sandbox startup attempts"), "sandbox startup attempts"
            ),
            "sandbox_ready": _integer(_single_value(markdown, "Sandbox ready"), "sandbox ready"),
            "sandbox_startup_timeouts": _integer(
                _single_value(markdown, "Sandbox startup timeouts"), "sandbox startup timeouts"
            ),
            "provider_model_api_grader_calls": "/".join(str(value) for value in calls),
            "valid_protocol_traces": _integer(
                _single_value(markdown, "Valid protocol traces"), "valid protocol traces"
            ),
            "runner_result_rows": _integer(_single_value(markdown, "Runner result rows"), "runner result rows"),
            "cleanup_survivors": int(cleanup.group(1)),
            "runner_group_outcomes": tuple(group_rows),
        },
        "network": {"configured": network.group(1), "observed": network.group(2)},
        "statuses": {
            "grader": "not_run",
            "runner_exit": "unknown",
            "task_quality": "not_measured",
            "invoice": _single_value(markdown, "Invoice", 3),
            "host_cost": _single_value(markdown, "Host-compute cost", 3),
            "calculated_api_cost": calculated_cost,
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
        "title": "SWE-Lancer 프로토콜 무효 실행과 정리",
        "description_end": "검증 실패, 네트워크 설정 모순, 시작 시간 초과와 측정되지 않은 상태를 분리한다.",
        "outcome_title": "관측 단위와 상태",
        "claim_boundary": "통과율, 순위, 후보 품질, 안정성, 대표 비용을 판단하지 않음",
    },
    "en": {
        "title": "SWE-Lancer protocol-invalid execution and cleanup",
        "description_end": (
            "Gate failures, the network-setting contradiction, startup timeouts, and unmeasured states remain separate."
        ),
        "outcome_title": "Observed units and statuses",
        "claim_boundary": "No pass rate, ranking, candidate-quality, stability, or population-cost conclusion",
    },
}
COPY_SHA256 = {
    "ko": "33ca1793120932a1a643535d7db3c10be8547100dfaa4c1436727c09e4543133",
    "en": "c03a9396f2fe31b8da6fde6ef7984b5524b91e617c1d4fe68c32b02d8bbe5572",
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
    if language == "ko":
        return {
            **copy,
            "description": (
                f'계획한 고정 실행 {plan["fixed_executions"]}회와 관측된 실행 결과 묶음 '
                f'{observed["runner_groups"]}개를 순서대로 보이고, {copy["description_end"]}'
            ),
            "subtitle": (
                f'고정 후보 {facts["candidate"]} · 유효 프로토콜 실행 기록 '
                f'{observed["valid_protocol_traces"]}개'
            ),
            "plan": f'계획 · 고정 실행 {plan["fixed_executions"]}회',
            "observed": f'관측 · 실행 결과 묶음 {observed["runner_groups"]}개',
            "valid": f'유효 기록 · {observed["valid_protocol_traces"]}개 (관측)',
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
                    f'시작 {observed["sandbox_startup_attempts"]} · 준비 {observed["sandbox_ready"]}',
                    (f'시간 초과 {observed["sandbox_startup_timeouts"]}',),
                ),
                ("호출", "제공자/모델/API/채점기", (f'{observed["provider_model_api_grader_calls"]} (관측)',)),
                (
                    "오류 결과 행",
                    f'{observed["runner_result_rows"]}개 · 시작 오류 표시',
                    ("채점 실패 아님",),
                ),
                (
                    "상태",
                    f'채점기 {statuses["grader"]}',
                    (
                        f'종료 {statuses["runner_exit"]}',
                        f'품질 {statuses["task_quality"]}',
                    ),
                ),
                (
                    "비용",
                    f'API 계산 {statuses["calculated_api_cost"]}',
                    (
                        f'청구서 {statuses["invoice"]}',
                        f'호스트 {statuses["host_cost"]}',
                    ),
                ),
                (
                    "정리",
                    f'남은 항목 {observed["cleanup_survivors"]}',
                    ("컨테이너·프로세스·작업공간·규칙",),
                ),
            ),
            "group_outcomes": group_outcomes,
        }
    return {
        **copy,
        "description": (
            f'{plan["fixed_executions"]} planned fixed execution and {observed["runner_groups"]} observed runner groups '
            f'are shown in order. {copy["description_end"]}'
        ),
        "subtitle": (
            f'Fixed candidate {facts["candidate"]} · {observed["valid_protocol_traces"]} valid protocol traces'
        ),
        "plan": f'PLAN · {plan["fixed_executions"]} fixed execution',
        "observed": f'OBSERVED · {observed["runner_groups"]} runner groups',
        "valid": f'VALID TRACES · {observed["valid_protocol_traces"]} observed',
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
                f'{observed["sandbox_startup_attempts"]} starts · {observed["sandbox_ready"]} ready',
                (f'{observed["sandbox_startup_timeouts"]} startup timeouts',),
            ),
            ("Calls", "provider/model/API/grader", (f'{observed["provider_model_api_grader_calls"]} observed',)),
            (
                "Error result rows",
                f'{observed["runner_result_rows"]} · startup placeholders',
                ("not graded failures",),
            ),
            (
                "Statuses",
                f'grader {statuses["grader"]}',
                (
                    f'exit {statuses["runner_exit"]}',
                    f'quality {statuses["task_quality"]}',
                ),
            ),
            (
                "Costs",
                f'API calc {statuses["calculated_api_cost"]}',
                (
                    f'invoice {statuses["invoice"]}',
                    f'host {statuses["host_cost"]}',
                ),
            ),
            (
                "Cleanup",
                f'{observed["cleanup_survivors"]} survivors',
                ("container/process/workspace/rule",),
            ),
        ),
        "group_outcomes": group_outcomes,
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
        '<svg xmlns="http://www.w3.org/2000/svg" width="1040" height="970" viewBox="0 0 1040 970" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(copy["title"])}</title>',
        f'<desc id="desc">{escape(copy["description"])}</desc>',
        f'<metadata>source-report-sha256:{REPORT_SHA256}</metadata>',
        '<rect width="1040" height="970" fill="#ffffff"/>',
        '<g font-family="sans-serif" font-variant-numeric="tabular-nums">',
    ]
    _text(elements, 30, 42, copy["title"], size=27, weight=700)
    _text(elements, 30, 72, copy["subtitle"], size=17, fill="#44515f")

    summary = ((30, copy["plan"], "#2457a6"), (370, copy["observed"], "#7c3aed"), (710, copy["valid"], "#b45309"))
    for summary_x, label, color in summary:
        elements.append(
            f'<rect x="{summary_x}" y="100" width="300" height="62" rx="10" fill="#f7f9fb" stroke="{color}" stroke-width="2"/>'
        )
        _text(elements, summary_x + 150, 139, label, size=17, weight=700, fill=color, anchor="middle")

    group_specs = (
        (30, copy["group_one_title"], copy["group_one_lines"], "#b45309"),
        (550, copy["group_two_title"], copy["group_two_lines"], "#b42318"),
    )
    for group_x, title, lines, color in group_specs:
        elements.append(
            f'<rect x="{group_x}" y="200" width="460" height="280" rx="12" fill="#fffaf5" '
            f'stroke="{color}" stroke-width="2" stroke-dasharray="8 5"/>'
        )
        _text(elements, group_x + 22, 238, title, size=21, weight=700, fill=color)
        for line_index, line in enumerate(lines):
            _text(elements, group_x + 22, 278 + 39 * line_index, line, size=17, weight=700 if line_index == 0 else 400)
    elements.append('<path d="M500,340 H535" stroke="#44515f" stroke-width="3"/>')
    elements.append('<path d="M545,340 l-10,-7 v14 z" fill="#44515f"/>')

    _text(elements, 30, 530, copy["outcome_title"], size=20, weight=700)
    outcome_positions = ((30, 555), (370, 555), (710, 555), (30, 700), (370, 700), (710, 700))
    for (outcome_x, outcome_y), (label, value, qualifiers) in zip(outcome_positions, copy["outcomes"], strict=True):
        elements.append(
            f'<rect x="{outcome_x}" y="{outcome_y}" width="{OUTCOME_BOX_WIDTH}" height="120" rx="10" fill="#f7f9fb" stroke="#7a8794" stroke-width="2"/>'
        )
        _text(elements, outcome_x + OUTCOME_TEXT_INSET, outcome_y + 31, label, size=17, weight=700)
        _text(elements, outcome_x + OUTCOME_TEXT_INSET, outcome_y + 66, value, size=16, weight=700, fill="#2457a6")
        qualifier_y = outcome_y + (88 if len(qualifiers) == 2 else 98)
        for line_index, qualifier in enumerate(qualifiers):
            _text(
                elements,
                outcome_x + OUTCOME_TEXT_INSET,
                qualifier_y + 23 * line_index,
                qualifier,
                size=16,
                fill="#44515f",
            )

    elements.append(
        '<rect x="30" y="855" width="980" height="82" rx="10" fill="#fff7ed" stroke="#b45309" stroke-width="2"/>'
    )
    _text(elements, 50, 905, copy["claim_boundary"], size=17, weight=700, fill="#7c2d12")
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
