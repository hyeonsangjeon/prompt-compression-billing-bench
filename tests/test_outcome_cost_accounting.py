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
DOCUMENT = ROOT / "docs/experiment/01-preliminary-comparison/outcome-cost-accounting-20260918.md"
PRELIMINARY_SUMMARY = ROOT / "data/experiment/preliminary-comparison-summary.json"
RESULTS_GUIDE = ROOT / "docs/experiment/01-preliminary-comparison/plain-language-results-20260917.md"
PRELIMINARY_REPORT = ROOT / "docs/experiment/01-preliminary-comparison/preliminary-comparison-20260916.md"
BRIEFING = ROOT / "docs/experiment/01-preliminary-comparison/experiment-briefing-20260919.md"
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
        cls.text_flat = " ".join(cls.text.split())

    def test_document_keeps_measurement_and_claim_boundaries_visible(self):
        for phrase in (
            "Terminal-Bench built-in grader",
            "does not mean customer acceptance",
            "not an actual invoice",
            "ran once each",
            "cache, request count, execution path, or concurrency",
            "compressor ranking",
            "compression causality",
            "quality non-inferiority",
            "population savings",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text_flat)

    def test_document_preserves_fixed_values_and_missing_join(self):
        for phrase in (
            "26 tasks and 104 conditions",
            "40 passes",
            "64 `wrong_answer`",
            "`$22.3333885`",
            "`$0.5583347125`",
            "`$87.771254`",
            "`$0.1294175`",
            "9 conditions",
            "95 conditions",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text_flat)
        self.assertIn("program-wide cost per pass remains unknown", self.text_flat)

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
            "Reading Cost Together With Outcome",
            "conditions that passed the Terminal-Bench built-in grader",
            "`$0.5583347125` per passing\n> condition in the completed cohort",
            "64 `wrong_answer` conditions",
            "`$87.771254` in confirmed cost from five long-running executions",
            "not been validated as a proxy for customer\nacceptance",
            "calculated API cost is not an invoice",
            "Possible use",
            "did not validate customer acceptance or actual contract margin",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.sharing)

    def test_technical_report_preserves_formula_scope_and_classification(self):
        for phrase in (
            "$22.3333885 ÷ 40 = $0.5583347125",
            "64 `wrong_answer` conditions",
            "0 `wrong_format` conditions",
            "4 conditions | `$2.277506`",
            "5 conditions | `$7.56232`",
            "95 conditions | `$12.4935625`",
            "4 attempts | `$80.879013`",
            "1 attempt | `$6.892241`",
            "5 attempts` and `$87.771254`",
            "estimate of `$0.1294175` for one request without usage",
            "does not calculate program-wide cost per passing condition",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.preliminary)

    def test_briefing_adds_only_verified_metric_and_boundary(self):
        self.assertIn("arithmetic value per passing condition in the completed cohort", self.briefing)
        self.assertIn("`$0.5583347125`", self.briefing)
        self.assertIn("`pass` has not been\n  validated as a proxy for customer acceptance", self.briefing)

    def test_one_page_preserves_result_cost_scope_and_missing_join(self):
        for phrase in (
            "Observed String Changes and Cost by Outcome",
            "rounded to two decimal places",
            "What the Preliminary Experiment Established",
            "Appropriate Use of This Record",
            "Established by current evidence",
            "If further evidence is needed",
            "No decision has been made to run additional validation",
            "does not urge a particular choice",
            "[26 Terminal-Bench 2.1 tasks](tasks.md)",
            "2026-09-16–17 UTC",
            "104 conditions total",
            "`temperature=0`, `reasoning_effort=none`",
            "not a guarantee of identical answers",
            "verifier false-failure case",
            "UTF-8 bytes of message content from 56 requests collected across 5 purposively selected tasks and 15 historical runs",
            "15.42%",
            "0.48%–35.29%",
            "candidate scope",
            "23 conditions and did not change in 55",
            "current public aggregate cannot distinguish those cases",
            "tiktoken `0.14.0` and `o200k_base`",
            "denominator for 48% is only the 209 spans whose strings changed",
            "Installation diagnostics and completion signals after the 30th content line disappeared",
            "an earlier listing filled 30 lines",
            "Public before-and-after example (static)",
            "`[ERROR]` and `[WARNING]`",
            "`1.22.1` became `. 22. 1`",
            "Design proposal",
            "does not establish that every product and setting requires the same protection mechanism",
            "Actual changes occurred in log candidates that passed the system's protection rules",
            "public aggregate does not reclassify the 209 spans as file lists, installation logs",
            "static illustrations of tool behavior",
            "transformed-string change count was zero",
            "Seven squeez or Headroom pairs received different judgments from `none`",
            "not repeated runs of the same uncompressed condition",
            "no evidence that full request history, request count, cache state, or execution path matched",
            "Repeated execution is a design condition for any further validation",
            "`$22.33`",
            "`$0.56`",
            "cost of 64 normal non-passes",
            "2,783 logical requests",
            "2,782 successful responses",
            "2,778 task deliveries",
            "`$2.28`",
            "`$7.56`",
            "95 conditions",
            "`$12.49`",
            "`$87.77`",
            "about 3.9 times",
            "did not isolate absence of a limit as the sole cause of the cost difference",
            "Calculated API Cost per Condition for 9 Exactly Linked Conditions",
            "bar [0.57, 1.51]",
            "4 of 40 passing conditions",
            "5 of 64 normal non-passing conditions",
            "not a representative sample",
            "Program-wide cost per pass was therefore not calculated",
            "not reconciled to an actual invoice",
            "jointly agreed business-acceptance criterion",
            "representative work sample",
            "calculated API cost, directly attributable infrastructure cost, or invoice-reconciled spend",
            "include exactly once every cost in the preregistered attribution scope from started non-passes, retries, and attempts that ended before quality judgment",
            "Key Limitations",
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
            "presales",
            "fixed-price estimate",
            "sales proposal",
            "actual contract margin",
            "customer-accepted result",
        ):
            with self.subTest(internal_sales_phrase=internal_sales_phrase):
                self.assertNotIn(internal_sales_phrase, self.one_page)
        for unsupported_claim in (
            "Token Compression Effects and Cost by Outcome",
            "the same tasks, with the same settings, repeatedly without compression",
            "the sent text was byte-identical",
            "all 55 conditions had nothing compressible",
            "caused by removing the limit",
        ):
            with self.subTest(unsupported_claim=unsupported_claim):
                self.assertNotIn(unsupported_claim, self.one_page)

    def test_task_catalog_reconciles_public_task_metrics(self):
        rows = re.findall(
            r"^\| \[(\d+)\. `([^`]+)`\]\((https://[^)]+)\) \|.*"
            r"\| (\d)/4 \| ([^|]+) \| (\d+) \| "
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
                r"^## (?:Separate Cohort: )?`([^`]+)`$", self.preliminary, re.MULTILINE
            )
        )
        self.assertEqual(task_ids, report_task_ids)
        for _, task, url, _, duration, _, _ in rows:
            with self.subTest(task=task):
                self.assertIn(
                    "7131e4375048a0e408a8fb404b5f499d726b695b", url
                )
                self.assertRegex(duration, r"\d+ min \d+ sec–\d+ min \d+ sec")
        for phrase in (
            "Four Comparison Conditions",
            "4 conditions per task and 104 total",
            "`none`",
            "squeez `1.48.4`",
            "Headroom `0.36.5` paths-only",
            "LLMLingua-2 `0.2.2`",
            "Logical requests",
            "Calculated API cost",
            "Actual `pass` and `wrong_answer` values are judgments from the task's built-in grader",
            "not a repeated-run pass rate",
            "unsuitable for comparing compressor speed",
            "not interchangeable with HTTP attempts, successful responses, or responses delivered to the task",
            "precise source sum is `$22.3333885`",
            "not an invoice-reconciled amount",
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
        self.assertNotIn("useful output", combined)
        self.assertNotIn("accepted output", combined)
        self.assertNotIn("customer-accepted result", combined)


if __name__ == "__main__":
    unittest.main()
