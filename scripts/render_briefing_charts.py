#!/usr/bin/env python3
"""Render the Korean customer-briefing figures from checked-in aggregate evidence.

Requires Python 3.10+, matplotlib 3.10.8 and a Korean font. Dependencies can live
in an external environment; this script does not change project dependencies.
Run from any directory: python scripts/render_briefing_charts.py
Optional: --font /path/to/KoreanFont.ttf
Outputs: figures/briefing-ko/{01..08}-*.{png,svg} and chart-data.json.
SVG text is embedded as outlines, so viewers need no Korean font installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager, ticker


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "figures" / "briefing-ko"
PRELIM = ROOT / "data" / "experiment" / "preliminary-comparison-summary.json"
ACCOUNTING = ROOT / "data" / "experiment" / "outcome-cost-accounting.json"
METRICS = ROOT / "docs" / "experiment" / "01-preliminary-comparison" / "metrics.md"
TECHNICAL = METRICS.with_name("preliminary-comparison-20260916.md")
BLUE = "#2464A4"
ORANGE = "#B96A28"
GRAY = "#E1E6EB"
GRAY_DARK = "#7B8998"
TEXT = "#202C38"
MUTED = "#566573"
GRID = "#E6EBF0"
LABELS = {"none": "추가 압축 없음", "squeez": "squeez", "Headroom": "Headroom", "LLMLingua-2": "LLMLingua-2"}


def choose_font(explicit: str | None) -> str:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(path)
        font_manager.fontManager.addfont(str(path))
        return font_manager.FontProperties(fname=str(path)).get_name()
    mac_font = Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf")
    if mac_font.is_file():
        font_manager.fontManager.addfont(str(mac_font))
        return font_manager.FontProperties(fname=str(mac_font)).get_name()
    for name in ("Noto Sans CJK KR", "Noto Sans KR", "NanumGothic", "Malgun Gothic"):
        if any(font.name == name for font in font_manager.fontManager.ttflist):
            return name
    raise RuntimeError("A Korean font is required. Supply --font /path/to/font.ttf.")


def read_source(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)


def source_record(path: Path) -> dict:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def changed_task_rows(pre: dict) -> list[dict]:
    """Join changed-span counts to higher-precision per-task cost tables.

    The rounded overview and metrics-table costs are never calculation inputs.
    Source line numbers and the exact published decimal strings are retained.
    """
    costs = {}
    task = None
    cost_table = False
    for line_number, line in enumerate(TECHNICAL.read_text(encoding="utf-8").splitlines(), 1):
        if line.startswith("## "):
            match = re.fullmatch(r"## (?:별도 집단: )?`([^`]+)`", line)
            task = match.group(1) if match else None
            cost_table = False
        if line.startswith("| 조건 | provider 계산 비용 |"):
            cost_table = True
        elif cost_table and line and not line.startswith("|"):
            cost_table = False
        if task and cost_table:
            match = re.match(r"^\| (none|squeez|Headroom|LLMLingua-2) \| \$([0-9.]+) \|", line)
            if match:
                key = (task, match.group(1))
                if key in costs:
                    raise ValueError(f"Duplicate detailed cost row: {key}")
                costs[key] = {"usd": match.group(2), "source_line": line_number}
    if len(costs) != pre["sample"]["conditions"]:
        raise ValueError("Detailed cost table no longer contains the expected 104 rows.")

    rows = []
    for line_number, line in enumerate(METRICS.read_text(encoding="utf-8").splitlines(), 1):
        if not line.startswith("| [`"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        task = re.search(r"`([^`]+)`", cells[0]).group(1)
        condition = cells[1]
        span_count, before, after = (int(cells[i].replace(",", "")) for i in (2, 3, 4))
        compressed = costs[(task, condition)]
        baseline = costs[(task, "none")]
        reduction = Decimal(before - after) / Decimal(before) * 100
        cost_delta = (Decimal(compressed["usd"]) / Decimal(baseline["usd"]) - 1) * 100
        rows.append({
            "id": f"{task}::{condition}", "task": task, "condition": condition,
            "baseline_id": f"{task}::none", "changed_spans": span_count,
            "local_tokens_before": before, "local_tokens_after": after,
            "token_reduction_percent": str(reduction),
            "api_cost_usd": compressed["usd"], "baseline_api_cost_usd": baseline["usd"],
            "api_cost_change_percent": str(cost_delta),
            "quality": cells[6].strip("`"), "baseline_quality": cells[8].strip("`"),
            "metrics_source_line": line_number,
            "cost_source_line": compressed["source_line"],
            "baseline_cost_source_line": baseline["source_line"],
        })
    expected = sum(v["changed_conditions"] for v in pre["changes"]["by_condition"].values())
    if len(rows) != expected or len({row["id"] for row in rows}) != expected:
        raise ValueError("Changed rows do not reconcile to unique changed conditions.")
    for field, source_key in (("local_tokens_before", "changed_span_tokens_before"), ("local_tokens_after", "changed_span_tokens_after")):
        if sum(row[field] for row in rows) != pre["changes"][source_key]:
            raise ValueError(f"Changed row token totals do not reconcile: {field}")
    return rows


def canvas(title: str, subtitle: str, *, left: float = 0.255, top: float = 0.735, bottom: float = 0.265):
    fig = plt.figure(figsize=(16, 9), dpi=100, facecolor="white")
    ax = fig.add_axes((left, bottom, 0.905 - left, top - bottom))
    fig.text(0.052, 0.935, title, fontsize=33, color=TEXT, va="top")
    fig.text(0.052, 0.855, subtitle, fontsize=21, color=MUTED, va="top", linespacing=1.5)
    ax.set_facecolor("white")
    ax.set_axisbelow(True)
    ax.grid(axis="x", color=GRID, linewidth=1)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#A9B5C0")
    ax.tick_params(axis="y", length=0, pad=18, labelsize=23, colors=TEXT)
    ax.tick_params(axis="x", length=0, pad=12, labelsize=18, colors=MUTED)
    return fig, ax


def notes(fig, primary: str, secondary: str, source: Path):
    fig.text(0.052, 0.155, primary, fontsize=21, color=TEXT, va="top")
    fig.text(0.052, 0.105, secondary, fontsize=18, color=MUTED, va="top")
    fig.text(0.052, 0.035, f"출처: {source.name}", fontsize=13, color=MUTED, va="bottom")


def save(fig, stem: str):
    # Fixed SVG IDs and omitted dates keep repeat renders byte-for-byte stable.
    fig.savefig(OUT / f"{stem}.png", dpi=100, metadata={"Software": "Korean briefing chart renderer"})
    fig.savefig(OUT / f"{stem}.svg", metadata={"Date": None, "Creator": "Korean briefing chart renderer"})
    svg_path = OUT / f"{stem}.svg"
    svg_path.write_text("\n".join(line.rstrip() for line in svg_path.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", help="Path to a font with Korean glyphs")
    args = parser.parse_args()
    font = choose_font(args.font)
    plt.rcParams.update({
        "font.family": font,
        "font.size": 21,
        "axes.unicode_minus": False,
        "svg.fonttype": "path",
        "svg.hashsalt": "kt-compression-briefing-v1",
        "text.color": TEXT,
        "text.usetex": False,
    })
    pre = read_source(PRELIM)
    cost = read_source(ACCOUNTING)
    conditions = pre["conditions"]
    if conditions != ["none", "squeez", "Headroom", "LLMLingua-2"]:
        raise ValueError("Review condition order and display labels before rendering.")
    tasks = pre["sample"]["tasks"]
    if pre["sample"]["repetitions_per_condition"] != 1:
        raise ValueError("The observation-count caption must be reviewed.")
    OUT.mkdir(parents=True, exist_ok=True)

    # 1. Condition composition: do not include the no-compression condition.
    compressors = conditions[1:]
    changes = pre["changes"]["by_condition"]
    changed = [changes[c]["changed_conditions"] for c in compressors]
    unchanged = [changes[c]["unchanged_conditions"] for c in compressors]
    if any(a + b != tasks for a, b in zip(changed, unchanged)):
        raise ValueError("Changed/unchanged counts do not reconcile.")
    total_changed, total_unchanged = sum(changed), sum(unchanged)
    total_conditions = tasks * len(compressors)
    fig, ax = canvas("입력 내용이 실제로 바뀐 과제 수", f"압축 도구별 {tasks}개 과제 · 파란색: 내용 변경 · 회색: 내용 그대로")
    for i, (c, a, b) in enumerate(zip(compressors, changed, unchanged)):
        ax.barh(i, a, color=BLUE, height=0.52)
        ax.barh(i, b, left=a, color=GRAY, height=0.52)
        ax.text(a / 2, i, str(a), ha="center", va="center", color="white", fontsize=23)
        ax.text(a + b / 2, i, str(b), ha="center", va="center", color=TEXT, fontsize=23)
    ax.set(yticks=range(3), yticklabels=[LABELS[c] for c in compressors], xlim=(0, tasks), ylim=(2.6, -0.6))
    ax.set_xticks([0, 5, 10, 15, 20, tasks])
    ax.set_xlabel("과제 수", labelpad=10, color=MUTED, fontsize=19)
    notes(fig, f"세 도구 합계: {total_changed}/{total_conditions}건 변경 · {total_unchanged}/{total_conditions}건 그대로", "‘내용 변경’은 입력이 바뀌었다는 뜻이며, 정답이나 비용 절감을 뜻하지 않음", PRELIM)
    save(fig, "01-changed-conditions")

    # 2. Compare only the measured changed spans, not provider/API totals.
    spans = sum(changes[c]["changed_spans"] for c in compressors)
    before = pre["changes"]["changed_span_tokens_before"]
    after = pre["changes"]["changed_span_tokens_after"]
    reduction = Decimal(before - after) / Decimal(before)
    fig, ax = canvas("내용이 바뀐 구간의 토큰 수", f"바뀐 {spans}구간만 비교 · 같은 구간의 압축 전후", left=0.20)
    for i, (value, color) in enumerate(((before, GRAY_DARK), (after, BLUE))):
        ax.barh(i, value, color=color, height=0.50)
        ax.text(value + 2100, i, f"{value:,}", va="center", fontsize=28, color=TEXT)
    ax.set(yticks=[0, 1], yticklabels=["압축 전", "압축 후"], xlim=(0, 120000), ylim=(1.6, -0.6))
    ax.set_xticks([0, 25000, 50000, 75000, 100000])
    ax.xaxis.set_major_formatter(ticker.StrMethodFormatter("{x:,.0f}"))
    ax.set_xlabel("로컬에서 센 토큰 수 (o200k_base)", labelpad=10, color=MUTED, fontsize=19)
    notes(fig, f"이 구간의 토큰 수는 약 {reduction:.0%} 감소", "전체 API 입력량이나 비용 절감률을 보여주는 수치가 아님", PRELIM)
    save(fig, "02-changed-span-tokens")

    # 3. One built-in grading result per task/condition; no significance claim.
    passes = [pre["quality"]["by_condition"][c]["pass"] for c in conditions]
    fails = [pre["quality"]["by_condition"][c]["wrong_answer"] for c in conditions]
    if any(a + b != tasks for a, b in zip(passes, fails)):
        raise ValueError("Quality counts do not reconcile.")
    fig, ax = canvas("자동 채점 기준을 통과한 과제 수", f"방식별 {tasks}개 과제 · 파란색: 통과 · 회색: 미통과")
    for i, (a, b) in enumerate(zip(passes, fails)):
        ax.barh(i, a, color=BLUE, height=0.53)
        ax.barh(i, b, left=a, color=GRAY, height=0.53)
        ax.text(a / 2, i, f"{a}/{tasks}", ha="center", va="center", color="white", fontsize=23)
        ax.text(a + b / 2, i, str(b), ha="center", va="center", color=TEXT, fontsize=23)
    ax.set(yticks=range(4), yticklabels=[LABELS[c] for c in conditions], xlim=(0, tasks), ylim=(3.6, -0.6))
    ax.set_xticks([0, 5, 10, 15, 20, tasks])
    ax.set_xlabel("과제 수", labelpad=10, color=MUTED, fontsize=19)
    notes(fig, "각 과제를 방식별로 1회씩 실행 · 도구의 우열이나 품질 유지 여부를 확정할 수 없음", "통과 기준: Terminal-Bench 자동 채점 · 고객의 실제 업무 합격 기준과는 별개", PRELIM)
    save(fig, "03-quality")

    # 4. Exact source costs are recorded in the manifest, labels round to cents.
    costs = [Decimal(str(pre["calculated_cost"]["by_condition"][c])) for c in conditions]
    requests = [pre["requests"]["by_condition"][c]["provider_http_attempts"] for c in conditions]
    if sum(costs) != Decimal(cost["completed_cohort"]["api_calculated_cost_usd"]):
        raise ValueError("Completed costs do not reconcile between sources.")
    fig, ax = canvas(f"{tasks}개 과제의 API 계산 비용", f"방식별 {tasks}개 과제의 합계 · 단위: 미국 달러")
    for i, value in enumerate(costs):
        ax.barh(i, float(value), color=BLUE, height=0.52)
        ax.text(float(value) + 0.13, i, f"${value:.2f}", va="center", fontsize=26)
    ax.set(yticks=range(4), yticklabels=[f"{LABELS[c]}\nAPI 요청 {n:,}회" for c, n in zip(conditions, requests)], xlim=(0, 8), ylim=(3.6, -0.6))
    ax.tick_params(axis="y", labelsize=20)
    ax.set_xticks([0, 2, 4, 6, 8])
    ax.set_xlabel("미국 달러", labelpad=10, color=MUTED, fontsize=19)
    notes(fig, "API 사용량 × 당시 고정 단가 · 실제 청구액과 비교하지 않음 · 서버 비용 제외", "요청 수·캐시 사용·실행 경로가 달라, 이 차이만으로 압축의 절감 효과를 확정할 수 없음", PRELIM)
    save(fig, "04-calculated-cost")

    # 5. Two distinct scopes; these totals are neither averages nor a tool comparison.
    completed_count = cost["completed_cohort"]["conditions"]
    incomplete_count = cost["pre_quality"]["started_attempts"]
    completed = Decimal(cost["completed_cohort"]["api_calculated_cost_usd"])
    incomplete = Decimal(cost["pre_quality"]["api_calculated_cost_known_usd"])
    stops = cost["pre_quality"]["outcomes"]["operator_stopped"]
    stalled = cost["pre_quality"]["outcomes"]["stalled_http_response"]
    if incomplete_count != stops + stalled:
        raise ValueError("Incomplete attempt counts do not reconcile.")
    fig, ax = canvas("완료된 실행과 미완료 실행의 API 계산 비용", "집계 대상이 다른 합계 · 평균 비용이나 압축 도구 간 비교가 아님", left=0.315)
    for i, value in enumerate((completed, incomplete)):
        ax.barh(i, float(value), color=BLUE, height=0.46)
        ax.text(float(value) + 1.9, i, f"${value:.2f}", va="center", fontsize=28)
    ax.set(yticks=[0, 1], yticklabels=[f"채점 완료 {completed_count}건\n({tasks}과제 × {len(conditions)}방식)", f"채점에 이르지 못한\n장시간 실행 {incomplete_count}건"], xlim=(0, 110), ylim=(1.65, -0.65))
    ax.tick_params(axis="y", labelsize=22)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel("확인된 API 계산 비용 합계 (미국 달러)", labelpad=10, color=MUTED, fontsize=19)
    notes(fig, f"미완료 {incomplete_count}건: 운영자 중단 {stops}건 · 응답 정체 {stalled}건", "실제 청구액과 비교하지 않음 · 서버 비용 및 사용량 미확인 요청의 추정 비용은 제외", ACCOUNTING)
    save(fig, "05-incomplete-cost")

    # 6. Observed cost differences, with the no-compression total as denominator.
    baseline_cost = costs[0]
    differences = [(value / baseline_cost - 1) * 100 for value in costs[1:]]
    fig, ax = canvas("추가 압축 없음 대비 API 계산 비용의 변화", f"추가 압축 없음 ${baseline_cost:.2f} 기준 · {tasks}과제 × 방식별 1회", left=0.24)
    for i, (delta, value) in enumerate(zip(differences, costs[1:])):
        ax.barh(i, float(delta), color=ORANGE if delta > 0 else BLUE, height=0.50)
        offset = 0.8 if delta > 0 else -0.8
        ax.text(float(delta) + offset, i, f"{delta:+.1f}%\n${value:.2f}", ha="left" if delta > 0 else "right", va="center", fontsize=25, linespacing=1.3)
    ax.axvline(0, color=TEXT, linewidth=1.5)
    ax.set(yticks=range(3), yticklabels=compressors, xlim=(-27, 27), ylim=(2.6, -0.6))
    ax.set_xticks([-20, -10, 0, 10, 20])
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: "0%" if v == 0 else f"{v:+.0f}%"))
    ax.set_xlabel("왼쪽: 비용 감소                         오른쪽: 비용 증가", labelpad=12, color=MUTED, fontsize=19)
    notes(fig, "26개 과제에서 관측한 총액 차이 · 요청 수·캐시·출력량을 통제하지 않은 결과", "API 사용량 × 당시 고정 단가 · 실제 청구액과 비교하지 않음 · 서버 비용 제외", PRELIM)
    save(fig, "06-cost-difference")

    # 7. Plot every changed condition. Shared task baselines are intentionally
    # retained, not treated as independent observations for an inferential fit.
    changed_rows = changed_task_rows(pre)
    fig, ax = canvas(f"토큰 감소율과 API 비용 변화: {len(changed_rows)}건의 관측", "가로: 변경 구간 토큰 감소 · 세로: 같은 과제의 추가 압축 없음 대비 비용 변화", left=0.14, top=0.725, bottom=0.30)
    styles = {"squeez": (ORANGE, "^"), "Headroom": (GRAY_DARK, "D"), "LLMLingua-2": (BLUE, "o")}
    for condition in compressors:
        selected = [row for row in changed_rows if row["condition"] == condition]
        color, marker = styles[condition]
        ax.scatter([float(row["token_reduction_percent"]) for row in selected], [float(row["api_cost_change_percent"]) for row in selected], s=150, c=color, marker=marker, edgecolors="white", linewidths=0.8, label=f"{condition} ({len(selected)}건)", zorder=4)
    ax.axhline(0, color=TEXT, linewidth=1.5, zorder=2)
    ax.grid(axis="y", color=GRID, linewidth=1)
    ax.spines["left"].set_visible(True)
    ax.spines["left"].set_color("#A9B5C0")
    ax.set(xlim=(0, 90), ylim=(-100, 135))
    ax.set_xticks([0, 20, 40, 60, 80])
    ax.set_yticks([-100, -50, 0, 50, 100])
    ax.xaxis.set_major_formatter(ticker.PercentFormatter(100, decimals=0))
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: "0%" if v == 0 else f"{v:+.0f}%"))
    ax.tick_params(axis="y", labelsize=17, pad=10)
    ax.set_xlabel("변경 구간 토큰 감소율", labelpad=11, color=MUTED, fontsize=20)
    ax.set_ylabel("과제 전체 API 비용 증감률", labelpad=17, color=MUTED, fontsize=20)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.07), ncols=3, frameon=False, fontsize=18, handletextpad=0.6, columnspacing=2.2)
    ax.text(2, 5, "기준 비용과 같음", color=MUTED, fontsize=16, va="bottom")
    annotations = [
        ("prove-plus-comm", "수학 증명 · prove-plus-comm", (3, 130)),
        ("sqlite-with-gcov", "프로그램 빌드\nsqlite-with-gcov", (65, -23)),
    ]
    for task, title, position in annotations:
        row = next(row for row in changed_rows if row["task"] == task and row["condition"] == "LLMLingua-2")
        x, y = float(row["token_reduction_percent"]), float(row["api_cost_change_percent"])
        caption = f"{title}\n토큰 {x:.1f}% 감소 · 비용 {y:+.1f}%"
        if task == "sqlite-with-gcov":
            caption = f"{title}\n토큰 {x:.1f}% 감소\n비용 {y:+.1f}%"
        ax.annotate(caption, (x, y), xytext=position, textcoords="data", fontsize=18, va="top", color=TEXT, linespacing=1.35,
                    bbox={"facecolor": "white", "edgecolor": "none", "pad": 3},
                    arrowprops={"arrowstyle": "-", "color": GRAY_DARK, "linewidth": 1.0, "shrinkA": 5, "shrinkB": 8}, zorder=5)
    fig.text(0.052, 0.15, "점 하나 = 한 과제의 압축 방식 1개 · 변경 구간 토큰만 비교 · 비용은 해당 과제 전체 API 계산값", fontsize=18, va="top")
    fig.text(0.052, 0.10, "방식별 1회 실행 · 같은 과제의 기준 비용을 여러 점에서 재사용 · 압축의 인과 효과를 뜻하지 않음", fontsize=17, color=MUTED, va="top")
    fig.text(0.052, 0.035, f"출처: {METRICS.name} (변경 구간) · {TECHNICAL.name} (과제별 정밀 비용)", fontsize=12, color=MUTED, va="bottom")
    save(fig, "07-token-cost-relationship")

    # 8. Recompute bill components from usage and fixed rates. The source
    # aggregate's tiny rounding residuals are preserved explicitly, never hidden.
    rates = cost["price_basis"]
    components = []
    for condition, published_cost in zip(conditions, costs):
        usage = pre["provider_usage"]["by_condition"][condition]
        uncached = Decimal(usage["input_tokens"] - usage["cached_input_tokens"]) * Decimal(rates["input_per_million_usd"]) / 1_000_000
        cached = Decimal(usage["cached_input_tokens"]) * Decimal(rates["cached_input_per_million_usd"]) / 1_000_000
        output = Decimal(usage["output_tokens"]) * Decimal(rates["output_per_million_usd"]) / 1_000_000
        total = uncached + cached + output
        components.append({"condition": condition, "uncached_input_usd": str(uncached), "cached_input_usd": str(cached), "output_usd": str(output), "component_sum_usd": str(total), "published_total_usd": str(published_cost), "component_sum_minus_published_total_usd": str(total - published_cost), "input_tokens": usage["input_tokens"], "cached_input_tokens": usage["cached_input_tokens"], "output_tokens": usage["output_tokens"]})
    fig, ax = canvas("API 계산 비용을 구성한 세 항목", f"방식별 {tasks}개 과제 합계 · API 토큰 사용량에 당시 고정 단가를 적용")
    component_keys = ["uncached_input_usd", "cached_input_usd", "output_usd"]
    component_labels = ["일반 입력", "캐시 입력", "출력"]
    component_colors = [BLUE, "#ABC7E3", "#758494"]
    for i, row in enumerate(components):
        left = Decimal(0)
        for key, label, color in zip(component_keys, component_labels, component_colors):
            value = Decimal(row[key])
            ax.barh(i, float(value), left=float(left), height=0.53, color=color, label=label if i == 0 else None)
            if key == "cached_input_usd":
                ax.text(float(left + value / 2), i - 0.32, f"${value:.2f}", ha="center", va="bottom", fontsize=18, color=TEXT)
            else:
                ax.text(float(left + value / 2), i, f"${value:.2f}", ha="center", va="center", fontsize=18, color="white")
            left += value
        ax.text(float(left) + 0.12, i, f"${left:.2f}", va="center", fontsize=24)
    ax.set(yticks=range(4), yticklabels=[LABELS[c] for c in conditions], xlim=(0, 8), ylim=(3.6, -0.6))
    ax.set_xticks([0, 2, 4, 6, 8])
    ax.set_xlabel("미국 달러", labelpad=10, color=MUTED, fontsize=19)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.04), ncols=3, frameon=False, fontsize=18, columnspacing=2)
    fig.text(0.052, 0.155, "100만 토큰당 일반 입력 $2.50 · 캐시 입력 $0.25 · 출력 $15.00", fontsize=21, va="top")
    fig.text(0.052, 0.105, "항목별 반올림으로 표시 합계와 총액이 다를 수 있음 · 실제 청구액과 비교하지 않음 · 서버 비용 제외", fontsize=18, color=MUTED, va="top")
    fig.text(0.052, 0.035, f"출처: {PRELIM.name} (사용량) · {ACCOUNTING.name} (단가)", fontsize=12, color=MUTED, va="bottom")
    save(fig, "08-billing-components")

    manifest = {
        "schema_version": 1,
        "sources": [source_record(PRELIM), source_record(ACCOUNTING), source_record(METRICS), source_record(TECHNICAL)],
        "rendering": {"width_px": 1600, "height_px": 900, "dpi": 100, "font_family": font, "matplotlib_version": matplotlib.__version__, "svg_text": "paths", "condition_order": conditions},
        "01-changed-conditions": {"condition_order": compressors, "changed": changed, "unchanged": unchanged, "denominator_each": tasks, "total_changed": total_changed, "total_unchanged": total_unchanged, "total_conditions": total_conditions, "excludes": "none condition"},
        "02-changed-span-tokens": {"changed_spans": spans, "before": before, "after": after, "reduction_fraction": str(reduction), "unit": pre["changes"]["token_unit"], "scope": "only measured changed spans; not total API input or cost"},
        "03-quality": {"condition_order": conditions, "pass": passes, "wrong_answer": fails, "denominator_each": tasks, "repetitions_per_condition": pre["sample"]["repetitions_per_condition"], "scope": "Terminal-Bench built-in grader, not customer acceptance"},
        "04-calculated-cost": {"condition_order": conditions, "calculated_cost_usd": [str(v) for v in costs], "provider_http_attempts": requests, "tasks_each": tasks, "basis": "provider usage times fixed historical rates", "invoice_reconciled": False, "includes_vm": False, "supports_causal_savings_or_ranking": False},
        "05-incomplete-cost": {"completed_conditions": completed_count, "completed_calculated_cost_usd": str(completed), "incomplete_started_attempts": incomplete_count, "incomplete_known_calculated_cost_usd": str(incomplete), "operator_stopped": stops, "stalled_http_response": stalled, "excluded_unconfirmed_estimate_usd": cost["pre_quality"]["api_unconfirmed_estimate_usd"], "invoice_reconciled": False, "includes_vm": False, "scope": "two different populations; totals, not averages; not a compressor comparison; not whole-program cost"},
        "06-cost-difference": {"condition_order": compressors, "calculated_cost_usd": [str(v) for v in costs[1:]], "baseline_condition": "none", "baseline_calculated_cost_usd": str(baseline_cost), "cost_change_percent": [str(v) for v in differences], "tasks_each": tasks, "scope": "observed aggregate cost differences, not confirmed causal savings"},
        "07-token-cost-relationship": {"rows": changed_rows, "row_count": len(changed_rows), "distinct_tasks": len({r["task"] for r in changed_rows}), "cost_lower_count": sum(Decimal(r["api_cost_change_percent"]) < 0 for r in changed_rows), "cost_higher_count": sum(Decimal(r["api_cost_change_percent"]) > 0 for r in changed_rows), "x_formula": "100 * (changed_span_tokens_before - changed_span_tokens_after) / changed_span_tokens_before", "y_formula": "100 * (same_task_compressed_API_cost / same_task_none_API_cost - 1)", "x_scope": "changed spans only, local o200k_base tokens", "y_scope": "whole-task API calculated cost from detailed per-task tables, not rounded overview costs", "repeated_baselines_are_independent": False, "regression_or_correlation_coefficient": None, "repetitions_per_task_condition": 1, "annotated_tasks": [a[0] for a in annotations]},
        "08-billing-components": {"condition_order": conditions, "rows": components, "rates_usd_per_million": {"uncached_input": rates["input_per_million_usd"], "cached_input": rates["cached_input_per_million_usd"], "output": rates["output_per_million_usd"]}, "formula": "(input_tokens - cached_input_tokens) * input_rate / 1000000 + cached_input_tokens * cached_rate / 1000000 + output_tokens * output_rate / 1000000", "scope": "component-derived amounts; small source rounding residuals retained by row", "invoice_reconciled": False, "includes_vm": False},
    }
    (OUT / "chart-data.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote 8 PNGs, 8 SVGs and chart-data.json to {OUT}")


if __name__ == "__main__":
    main()
