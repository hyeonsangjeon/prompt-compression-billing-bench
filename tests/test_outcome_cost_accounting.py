import copy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import unittest

from jsonschema import Draft202012Validator

from src.outcome_cost_accounting import (
    EVIDENCE,
    OUTPUT,
    _aggregate_records,
    build_accounting,
    check,
    render,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/outcome-cost-accounting.schema.json"
DOCUMENT = ROOT / "docs/experiment/outcome-cost-accounting-20260918.md"
PRELIMINARY_SUMMARY = ROOT / "data/experiment/preliminary-comparison-summary.json"
RESULTS_GUIDE = ROOT / "docs/experiment/plain-language-results-20260917.md"
PRELIMINARY_REPORT = ROOT / "docs/experiment/preliminary-comparison-20260916.md"
BRIEFING = ROOT / "docs/experiment/experiment-briefing-20260919.md"
ONE_PAGE = ROOT / "docs/experiment/01-preliminary-comparison/README.md"
TASK_CATALOG = ROOT / "docs/experiment/01-preliminary-comparison/tasks.md"


def attempt(
    record_id,
    trial_key,
    outcome,
    quality,
    *,
    started=True,
    api="1",
    unknown=0,
    estimate=None,
    vm="0",
    observed_vm=None,
    blob="0",
):
    input_tokens = int(Decimal(api) * Decimal(400_000))
    return {
        "record_id": record_id,
        "scope": "completed_cohort_joined",
        "trial_key": trial_key,
        "started": started,
        "attempt_outcome": outcome,
        "quality_result": quality,
        "provider_usage": {
            "known_attempts": int(Decimal(api) > 0),
            "input_tokens": input_tokens,
            "cached_input_tokens": 0,
            "output_tokens": 0,
        },
        "cost": {
            "api_known_usd": api,
            "api_unknown_attempts": unknown,
            "api_unconfirmed_estimate_usd": estimate,
            "vm_direct_attributable_usd": vm,
            "vm_observed_non_additive_usd": observed_vm,
            "blob_network_known_usd": blob,
            "invoice_reconciled": False,
        },
    }


class OutcomeCostAccountingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads(EVIDENCE.read_bytes())
        cls.output = json.loads(OUTPUT.read_bytes())
        cls.schema = json.loads(SCHEMA.read_bytes())

    def test_generated_output_matches_in_both_directions(self):
        check()
        self.assertEqual(OUTPUT.read_text(), render())
        self.assertEqual(
            self.output["source"]["sha256"],
            hashlib.sha256(EVIDENCE.read_bytes()).hexdigest(),
        )
        Draft202012Validator(self.schema).validate(self.output)

    def test_fixed_completed_cohort_values_are_preserved(self):
        cohort = self.output["completed_cohort"]
        self.assertEqual((cohort["tasks"], cohort["conditions"]), (26, 104))
        self.assertEqual(cohort["quality"], {
            "pass": 40,
            "wrong_answer": 64,
            "wrong_format": 0,
        })
        self.assertEqual(cohort["api_calculated_cost_usd"], "22.3333885")
        self.assertEqual(cohort["arithmetic_api_cost_per_pass_usd"], "0.5583347125")
        self.assertIsNone(cohort["program_wide_cost_per_pass_usd"])

    def test_completed_cohort_controls_match_the_public_structured_summary(self):
        summary = json.loads(PRELIMINARY_SUMMARY.read_text(), parse_float=Decimal)
        self.assertEqual(summary["sample"], {
            "tasks": 26,
            "conditions_per_task": 4,
            "conditions": 104,
            "repetitions_per_condition": 1,
        })
        quality = summary["quality"]["by_condition"].values()
        self.assertEqual(sum(row["pass"] for row in quality), 40)
        quality = summary["quality"]["by_condition"].values()
        self.assertEqual(sum(row["wrong_answer"] for row in quality), 64)
        self.assertEqual(
            sum(summary["calculated_cost"]["by_condition"].values()),
            Decimal("22.3333885"),
        )

    def test_exact_outcome_subtotals_do_not_claim_full_coverage(self):
        attribution = self.output["completed_cohort"]["outcome_attribution"]
        self.assertFalse(attribution["complete"])
        self.assertEqual((attribution["joined_conditions"], attribution["missing_conditions"]), (9, 95))
        self.assertEqual(
            attribution["by_quality"]["pass"]["api_calculated_cost_known_usd"],
            "2.277506",
        )
        self.assertEqual(
            attribution["by_quality"]["pass"]["api_calculated_cost_per_quality_result_usd"],
            "0.5693765",
        )
        self.assertEqual(
            attribution["by_quality"]["normal_nonpass"]["api_calculated_cost_known_usd"],
            "7.56232",
        )
        self.assertEqual(
            attribution["by_quality"]["normal_nonpass"]["api_calculated_cost_per_quality_result_usd"],
            "1.512464",
        )
        self.assertEqual(
            attribution["unallocated"]["api_calculated_cost_known_usd"],
            "12.4935625",
        )
        self.assertIsNone(attribution["unallocated"]["vm_direct_attributable_cost_usd"])

    def test_pre_quality_costs_and_unknown_request_stay_separate(self):
        current = self.output["pre_quality"]
        self.assertEqual(current["started_attempts"], 5)
        self.assertEqual(current["quality_results"], 0)
        self.assertEqual(current["api_calculated_cost_known_usd"], "87.771254")
        self.assertEqual(current["api_unknown_attempts"], 1)
        self.assertEqual(current["api_unconfirmed_estimate_usd"], "0.1294175")
        self.assertEqual(current["vm_direct_attributable_cost_known_usd"], "4.204009802011")
        self.assertEqual(current["blob_network_cost_known_usd"], "0.000054")
        self.assertEqual(current["known_direct_cost_subtotal_usd"], "91.975317802011")
        self.assertIsNone(current["final_total_usd"])
        self.assertEqual(
            current["by_outcome"]["operator_stopped"]["api_calculated_cost_known_usd"],
            "80.879013",
        )
        self.assertEqual(
            current["by_outcome"]["stalled_http_response"]["api_calculated_cost_known_usd"],
            "6.892241",
        )

    def test_api_classification_reconciles_exactly_both_ways(self):
        reconciliation = self.output["included_scope_reconciliation"]
        classified = sum(
            Decimal(value)
            for value in reconciliation["api_by_classification"].values()
        )
        self.assertEqual(classified, Decimal("110.1046425"))
        self.assertEqual(
            classified,
            Decimal(reconciliation["api_included_known_total_usd"]),
        )
        self.assertTrue(reconciliation["api_bidirectional_match"])
        self.assertFalse(reconciliation["cross_component_total_is_final"])

    def test_attempt_and_quality_identities_cannot_be_counted_twice(self):
        first = attempt("attempt-1", "trial-1", "pass", "pass")
        with self.assertRaisesRegex(ValueError, "identifiers.*unique"):
            _aggregate_records([first, copy.deepcopy(first)])
        second = attempt("attempt-2", "trial-1", "pass", "pass")
        with self.assertRaisesRegex(ValueError, "quality result only once"):
            _aggregate_records([first, second])

    def test_started_attempt_cost_is_counted_even_before_quality(self):
        technical = attempt(
            "attempt-1",
            "trial-1",
            "technical_incomplete",
            None,
            api="1.25",
            unknown=1,
            estimate="0.5",
        )
        completed = attempt("attempt-2", "trial-1", "pass", "pass", api="2.75")
        aggregate = _aggregate_records([technical, completed])
        self.assertEqual(aggregate["pass"]["quality_results"], 1)
        self.assertEqual(aggregate["pass"]["api_calculated_cost_known_usd"], "2.75")
        self.assertEqual(aggregate["pre_quality"]["started_attempts"], 1)
        self.assertEqual(aggregate["pre_quality"]["api_calculated_cost_known_usd"], "1.25")
        self.assertEqual(aggregate["pre_quality"]["api_unknown_attempts"], 1)
        self.assertEqual(aggregate["pre_quality"]["api_unconfirmed_estimate_usd"], "0.5")

    def test_wrong_format_is_a_normally_graded_nonpass(self):
        formatted = attempt(
            "attempt-1", "trial-1", "wrong_format", "wrong_format", api="0.5"
        )
        aggregate = _aggregate_records([formatted])
        self.assertEqual(aggregate["normal_nonpass"]["quality_results"], 1)
        self.assertEqual(aggregate["normal_nonpass"]["outcomes"], {"wrong_format": 1})
        self.assertEqual(
            aggregate["normal_nonpass"]["api_calculated_cost_known_usd"], "0.5"
        )

    def test_cancelled_before_start_is_zero_or_rejected(self):
        cancelled = attempt(
            "attempt-1",
            "trial-1",
            "cancelled_before_start",
            None,
            started=False,
            api="0",
            vm="0",
            blob="0",
        )
        aggregate = _aggregate_records([cancelled])
        self.assertEqual(aggregate["cancelled_before_start"]["started_attempts"], 0)
        self.assertEqual(
            aggregate["cancelled_before_start"]["api_calculated_cost_known_usd"],
            "0",
        )
        evidence = copy.deepcopy(self.evidence)
        cancelled["scope"] = "cancelled_before_start"
        evidence["attempts"].append(cancelled)
        result = build_accounting(evidence, "0" * 64)
        self.assertEqual(
            result["cancelled_before_start"]["outcomes"],
            {"cancelled_before_start": 1},
        )
        invalid = copy.deepcopy(cancelled)
        invalid["record_id"] = "attempt-2"
        invalid["cost"]["api_known_usd"] = "0.01"
        invalid["provider_usage"]["known_attempts"] = 1
        invalid["provider_usage"]["input_tokens"] = 4000
        with self.assertRaisesRegex(ValueError, "must have zero known cost"):
            _aggregate_records([invalid])

    def test_control_drift_is_rejected(self):
        drifted = copy.deepcopy(self.evidence)
        drifted["controls"]["completed_cohort"]["api_calculated_cost_usd"] = "22"
        with self.assertRaisesRegex(ValueError, "arithmetic control drifted"):
            build_accounting(drifted, "0" * 64)

    def test_provider_usage_and_fixed_price_basis_are_checked(self):
        drifted = copy.deepcopy(self.evidence)
        drifted["attempts"][0]["provider_usage"]["output_tokens"] += 1
        with self.assertRaisesRegex(ValueError, "provider usage and fixed rates"):
            build_accounting(drifted, "0" * 64)

        drifted = copy.deepcopy(self.evidence)
        drifted["price_basis"]["output_per_million_usd"] = "14"
        with self.assertRaisesRegex(ValueError, "price basis"):
            build_accounting(drifted, "0" * 64)

    def test_long_tail_classification_controls_are_checked(self):
        drifted = copy.deepcopy(self.evidence)
        drifted["controls"]["long_tail"]["operator_stopped"] = 3
        with self.assertRaisesRegex(ValueError, "Long-tail controls"):
            build_accounting(drifted, "0" * 64)

    def test_public_json_contains_no_private_location_or_endpoint_value(self):
        text = EVIDENCE.read_text() + OUTPUT.read_text()
        self.assertNotRegex(text, r"/ai-work/|/tmp/|/mnt/|https?://")
        self.assertNotRegex(text, r"(?i)(credential|tenant|endpoint)[_-]?(id|url|value)?\s*[:=]")
        self.assertNotRegex(
            text,
            r'"(?:run_id|attempt_id|provider_request_id|request_sha256|response_sha256)"\s*:',
        )


class OutcomeCostDocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DOCUMENT.read_text()

    def test_document_keeps_measurement_and_claim_boundaries_visible(self):
        for phrase in (
            "Terminal-Bench 내장 채점 통과",
            "고객 수락을 뜻하지 않는다",
            "실제 청구서가 아니다",
            "조건당 1회",
            "캐시·요청 수·실행 경로·동시성",
            "압축기 순위",
            "압축 인과",
            "비열등성",
            "모집단 절감률",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_document_preserves_fixed_values_and_missing_join(self):
        for phrase in (
            "26과제·104조건",
            "40개",
            "64개",
            "`$22.3333885`",
            "`$0.5583347125`",
            "`$87.771254`",
            "`$0.1294175`",
            "9조건",
            "95조건",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)
        self.assertIn("프로그램 전체 통과 1건당 비용은 미확정", self.text)

    def test_relative_links_resolve(self):
        for target in re.findall(r"(?<!!)\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)", self.text):
            if re.match(r"[a-z]+://", target):
                continue
            with self.subTest(target=target):
                self.assertTrue((DOCUMENT.parent / target).resolve().exists())


class OutcomeCostPresentationNarrativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sharing = RESULTS_GUIDE.read_text()
        cls.preliminary = PRELIMINARY_REPORT.read_text()
        cls.briefing = BRIEFING.read_text()
        cls.one_page = ONE_PAGE.read_text()
        cls.one_page_flat = " ".join(cls.one_page.split())
        cls.task_catalog = TASK_CATALOG.read_text()
        cls.task_catalog_flat = " ".join(cls.task_catalog.split())

    def test_easy_narrative_keeps_result_and_cost_together(self):
        for phrase in (
            "비용을 결과와 함께 읽는 법",
            "Terminal-Bench 내장 채점을 통과한 조건 결과",
            "완결 코호트 통과 조건 1건당 `$0.5583347125`",
            "`wrong_answer` 64조건",
            "장기 실행 5개의 확인 비용 `$87.771254`",
            "고객 수락 대리 지표로 검증되지 않았고",
            "API 계산 비용도 실제 청구서가 아니다",
            "가능한 활용",
            "실제 계약 마진을 검증한 것은 아니다",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.sharing)

    def test_technical_report_preserves_formula_scope_and_classification(self):
        for phrase in (
            "$22.3333885 ÷ 40 = $0.5583347125",
            "`wrong_answer` 64조건",
            "`wrong_format`은 0조건",
            "4조건 | `$2.277506`",
            "5조건 | `$7.56232`",
            "95조건 | `$12.4935625`",
            "4시도 | `$80.879013`",
            "1시도 | `$6.892241`",
            "5시도`와 `$87.771254`",
            "추정 `$0.1294175`도 확인 비용에서 제외",
            "프로그램 전체 통과 조건 1건당 비용은 계산하지 않는다",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.preliminary)

    def test_briefing_adds_only_verified_metric_and_boundary(self):
        self.assertIn("완결 코호트 통과 조건 1건당 산술값", self.briefing)
        self.assertIn("`$0.5583347125`", self.briefing)
        self.assertIn("`pass`는 고객 수락 대리 지표로 검증되지 않았다", self.briefing)

    def test_one_page_preserves_result_cost_scope_and_missing_join(self):
        for phrase in (
            "압축 적용에서 관측한 문자열 변화와 결과별 비용",
            "소수 둘째 자리까지 반올림",
            "1차 실험에서 확인한 것",
            "이 기록으로 열어 둔 결정",
            "1차로 끝낸다면",
            "2차 검증을 한다면",
            "어느 쪽으로 갈지는 아직 정하지 않았다",
            "[26과제](tasks.md)",
            "2026-09-16~17 UTC",
            "모두 104조건",
            "`temperature=0`, `reasoning_effort=none`",
            "같은 답을 보장하지 않음",
            "채점기 거짓 실패",
            "목적 선정 5과제·15실행에서 수집한 56개 요청의 메시지 본문 UTF-8바이트",
            "15.42%",
            "0.48%~35.29%",
            "후보 범위",
            "78조건 중 23조건",
            "55조건에서는 달라지지 않았다",
            "현재 공개 집계로 두 경우를 나누지는 못한다",
            "`tiktoken 0.14.0`의 `o200k_base`",
            "48%의 분모는 문자열이 달라진 209구간만",
            "설치 출력에서는 30번째 내용 줄 뒤의 진단·완료 신호가 사라졌다",
            "별도 복합 명령에서는 앞선 목록이 30줄을 채워",
            "공개 전후 사례(정적)",
            "`[ERROR]`·`[WARNING]`",
            "`1.22.1`은 `. 22. 1`로 갈렸으며",
            "설계 제안",
            "모든 제품과 설정에 같은 보호 방식이 필요하다고 일반화하지 않는다",
            "실제 변경은 시스템의 보호 규칙을 통과한 로그 후보에서 일어났다",
            "209구간을 파일 목록·설치 기록·명령 실행 결과 같은 종류별로 다시 나누지 않으므로",
            "도구 동작을 보여 주는 정적 표본으로만 읽는다",
            "기록된 변환 문자열 변경이 0건인데도",
            "무압축 기준과 판정이 달라진 짝이 7개",
            "동일한 무압축 조건을 반복한 결과가 아니며",
            "전체 요청 이력·요청 수·캐시·실행 경로가 같았다는 증거도 아니다",
            "반복 실행은 2차를 선택할 때 필요한 설계 조건",
            "`$22.33`",
            "`$0.56`",
            "64조건의 비용도 들어 있다",
            "논리 요청 2,783회",
            "성공 응답 2,782회",
            "작업 전달 2,778회",
            "`$2.28`",
            "`$7.56`",
            "95조건",
            "`$12.49`",
            "`$87.77`",
            "약 3.9배",
            "상한 부재만이 비용 차이를 만들었다고 분리 측정한 것은 아니다",
            "정확히 연결된 9조건의 조건당 API 계산 비용",
            "bar [0.57, 1.51]",
            "통과 40조건 중 4조건",
            "정상 미통과 64조건 중 5조건",
            "대표 표본이 아니다",
            "프로그램 전체 통과 1건당 비용은 계산하지 않았다",
            "실제 청구서와 대사하지 않음",
            "양사가 합의한 업무 수락 기준",
            "공동으로 선정한 대표 업무 표본",
            "API 계산 비용, 직접 귀속 인프라 비용, 청구서 대사액",
            "실제로 시작한 미통과·재시도·품질 판정 전 시도의 비용을 각각 한 번 포함",
            "핵심 한계",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.one_page_flat)
        for exact_value in (
            "$22.3333885",
            "$0.5583347125",
            "$2.277506",
            "$7.56232",
            "$12.4935625",
            "$87.771254",
            "$110.1046425",
        ):
            with self.subTest(exact_value=exact_value):
                self.assertNotIn(exact_value, self.one_page)
        for internal_sales_phrase in (
            "프리세일즈",
            "고정가 견적",
            "제안서",
            "실제 계약 마진",
            "고객이 받아들인 결과",
        ):
            with self.subTest(internal_sales_phrase=internal_sales_phrase):
                self.assertNotIn(internal_sales_phrase, self.one_page)
        for unsupported_claim in (
            "토큰 압축 효과와 결과별 비용",
            "같은 과제를, 같은 설정으로, 압축을 걸지 않은 채 여러 번",
            "보낸 글자가 한 글자도 다르지 않았다",
            "55조건은 압축할 만한 글이 없었기 때문",
            "상한을 없앤 결과",
        ):
            with self.subTest(unsupported_claim=unsupported_claim):
                self.assertNotIn(unsupported_claim, self.one_page)

    def test_task_catalog_reconciles_public_task_metrics(self):
        rows = re.findall(
            r"^\| \[(\d+)\. `([^`]+)`\]\((https://[^)]+)\) \|.*"
            r"\| (\d)/4 \| ([^|]+) \| (\d+)회 \| "
            r"`\$(\d+\.\d{3})` \|$",
            self.task_catalog,
            re.MULTILINE,
        )
        self.assertEqual(len(rows), 26)
        self.assertEqual([int(row[0]) for row in rows], list(range(1, 27)))
        self.assertEqual(sum(int(row[3]) for row in rows), 40)
        self.assertEqual(sum(int(row[5]) for row in rows), 1027)
        self.assertEqual(sum(Decimal(row[6]) for row in rows), Decimal("22.333"))
        task_ids = {row[1] for row in rows}
        report_task_ids = set(
            re.findall(
                r"^## (?:별도 집단: )?`([^`]+)`$", self.preliminary, re.MULTILINE
            )
        )
        self.assertEqual(task_ids, report_task_ids)
        for _, task, url, _, duration, _, _ in rows:
            with self.subTest(task=task):
                self.assertIn(
                    "7131e4375048a0e408a8fb404b5f499d726b695b", url
                )
                self.assertRegex(duration, r"\d+분 \d+초~\d+분 \d+초")
        for phrase in (
            "네 비교 조건",
            "과제당 4조건, 모두 104조건",
            "`none`",
            "squeez `1.48.4`",
            "Headroom `0.36.5` paths-only",
            "LLMLingua-2 `0.2.2`",
            "논리 요청 합",
            "API 계산 비용 합",
            "실제 `pass`와 `wrong_answer`는 과제 내장 채점기의 판정",
            "반복 통과율이 아니다",
            "압축기 속도 비교로 읽지 않는다",
            "HTTP 시도, 성공 응답, 작업에 전달한 응답과 같은 사건으로 취급하지 않는다",
            "정밀 원본 합은 `$22.3333885`",
            "실제 청구서와 대사한 금액은 아니다",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.task_catalog_flat)

    def test_one_page_relative_links_resolve_after_study_grouping(self):
        for target in re.findall(
            r"(?<!!)\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)", self.one_page
        ):
            if re.match(r"[a-z]+://", target):
                continue
            with self.subTest(target=target):
                self.assertTrue((ONE_PAGE.parent / target).resolve().exists())

    def test_narrative_avoids_unvalidated_acceptance_claims(self):
        combined = "\n".join(
            (self.sharing, self.preliminary, self.briefing, self.one_page)
        )
        self.assertNotIn("쓸모 있었던 결과물", combined)
        self.assertNotIn("받아들여진 결과물", combined)
        self.assertNotIn("고객이 수락한 결과", combined)


if __name__ == "__main__":
    unittest.main()
