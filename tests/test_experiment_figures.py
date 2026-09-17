import hashlib
import json
from pathlib import Path
import re
import unittest

from src.experiment_figures import (
    DATA,
    OUTPUTS,
    _axis_maximum,
    load_aggregate,
    render_all,
)


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs/experiment/visualization-guide-20260919.md"


class ExperimentFigureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.aggregate = load_aggregate()
        cls.guide = GUIDE.read_text()

    def test_six_figures_are_generated_from_the_hash_bound_public_aggregate(self):
        generated = render_all(self.aggregate)
        self.assertEqual(set(generated), set(OUTPUTS))
        for name, content in generated.items():
            with self.subTest(name=name):
                self.assertEqual(OUTPUTS[name].read_text(), content)
                self.assertIn('role="img"', content)
                self.assertIn("Aggregate source SHA-256", content)
                figure_hash = hashlib.sha256(content.encode()).hexdigest()
                self.assertIn(figure_hash, self.guide)

    def test_aggregate_preserves_denominators_units_and_unknown_pairs(self):
        self.assertEqual(self.aggregate["sample"], {
            "tasks": 26,
            "conditions_per_task": 4,
            "conditions": 104,
            "repetitions_per_condition": 1,
        })
        self.assertEqual(self.aggregate["quality"]["denominator"], 104)
        self.assertEqual(self.aggregate["changes"]["missing_pairs"], 166)
        self.assertEqual(
            (self.aggregate["changes"]["changed_span_tokens_before"], self.aggregate["changes"]["changed_span_tokens_after"]),
            (97723, 50824),
        )
        self.assertFalse(self.aggregate["calculated_cost"]["invoice_reconciled"])

    def test_headline_totals_match_the_public_report(self):
        quality = self.aggregate["quality"]["by_condition"].values()
        changes = self.aggregate["changes"]["by_condition"].values()
        requests = self.aggregate["requests"]["by_condition"].values()
        costs = self.aggregate["calculated_cost"]["by_condition"].values()
        self.assertEqual(sum(item["pass"] for item in quality), 40)
        self.assertEqual(sum(item["wrong_answer"] for item in quality), 64)
        self.assertEqual(sum(item["changed_conditions"] for item in changes), 23)
        self.assertEqual(sum(item["changed_spans"] for item in changes), 209)
        for field in (
            "logical_model_calls", "provider_http_attempts",
            "successful_http_responses", "delivered_responses",
        ):
            self.assertEqual(sum(item[field] for item in requests), 1027)
        self.assertAlmostEqual(sum(costs), 22.3333885)

    def test_guide_links_all_ten_eda_and_six_result_figures_with_metadata(self):
        manifest = json.loads((ROOT / "docs/eda/manifest.json").read_bytes())
        self.assertEqual(len(manifest["figures"]), 10)
        for entry in manifest["figures"]:
            with self.subTest(figure=entry["id"]):
                target = "../eda/" + entry["path"]
                self.assertIn(f"]({target})", self.guide)
                self.assertIn(entry["sha256"], self.guide)
                self.assertTrue((GUIDE.parent / target).resolve().is_file())
        self.assertEqual(len(re.findall(r"^### 결과 [1-6]\.", self.guide, re.MULTILINE)), 6)
        for required in ("표본", "분모·단위", "관측", "증명하지 않는 것"):
            self.assertGreaterEqual(self.guide.count(f"| {required} |"), 17)

    def test_units_have_separate_result_axes(self):
        expected_units = {
            "quality": "conditions",
            "changed_conditions": "conditions",
            "changed_spans": "changed spans",
            "requests": "events",
            "provider_usage": "provider-reported tokens",
            "calculated_cost": "USD",
        }
        for name, unit in expected_units.items():
            with self.subTest(name=name):
                content = OUTPUTS[name].read_text()
                self.assertIn(f"Unit: {unit}", content)
                for other in set(expected_units.values()) - {unit}:
                    self.assertNotIn(f"Unit: {other}", content)
                self.assertIn('font-variant-numeric="tabular-nums"', content)

    def test_integer_axis_ticks_match_their_positions(self):
        for maximum, unit, expected in (
            (17, "conditions", 20),
            (26, "conditions", 28),
            (154, "changed spans", 156),
            (289, "events", 292),
            (4_913_043, "provider-reported tokens", 4_913_044),
        ):
            with self.subTest(unit=unit):
                self.assertEqual(_axis_maximum(maximum, unit), expected)
        self.assertEqual(_axis_maximum(6.663187, "USD"), 6.663187)

    def test_reading_path_and_citation_rule_are_direct(self):
        briefing = (ROOT / "docs/experiment/kt-briefing-20260919.md").read_text()
        for target in (
            "visualization-guide-20260919.md",
            "preliminary-comparison-20260916.md",
            "../../README.md#try-it-in-five-minutes",
        ):
            self.assertIn(target, briefing)
        self.assertIn("인용 규칙", self.guide)
        self.assertIn("표본·분모·단위", self.guide)
        self.assertIn("조건당 1회", self.guide)
        self.assertIn("압축기 순위·인과 효과·품질 비열등성", self.guide)
        for document in (
            ROOT / "README.md",
            ROOT / "docs/experiment/README.md",
        ):
            content = document.read_text()
            self.assertLess(
                content.index("kt-sharing-20260917.md"),
                content.index("preliminary-comparison-20260916.md"),
            )
        self.assertIn("kt-sharing-20260917.md", self.guide)

    def test_all_direct_relative_links_and_images_resolve(self):
        documents = (
            ROOT / "README.md",
            ROOT / "docs/experiment/README.md",
            ROOT / "docs/experiment/kt-briefing-20260919.md",
            GUIDE,
        )
        pattern = re.compile(r"(?<!!)\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)|!\[[^\]]*\]\(([^)]+)\)")
        for document in documents:
            for match in pattern.finditer(document.read_text()):
                target = match.group(1) or match.group(2)
                if re.match(r"[a-z]+://", target):
                    continue
                with self.subTest(document=document.name, target=target):
                    self.assertTrue((document.parent / target).resolve().exists())

    def test_data_file_hash_is_named_in_the_guide(self):
        data_hash = hashlib.sha256(DATA.read_bytes()).hexdigest()
        self.assertIn(data_hash, self.guide)


if __name__ == "__main__":
    unittest.main()
