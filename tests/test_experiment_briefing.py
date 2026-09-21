import hashlib
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
BRIEFING = ROOT / "docs/experiment/01-preliminary-comparison/experiment-briefing-20260919.md"
DATA_GUIDE = ROOT / "docs/experiment/data-connection-guide-20260919.md"


class ExperimentBriefingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = BRIEFING.read_text()
        cls.text_flat = " ".join(cls.text.split())

    def test_protected_facts_and_denominators_are_present(self):
        required = (
            "5 tasks, 15 runs, and 56 requests",
            "0.48%–35.29%",
            "15.42% overall",
            "hypothetical deletion of all candidates 22.83%",
            "5 tasks × 20 = 100 trials",
            "26 tasks × 4 conditions = 104 conditions",
            "40 `pass` and 64 `wrong_answer`",
            "209 spans across 23 conditions",
            "`97,723 → 50,824`",
            "each totaled 1,027",
            "`$22.3333885`",
            "`$87.771254`",
            "`$0.1294175`",
        )
        for fact in required:
            with self.subTest(fact=fact):
                self.assertIn(fact, self.text_flat)

    def test_claim_limits_and_design_gaps_stay_next_to_results(self):
        for phrase in (
            "one run per condition",
            "Cache, request count, model execution path, and cross-condition concurrency were uncontrolled",
            "`temperature=0` does not guarantee identical answers",
            "verifier false failure",
            "causal compression effect",
            "compressor ranking",
            "quality non-inferiority",
            "population savings",
            "stopped post hoc",
            "unknown quality",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text_flat)
        self.assertEqual(len(re.findall(r"^\| [0-9]+\.", self.text, re.MULTILINE)), 10)

    def test_figures_have_alt_text_captions_and_hash_bound_lineage(self):
        self.assertIn("**Figure 1 alternative text.**", self.text)
        self.assertIn("```mermaid", self.text)
        self.assertIn("*Figure 1.", self.text)
        self.assertIn("**Figure 2 alternative text.**", self.text)
        self.assertIn("*Figure 2.", self.text)
        figure = ROOT / "docs/eda/figures/round2/02-candidate-share-by-type.svg"
        actual = hashlib.sha256(figure.read_bytes()).hexdigest()
        manifest = json.loads((ROOT / "docs/eda/manifest.json").read_bytes())
        entry = next(item for item in manifest["figures"] if item["path"].endswith("02-candidate-share-by-type.svg"))
        self.assertEqual(actual, entry["sha256"])
        self.assertIn(actual, self.text)
        for fact in ("5 tasks", "15 runs", "56 requests", "UTF-8"):
            self.assertIn(fact, entry["alt"])
        self.assertIn("NOT API token share", figure.read_text())

    def test_direct_relative_links_resolve(self):
        documents = (ROOT / "README.md", ROOT / "docs/experiment/README.md", BRIEFING, DATA_GUIDE)
        for document in documents:
            text = document.read_text()
            for target in re.findall(r"(?<!!)\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)", text):
                if re.match(r"[a-z]+://", target):
                    continue
                with self.subTest(document=document.name, target=target):
                    self.assertTrue((document.parent / target).resolve().exists())
            for target in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text):
                with self.subTest(document=document.name, target=target):
                    self.assertTrue((document.parent / target).resolve().is_file())


class DataConnectionGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DATA_GUIDE.read_text()
        cls.text_flat = " ".join(cls.text.split())

    def test_sha256_is_defined_before_first_use(self):
        definition = "**file fingerprint (SHA-256 hash)**"
        self.assertIn(definition, self.text)
        self.assertEqual(
            self.text.index("SHA-256"),
            self.text.index(definition) + definition.index("SHA-256"),
        )

    def test_existing_single_task_contract_is_reused(self):
        for phrase in (
            "examples/experiment/benchmark.yaml",
            "src/benchmark_run.py",
            "src/screening_run.py",
            "schemas/experiment-result.schema.json",
            "screening_run --diagnose-task",
            "does not create a new runner or bypass",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text_flat)

    def test_no_call_and_quality_boundaries_are_explicit(self):
        for phrase in (
            "no-call preflight",
            "status = checked",
            "outcome = preflight_passed",
            "technical_incomplete",
            "do not convert to a wrong answer",
            "quality.status=wrong_answer",
            "quality.status=wrong_format",
            "--execute",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text_flat)

    def test_private_values_and_measurement_units_stay_separate(self):
        for phrase in (
            "Do not move source data",
            "actually changed-span tokens",
            "Full API usage",
            "Calculated cost",
            "Actual invoice",
            "cost.invoice_reconciled=false",
            "unobserved usage to zero",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text_flat)
        for environment_name in (
            "FOUNDRY_ENDPOINT",
            "SCREENING_OPERATIONAL_LEDGER",
            "TERMINAL_BENCH_ROOT",
            "SCREENING_INVENTORY",
        ):
            self.assertIn(environment_name, self.text)
        self.assertNotRegex(self.text, r"https?://|/Users/|/home/|/ai-work/|/tmp/")

    def test_fixed_benchmark_scope_is_not_presented_as_arbitrary_customer_data(self):
        for phrase in (
            "not a generic runner for arbitrary customer-data formats",
            "A task absent from the public index is rejected during no-call preflight",
            "Requires separate review",
            "one run cannot establish cross-condition ranking or non-inferiority",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text_flat)


if __name__ == "__main__":
    unittest.main()
