import json
from pathlib import Path
import re
import unittest

from evidence import PUBLIC_FILES
from src.cache_execution_figure import REPORT_RECORD, parse_report_record, validate_report


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "docs_en/experiment/02-follow-up/cache-reuse/execution-20260923.md"
REPORT_RELATIVE = REPORT_PATH.relative_to(ROOT).as_posix()
LEGACY_PATH = ROOT / "docs_en/results/cache-reuse-execution-20260923.md"
LEGACY_RELATIVE = LEGACY_PATH.relative_to(ROOT).as_posix()
TEST_RELATIVE = "tests/test_cache_execution_report.py"

EVIDENCE_HASHES = {
    "derivation": "b0cbc6a291769c034546a89979b5dfaa29a0d522df137c91224541c12cd1221f",
    "cache_ledger": "a23acd062978825530940db92d013f6ee387dbd69f9daaba90d854d5a0f48ce6",
    "native_ledger": "f978be7d59f253508d6f47689ca03da2941ce0470fed05ea493f195271351cf5",
    "runtime_facts": "dc8726d30d2b804ced536173de38bdf92e81bb2962856bb746a3dde6c6ea5063",
    "doctor": "8d10ed7bc056b46be1d3e241473c63cafba64fde265320199f5308565d0a46d1",
    "admission": "760d05559bc2973639aec2d00d57f3f2439466e855d18d7c71fd73651b0a320a",
    "plan": "660024baa192e28c6ac9b3f698e0af32054513352b001dc0a6c09378d0a3d181",
    "manifest": "4736ac072016d7d501d5dbee6011569e92abcc3fef52a5c29aae9a61a9673e21",
    "failure": "c8d83baf8bfc99b15decd275bb45e6c4ae46b0ab8d9ee5faa5958cdded691ed6",
    "aggregate": "dfeb88f3291226a5f8fa503e32f841cdf55653bcc4593fa654a204ced985f9d0",
    "stability": "d0a56c0725ba4e8ab43d162bd8859d153b0119f762025638edf28af0b022f1b9",
    "cleanup": "98292b4c810933ca319e9933fab4e08ad4b006903fa7e1b8880d02ed02fc6ec7",
    "completion": "88496d641b155f9b9b293956b692cb9103058a31b592707cd737c311e196b3b0",
    "deallocation": "6823e8e04e1db35aababbe6f45ab08dd60b7c7e66743a04f7995f810044d87e2",
}


class CacheExecutionReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = REPORT_PATH.read_text(encoding="utf-8")

    def test_report_preserves_the_sealed_result_and_nonfinding(self):
        self.assertEqual(parse_report_record(self.report), REPORT_RECORD)
        validate_report(self.report)
        protected_literals = (
            "| Cycles | 10 initially | 1 | 0 | 1 | 0 |",
            "| Bundles | 60 initially | 2 | 1 | 1 | 0 |",
            "| Task trials | 300 initially | 6 | 5 | 1 | 0 |",
            "| Successful provider calls | 18 |",
            "| Eligible request observations | 10 |",
            "| Not-applicable request observations | 8 |",
            "| Five-task descriptive request observations | 18 |",
            "| Input | 65,423 |",
            "| Cached input | 0 |",
            "| Output | 9,690 |",
            "| Input cost | $0.1635575 |",
            "| Output cost | $0.14535 |",
            "| Total calculated cost | $0.3089075 |",
            "3 of 5 passed",
            "Actual calculated cost before the integrity stop was `$0.3089075`.",
        )
        for literal in protected_literals:
            with self.subTest(literal=literal):
                self.assertIn(literal, self.report)

        normalized = " ".join(self.report.split())
        for literal in (
            "No differing prefix or prefix length was measured for the absent ordinal-3 pair",
            "no outer retry or replacement",
            "the stability comparison and extension did not run",
        ):
            with self.subTest(literal=literal):
                self.assertIn(literal, normalized)

        found_hashes = re.findall(r"\b[0-9a-f]{64}\b", self.report)
        self.assertEqual(set(found_hashes), set(EVIDENCE_HASHES.values()))
        self.assertEqual(len(found_hashes), len(EVIDENCE_HASHES))

    def test_report_answers_the_reader_questions_without_strengthening_the_result(self):
        normalized = " ".join(self.report.split())
        semantic_patterns = (
            r"Prompt caching is not the reuse of a stored answer",
            r"Compression is a separate intervention",
            r"comparable individual requests from the same task at the same logical ordinal",
            r"18 provider calls succeeded.*Six task trials started and five completed",
            r"zero valid cycles",
            r"Cached input is a subset of input rather than an additional amount",
            r"not a reconciled invoice",
            r"not a `none` versus `squeez` comparison.*general model-quality claim",
            r"evidence did not isolate whether the request-count difference came from",
        )
        for pattern in semantic_patterns:
            with self.subTest(pattern=pattern):
                self.assertRegex(normalized, pattern)

    def test_navigation_publication_and_snapshot_boundaries(self):
        root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
        english_index = (ROOT / "docs_en/README.md").read_text(encoding="utf-8")
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        publication = (ROOT / "docs/publication.md").read_text(encoding="utf-8")
        snapshot = (ROOT / "docs_en/SNAPSHOT.md").read_text(encoding="utf-8")
        pages = json.loads((ROOT / "config/pages-static.json").read_text(encoding="utf-8"))

        self.assertIn(f"]({REPORT_RELATIVE})", root_readme)
        self.assertIn("](experiment/02-follow-up/cache-reuse/execution-20260923.md)", english_index)
        self.assertIn("valid cycle denominator was zero", " ".join(status.split()))
        self.assertIn(REPORT_RELATIVE, publication)
        self.assertIn(LEGACY_RELATIVE, publication)
        self.assertIn(REPORT_RELATIVE, PUBLIC_FILES)
        self.assertIn(LEGACY_RELATIVE, PUBLIC_FILES)
        self.assertIn(TEST_RELATIVE, PUBLIC_FILES)
        self.assertNotIn(REPORT_RELATIVE, pages["source_allowlist"])
        self.assertNotIn(REPORT_RELATIVE, snapshot)

    def test_legacy_url_is_one_hop_notice_to_the_complete_report(self):
        notice = LEGACY_PATH.read_text(encoding="utf-8")
        links = re.findall(r"(?<!!)\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)", notice)
        self.assertEqual(links, ["../experiment/02-follow-up/cache-reuse/execution-20260923.md"])
        self.assertEqual((LEGACY_PATH.parent / links[0]).resolve(), REPORT_PATH.resolve())
        self.assertEqual(notice.count("]("), 1)
        self.assertIn("one-hop compatibility notice", notice)
        self.assertNotIn("| Cycles |", notice)
        self.assertNotIn("65,423", notice)

    def test_measurement_conditions_preserve_runtime_and_judging_contract(self):
        conditions = self.report.split("## Measurement conditions", 1)[1].split(
            "\n## ", 1
        )[0]
        protected_conditions = (
            "does not retain an execution date, time window, or timezone",
            "Provider `foundry`; model `gpt-5.4`; provider-reported revision "
            "`gpt-5.4-2026-03-05`",
            "`openai_v1_chat_completions` through a project-scoped Foundry endpoint binding",
            "Temperature `0`; reasoning effort `none`; `determinism_claimed=false`.",
            "Project-owned private Linux runtime using managed identity; serial concurrency `1`",
            "hash-bound namespace/isolation and external-matching-traffic evidence",
            "The native task verifier applied only to completed task trials; `3/5` is descriptive",
            "The sealed report contains no evidence of independent judge validation.",
            "Admitted fixed schedule checked at `2026-09-22T14:30:31.954Z`",
            "bound by the cache/native ledger SHA-256 values below",
        )
        for literal in protected_conditions:
            with self.subTest(literal=literal):
                self.assertIn(literal, conditions)

        self.assertIn(
            "Temperature `0` and reasoning effort `none` were configured, but those "
            "settings do not establish deterministic request counts.",
            " ".join(self.report.split()),
        )

    def test_report_links_resolve_and_private_shapes_are_absent(self):
        links = re.findall(r"(?<!!)\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)", self.report)
        self.assertEqual(links, ["../../../../docs/cache-reuse.md"])
        for target in links:
            self.assertTrue((REPORT_PATH.parent / target).resolve().is_file())

        private_patterns = (
            r"(?:/home/|/Users/|/var/lib/|/tmp/|[A-Za-z]:\\)",
            r"(?i)\b(?:subscription|tenant|resource[_ -]?group|principal)[ _-]?id\b",
            r"\b(?:sk|api)-[A-Za-z0-9]{16,}\b",
            r"https?://",
        )
        for pattern in private_patterns:
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, self.report))


if __name__ == "__main__":
    unittest.main()
