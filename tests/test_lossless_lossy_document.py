import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "docs/experiment/01-preliminary-comparison/lossless-lossy-compression-20260919.md"
INDEX = ROOT / "docs/experiment/README.md"
SUMMARY = ROOT / "data/experiment/preliminary-comparison-summary.json"
STATIC_REPORT = ROOT / "docs/experiment/compressors.md"


class LosslessLossyDocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DOCUMENT.read_text(encoding="utf-8")
        cls.text_flat = " ".join(cls.text.split())
        cls.summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
        cls.static_report = STATIC_REPORT.read_text(encoding="utf-8")

    def test_definitions_and_distinct_boundaries_are_explicit(self):
        required = (
            "lossless compression",
            "exact source bytes",
            "**Lossy compression**",
            "cannot guarantee restoration to the same bytes",
            "Transport compression",
            "Cache",
            "Prompt-content reduction",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text_flat)

    def test_four_conditions_keep_the_implemented_classification(self):
        expected = (
            "`none` returns the input string unchanged",
            "squeez `1.48.4`",
            "Classification:** Lossy compression",
            "Headroom `0.36.5`",
            "Lossless compression within a restricted paths-only configuration",
            "LLMLingua-2 `0.2.2`",
            "`rate=0.5`",
        )
        for phrase in expected:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text_flat)
        self.assertGreaterEqual(self.text.count("Classification:** Lossy compression"), 2)

    def test_published_change_counts_match_the_aggregate(self):
        by_condition = self.summary["changes"]["by_condition"]
        for condition, display in (
            ("squeez", "squeez"),
            ("Headroom", "Headroom"),
            ("LLMLingua-2", "LLMLingua-2"),
        ):
            values = by_condition[condition]
            section = self.text.split(f"### `{display}`", 1)[1].split("\n### ", 1)[0]
            expected = f"{values['changed_spans']} spans in {values['changed_conditions']} of 26 conditions actually changed"
            with self.subTest(condition=condition):
                self.assertIn(expected, section)
        self.assertIn("209 spans in 23 conditions", self.text)
        self.assertIn("One per condition", self.text)

    def test_static_scope_matches_the_published_measurement(self):
        source_and_document = (
            ("18/107; 6/27", "18 of 107 candidate occurrences and 6 of 27 unique inputs changed"),
            ("10/107; 3/27", "10 occurrences and 3 unique inputs actually changed"),
            ("107/107; 27/27", "All 107 candidate occurrences and 27 unique inputs changed"),
        )
        for source_phrase, document_phrase in source_and_document:
            with self.subTest(source_phrase=source_phrase):
                self.assertIn(source_phrase, self.static_report)
                self.assertIn(document_phrase, self.text)
        self.assertIn("Reverse transformation reproduced the original bytes for 107/107 occurrences", self.static_report)
        self.assertIn("Restoration matched for all 107 candidate occurrences", self.text)

    def test_units_quality_and_claim_limits_are_not_merged(self):
        for phrase in (
            "Local tokens in changed spans",
            "Full API usage",
            "Calculated cost",
            "Actual invoice",
            "Quality",
            "product adoption",
            "compressor ranking",
            "quality non-inferiority",
            "population cost savings",
            "Cache, request count, path, and concurrency uncontrolled",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text_flat)
        self.assertEqual(len(re.findall(r"^\| (?:[1-9]|10) \|", self.text, re.MULTILINE)), 10)

    def test_direct_relative_links_resolve(self):
        for document in (INDEX, DOCUMENT):
            text = document.read_text(encoding="utf-8")
            for target in re.findall(r"(?<!!)\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)", text):
                if re.match(r"[a-z]+://", target):
                    continue
                with self.subTest(document=document.name, target=target):
                    self.assertTrue((document.parent / target).resolve().is_file())

    def test_document_contains_no_resource_or_private_path_value(self):
        self.assertNotRegex(
            self.text,
            r"https?://|/Users/|/home/|/ai-work/|/tmp/|\.internal\b|"
            r"(?:credential|endpoint|tenant)[_-]?(?:id|url)?\s*[:=]\s*[^`\s]+",
        )


if __name__ == "__main__":
    unittest.main()
