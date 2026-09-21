import json
from decimal import Decimal
from pathlib import Path
import re
import unittest

from evidence import PUBLIC_FILES


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs/experiment/01-preliminary-comparison/outcome-cost-accounting-plan-20260918.md"
SUMMARY = ROOT / "data/experiment/preliminary-comparison-summary.json"


class OutcomeCostPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PLAN.read_text(encoding="utf-8")
        cls.summary = json.loads(
            SUMMARY.read_text(encoding="utf-8"),
            parse_float=Decimal,
        )

    def test_current_completed_cohort_calculation_is_exact(self):
        pass_count = sum(
            value["pass"]
            for value in self.summary["quality"]["by_condition"].values()
        )
        wrong_answer_count = sum(
            value["wrong_answer"]
            for value in self.summary["quality"]["by_condition"].values()
        )
        calculated_cost = sum(self.summary["calculated_cost"]["by_condition"].values())
        cost_per_pass = calculated_cost / pass_count

        self.assertEqual(pass_count, 40)
        self.assertEqual(wrong_answer_count, 64)
        self.assertEqual(calculated_cost, Decimal("22.3333885"))
        self.assertEqual(cost_per_pass, Decimal("0.5583347125"))
        for value in (
            "26 tasks and 104 conditions",
            "40 `pass`",
            "64 `wrong_answer`",
            "`$22.3333885 ÷ 40 = $0.5583347125`",
        ):
            self.assertIn(value, self.text)

    def test_quality_and_cost_boundaries_are_not_merged(self):
        for phrase in (
            "Pass-Attributed Cost",
            "Normal Non-Pass Cost After Grading",
            "Cost Before Quality Judgment",
            "Cancelled before start",
            "rather than an actual invoice",
            "not customer acceptance",
            "Three-decimal rounded costs in public tables are not summed",
            "Program-Wide Cost per Pass",
            "This value is not calculated now",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_long_tail_cost_keeps_its_scope_and_unknown_amount(self):
        for phrase in (
            "Long-running attempts",
            "`$87.771254`",
            "`$0.1294175`",
            "Pre-quality-judgment cost",
            "not the program-wide sum of all pre-quality-judgment costs",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_plan_is_linked_and_publicly_allowlisted(self):
        index = (ROOT / "docs/experiment/README.md").read_text(encoding="utf-8")
        publication = (ROOT / "docs/publication.md").read_text(encoding="utf-8")
        relative = "docs/experiment/01-preliminary-comparison/outcome-cost-accounting-plan-20260918.md"

        self.assertIn("outcome-cost-accounting-plan-20260918.md", index)
        self.assertIn(relative, publication)
        self.assertIn(relative, PUBLIC_FILES)
        self.assertIn("tests/test_outcome_cost_plan.py", PUBLIC_FILES)

    def test_direct_relative_links_resolve(self):
        for target in re.findall(r"(?<!!)\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)", self.text):
            if re.match(r"[a-z]+://", target):
                continue
            with self.subTest(target=target):
                self.assertTrue((PLAN.parent / target).resolve().is_file())

    def test_plan_contains_no_private_location_or_endpoint_value(self):
        self.assertNotRegex(
            self.text,
            r"https?://|/Users/|/home/|/ai-work/|/tmp/|"
            r"(?:credential|endpoint|tenant)[_-]?(?:id|url)?\s*[:=]\s*[^`\s]+",
        )


if __name__ == "__main__":
    unittest.main()
