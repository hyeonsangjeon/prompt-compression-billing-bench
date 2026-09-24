import json
from pathlib import Path
import re
import unittest

from evidence import PUBLIC_FILES


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "docs_en/experiment/02-follow-up/swe-lancer/fixed-trace-20260923.md"
REPORT_RELATIVE = REPORT_PATH.relative_to(ROOT).as_posix()
LEGACY_PATH = ROOT / "docs_en/results/swe-lancer-fixed-trace-20260923.md"
LEGACY_RELATIVE = LEGACY_PATH.relative_to(ROOT).as_posix()
TEST_RELATIVE = "tests/test_swe_lancer_fixed_trace_report.py"

EVIDENCE_HASHES = {
    "image_manifest": "b6ee529bbc589b251d2e287aa28068ea4f7e69b3eac2927b393091ac968e7587",
    "image_config": "3ac386d8f793eb2c3fdef76766b551bb2c04da8b7dd9703a01b561c293b82400",
    "solver": "860c8bf2e65d02de9d768ff36fee6d80bb8d3dfa9955e6b83ad983ea49c62012",
    "catalog": "5c3a6d4570b49be0d9fced98f5b32487420b16f25c98d6658830e31fa03f049a",
    "task_row": "ff7ea7f9d37739a30adff1d26f51eb3baee87a1cad421d4e1cc17c26adb19702",
    "ledger": "bfcc404dd25a4f02ca7c1f237f8e876ea296e0dd40ae6e1314d54257485ffe80",
    "attestation": "bea2ebbd3de926c1c0e43ffef83eddf1a179a0e6f1387b961f68bdc1a2af48b4",
    "carrier_result": "cfaff9121067948e1d75d9af990791869906a80f04251a95c5c1b27ad77b1ff7",
    "provider_receipt": "cbee89b3ffe606345968a78caf368565e3f1a3c92dfbb4422e63bd09b8c1320c",
    "price_receipt": "77365638018ac22378a562d11164c5e364841275eb10e79c6366ae56b70e58ec",
    "outbound_receipt": "8b059b3560b6f8592ec811df111424070596fea43af86ec500392788d25bbaab",
    "carrier_verification": "cbc0c7332581c5c2487ebde0d4132a89c554557c19c58098838a086681e3cd9f",
    "carrier_negatives": "860a66d4fd716e23769617b999ada7e8c6745dfd5c277aa06ea1826fe39d195f",
    "carrier_privacy": "e8db5e1cfc17249acbb34d1a17f322b5cd427b932fdbe5a9720b07f4d59c88d7",
    "carrier_cleanup": "f8085e22492db60bd89dcbc2c6166a084a88bdb2e8a3109e06a71a830c0056a9",
    "plan": "c875e8c193c2301ba212ce88586089cff91d229c1edcae31642a52fa9d04bdc5",
    "guard": "a30973dddfc746c5a89945b4dde10863ed82fe7b919ab9e45c6f76cf90502c1c",
    "runner_stderr": "2c1873ab46abfa9cd6361d326e388be7f5f20dc69912f2ce61ca32af377f75d6",
    "empty_file": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "trace_events": "60da7b736e16e9658f8169b4efc11fa3b8f8a360103eff73bc302d78dccc81ea",
    "run_1": "4c70cb2401c52defee23d534f37fb12315f88c4a489c9c8210dd96e3c947aa1c",
    "run_2": "d140b01bf32d381f950e0aee3bab72077b6082c40ae8e65bdda11624348b9328",
    "runner_result": "5cb038090490e69f98ed311567564a1910571046e06e4fca2f0a8d8051de3242",
    "aggregate_self": "cd7bc4b17e1c861380af118464438e8d7fe1c3ae187ac02f2fb134ba1bf565f3",
    "aggregate_file": "4d820df569c9f1f3ecc7ffb61580c427c98bed82bfa1138939fbc096fb2f3cce",
    "verification": "b79cfa1f3ba2a646ba41bb614663c745b90e1a279a9fc030c9c8248f21a40fc3",
    "mutations": "8df744649cd1f4452f875310085c8cf38e87a3e1522b65773a39e85c6754b8dd",
    "privacy": "3e3c3cb17648133a5d889c56f3969c929de597275a9924f4683deb6de3d5b99c",
    "cleanup": "426a425521b6a9fdaa8b3976d5181afdf963fbb1a79e8923803d0bfc68be71b2",
    "manifest_self": "b84bc274f60def51f2beb0a5d9a161ff1230d5c926486fb6e6339ce6c50d7ff5",
    "manifest_file": "2013a6277486470e3f206f5fdeb1722bf3c87321a959b1eb5c9ef274d32d3d13",
    "remote_completion_self": "cb83835bf03363421fd0c9306816433c87591c680d9616cb2d8efe478510761e",
    "remote_completion_file": "fb10807bba9dc157a50391ce715e5c49582e98e88a7ef17a2114cbc77e855e33",
    "deallocation": "3defdd52dbb9363de37af4eb49133812972889be00f4e3af697b15b7e87f304e",
    "final_completion_self": "31699e886f151ed47c297442aa959a21d45150e34652acc761e56c4f9c196d59",
    "final_completion_file": "89b81e0930b5d827792721e37f6d6e1ac7c7143ee4db2dcb9f8f3e41a9bb4630",
    "tests": "6f0a196684be31fe01e825e0ddae71ec3352645e058b0927ee82d739a591648a",
}


class SweLancerFixedTraceReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = REPORT_PATH.read_text(encoding="utf-8")

    def test_report_preserves_terminal_outcome_and_zero_call_boundary(self):
        normalized = " ".join(self.report.split())
        protected_literals = (
            "The fixed candidate did not produce a valid provider-backed trace.",
            "The terminal result is therefore `invalid_protocol_trace`",
            "Initial pre-dispatch verification | 27/29; failed `task.row`, `image.config`",
            "Final pre-dispatch verification | 31/31",
            "Runner groups observed | 2",
            "Valid protocol traces | 0",
            "Sandbox startup attempts | 2",
            "Sandbox ready | 0",
            "Provider calls | 0",
            "Grader calls | 0",
            "Both private run logs ended while waiting for the sandbox computer to start.",
            "The benchmark grader was not invoked, so task pass is `not_measured`.",
            "Calculated API cost | `USD 0.000000`",
            "The VM reached `deallocated`",
        )
        for literal in protected_literals:
            with self.subTest(literal=literal):
                self.assertIn(literal, normalized)

        found_hashes = set(re.findall(r"\b[0-9a-f]{64}\b", self.report))
        self.assertEqual(found_hashes, set(EVIDENCE_HASHES.values()))

    def test_measurement_conditions_preserve_source_runtime_and_limits(self):
        conditions = self.report.split("## Measurement conditions", 1)[1].split(
            "\n## ", 1
        )[0]
        protected_conditions = (
            "`2026-09-23T02:12:29Z` to `2026-09-23T02:18:27.355804Z`, UTC",
            "Provider `openai`; model setting `openai/gpt-4o`",
            "reported revision `gpt-4o-2024-11-20`",
            "`openai-v1-chat-completions`",
            "Concurrency `1`; multiprocessing disabled; runner retries `0`; SDK retries `0`",
            "The command configured `disable_internet=true`; the guarded start observed `allow_internet=true`",
            "The benchmark grader was not invoked.",
            "Independent grader validation was not available",
            "`USD 2.50` per million input tokens and `USD 10.00` per million output tokens",
        )
        for literal in protected_conditions:
            with self.subTest(literal=literal):
                self.assertIn(literal, conditions)

        for literal in (
            "Attempt wall time | 4,920 seconds",
            "Cleanup reserve | 120 seconds",
            "Logical request timeout | 1,200 seconds",
            "Maximum output | 2,048 tokens",
            "Maximum request wire size | 8,000,000 bytes",
            "Attempt calculated-cost cap | USD 20.00",
            "Run calculated-cost cap | USD 20.00",
        ):
            self.assertIn(literal, self.report)

    def test_observation_explanation_limits_and_quotation_boundary_remain(self):
        normalized = " ".join(self.report.split())
        self.assertIn("> **Public quotation boundary.**", self.report)
        self.assertIn("**Observation.**", self.report)
        self.assertIn("**Possible explanation.**", self.report)
        self.assertIn("**Limits.**", self.report)
        self.assertIn(
            "the evidence did not isolate whether image startup, runtime wiring,",
            normalized,
        )
        self.assertIn(
            "It does not support a candidate pass/fail judgment",
            normalized,
        )
        self.assertIn(
            "A new execution would require a separate project item",
            normalized,
        )

    def test_navigation_publication_and_snapshot_boundaries(self):
        root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
        english_index = (ROOT / "docs_en/README.md").read_text(encoding="utf-8")
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        publication = (ROOT / "docs/publication.md").read_text(encoding="utf-8")
        snapshot = (ROOT / "docs_en/SNAPSHOT.md").read_text(encoding="utf-8")
        pages = json.loads((ROOT / "config/pages-static.json").read_text(encoding="utf-8"))

        self.assertIn(f"]({REPORT_RELATIVE})", root_readme)
        self.assertIn("](experiment/02-follow-up/swe-lancer/fixed-trace-20260923.md)", english_index)
        self.assertIn("zero valid protocol traces", " ".join(status.split()))
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
        self.assertEqual(links, ["../experiment/02-follow-up/swe-lancer/fixed-trace-20260923.md"])
        self.assertEqual((LEGACY_PATH.parent / links[0]).resolve(), REPORT_PATH.resolve())
        self.assertEqual(notice.count("]("), 1)
        self.assertIn("one-hop compatibility notice", notice)
        self.assertNotIn("Runner groups observed", notice)
        self.assertNotIn("27/29", notice)

    def test_links_resolve_and_private_shapes_are_absent(self):
        links = re.findall(r"(?<!!)\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)", self.report)
        self.assertEqual(
            links,
            [
                "../../swe-lancer-candidate-evaluation-20260920.md",
                "../../../../docs/runtime-owner-handoff.md",
            ],
        )
        for target in links:
            self.assertTrue((REPORT_PATH.parent / target).resolve().is_file())

        private_patterns = (
            r"(?:/home/|/Users/|/var/lib/|/tmp/|[A-Za-z]:\\)",
            r"/subscriptions/[^\s`]+",
            r"\b(?:sk|api)-[A-Za-z0-9]{16,}\b",
            r"https?://",
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        )
        for pattern in private_patterns:
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, self.report, re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
