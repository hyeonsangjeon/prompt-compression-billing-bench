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

    def test_narrative_avoids_unvalidated_acceptance_claims(self):
        combined = "\n".join((self.sharing, self.preliminary, self.briefing))
        self.assertNotIn("쓸모 있었던 결과물", combined)
        self.assertNotIn("받아들여진 결과물", combined)
        self.assertNotIn("고객이 수락한 결과", combined)


if __name__ == "__main__":
    unittest.main()
