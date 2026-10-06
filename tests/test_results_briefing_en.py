import csv
import json
import unittest
from pathlib import Path

from evidence import PUBLIC_FILES


ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "data/experiment/preliminary-comparison-summary.json"
REPORT = ROOT / "docs_en/experiment/results-briefing-en.md"
CSV_PATH = ROOT / "docs_en/experiment/results-briefing-en.csv"
SHARE = ROOT / "docs_en/experiment/gbb-share-en.md"


class ResultsBriefingEnglishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
        cls.report = REPORT.read_text(encoding="utf-8")
        cls.share = SHARE.read_text(encoding="utf-8")
        with CSV_PATH.open(newline="", encoding="utf-8") as handle:
            cls.rows = list(csv.DictReader(handle))

    def test_public_files_are_registered(self):
        for relative in (
            "docs_en/experiment/results-briefing-en.md",
            "docs_en/experiment/results-briefing-en.csv",
            "docs_en/experiment/gbb-share-en.md",
            "tests/test_results_briefing_en.py",
        ):
            with self.subTest(relative=relative):
                self.assertIn(relative, PUBLIC_FILES)

    def test_main_table_matches_aggregate_and_uses_unrounded_differences(self):
        expected = {
            "No additional compression": ("none", "11", "0", "$5.62", "Reference"),
            "squeez": ("squeez", "10", "1", "$6.66", "+18.6%"),
            "Headroom": ("Headroom", "9", "4", "$5.36", "−4.6%"),
            "LLMLingua-2": ("LLMLingua-2", "10", "18", "$4.69", "−16.5%"),
        }
        reference = self.summary["calculated_cost"]["by_condition"]["none"]
        for row in self.rows:
            label = row["compression_condition"]
            key, passes, changed, display_cost, display_delta = expected[label]
            with self.subTest(condition=label):
                self.assertEqual(row["grader_passes"], passes)
                self.assertEqual(row["grader_denominator"], "26")
                self.assertEqual(row["runs_with_changed_input"], changed)
                self.assertEqual(row["changed_input_denominator"], "26")
                cost = self.summary["calculated_cost"]["by_condition"][key]
                self.assertEqual(float(row["calculated_api_cost_usd_exact"]), cost)
                self.assertEqual(row["calculated_api_cost_display"], display_cost)
                exact_delta = ((cost - reference) / reference) * 100
                self.assertAlmostEqual(
                    float(row["difference_from_no_additional_compression_percent_exact"]),
                    exact_delta,
                )
                self.assertEqual(row["difference_from_no_additional_compression_display"], display_delta)
                self.assertIn(f"| {label} | {passes}/26 | {changed}/26 | {display_cost} | {display_delta} |", self.report)

    def test_provider_usage_table_does_not_add_cached_input_again(self):
        labels = {
            "No additional compression": "none",
            "squeez": "squeez",
            "Headroom": "Headroom",
            "LLMLingua-2": "LLMLingua-2",
        }
        for label, key in labels.items():
            usage = self.summary["provider_usage"]["by_condition"][key]
            requests = self.summary["requests"]["by_condition"][key]
            expected_line = (
                f"| {label} | {usage['input_tokens']:,} | {usage['cached_input_tokens']:,} "
                f"| {usage['output_tokens']:,} | {requests['logical_model_calls']:,} "
                f"| {requests['delivered_responses']:,} |"
            )
            with self.subTest(condition=label):
                self.assertIn(expected_line, self.report)
        self.assertIn("Provider-reported total input already includes cached input", self.report)
        self.assertIn("Cached input is a subset of total input", self.report)

    def test_conditions_limits_and_share_text_stay_bounded(self):
        protected_phrases = (
            "Terminal-Bench 2.1",
            "26 tasks under four conditions",
            "104 completed task runs",
            "2026-09-16-17 UTC",
            "`gpt-5.4`",
            "`gpt-5.4-2026-03-05`",
            "Headroom paths-only",
            "not reconciled to an invoice",
            "exclude server costs",
            "One repetition cannot establish causal compression savings, retained quality, or a product ranking.",
            "`97,723 -> 50,824`",
            "Cost was lower than the no-additional-compression run in 14 comparisons and higher in 9.",
            "zero valid comparisons",
            "zero valid records",
            "USD 0.000007",
        )
        for phrase in protected_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.report)

        for phrase in (
            "not evidence that she verified or endorsed",
            "Vicky",
            "squeez",
            "Headroom",
            "LLMLingua-2",
            "gpt-5.4",
            "not a 48% reduction in total input or cost",
        ):
            with self.subTest(share_phrase=phrase):
                self.assertIn(phrase, self.share)


if __name__ == "__main__":
    unittest.main()
