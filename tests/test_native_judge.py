from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from src.native_judge import classify_native, collect_native_outcome, test_failure as classify_test


def result_fixture(reward):
    return {"verifier_result": {"rewards": {"reward": reward}}, "exception_info": None}


def ctrf_fixture(status="passed", trace=None):
    return {"results": {"summary": {"tests": 1}, "tests": [{"name": "test_outputs.py::test_value", "status": status, "trace": trace}]}}


class NativeJudgeTests(unittest.TestCase):
    def test_native_reward_is_retained_not_regraded(self):
        result = classify_native(result_fixture(1), ctrf_fixture())
        self.assertEqual(result["native_reward"], 1)
        self.assertTrue(result["quality_valid"])
        self.assertEqual(result["truncation_causality"], "not_established")

    def test_failure_signatures_use_active_exception_not_quoted_source(self):
        source = 'assert output == "JSONDecodeError TimeoutError"\nE AssertionError: wrong value'
        self.assertEqual(classify_test({"name": "test_value", "status": "failed", "trace": source})["category"], "wrong_answer")
        for trace, category in (("E json.decoder.JSONDecodeError: value", "wrong_format"),
                                ("E TimeoutExpired: command", "timeout"),
                                ("E AssertionError: Unexpected header: wrong", "wrong_format")):
            self.assertEqual(classify_test({"trace": trace})["category"], category)

    def test_false_pass_and_missing_tests_are_invalid_not_zero(self):
        outcome = classify_native(result_fixture(1), ctrf_fixture("failed", "E AssertionError: wrong"))
        self.assertEqual(outcome["native_reward"], 1)
        self.assertFalse(outcome["quality_valid"])
        outcome = classify_native(None, None)
        self.assertIsNone(outcome["native_reward"])
        self.assertEqual(outcome["status"], "invalid")

    def test_malformed_nested_artifacts_never_crash_or_pass(self):
        for result, ctrf in (([], []), ({"verifier_result": []}, {}),
                             ({"verifier_result": {"rewards": []}}, {}),
                             (result_fixture(1), {"results": []}),
                             (result_fixture(1), {"results": {"tests": [{"name": [], "status": []}]}})):
            with self.subTest(result=result, ctrf=ctrf):
                self.assertFalse(classify_native(result, ctrf)["quality_valid"])

    def test_timeout_is_a_failure_reason_and_external_abort_is_not_a_native_zero(self):
        outcome = classify_native(None, None, process={"timed_out": True})
        self.assertEqual(outcome["primary_failure"], "timeout")
        self.assertIsNone(outcome["native_reward"])
        recorded = result_fixture(0)
        recorded["exception_info"] = {"exception_type": "AgentTimeoutError"}
        outcome = classify_native(recorded, ctrf_fixture("failed", "E AssertionError: wrong"))
        self.assertEqual(outcome["primary_failure"], "timeout")
        self.assertTrue(outcome["quality_valid"])

    def test_actual_deepswe_mode_rule_is_both_zero_not_a_surrogate_score(self):
        for base, added, reward in ((0, 0, 1), (0, 1, 0), (1, 0, 0), (1, 1, 0)):
            stdout = f"[verifier] Baseline exit code: {base}\n[verifier] New tests exit code: {added}\n"
            result = classify_native(result_fixture(reward), None, benchmark="deep-swe", stdout=stdout)
            self.assertTrue(result["quality_valid"])
            self.assertEqual(result["native_reward"], reward)
        self.assertFalse(classify_native(result_fixture(1), None, benchmark="deep-swe")["quality_valid"])

    def test_conflicting_deepswe_exit_codes_require_review(self):
        stdout = "[verifier] Baseline exit code: 0\n[verifier] New tests exit code: 1\n"
        self.assertFalse(classify_native(result_fixture(1), None, benchmark="deep-swe", stdout=stdout)["quality_valid"])
        self.assertFalse(classify_native(result_fixture(0), None, benchmark="deep-swe", stdout=stdout + stdout)["quality_valid"])

    def test_collection_cross_checks_reward_file_and_preserves_evidence_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            job = Path(temporary)
            trial = job / "trial"
            (trial / "verifier").mkdir(parents=True)
            (trial / "result.json").write_text(json.dumps(result_fixture(1)))
            (trial / "verifier/ctrf.json").write_text(json.dumps(ctrf_fixture()))
            reward = trial / "verifier/reward.txt"
            reward.write_text("1\n")
            outcome = collect_native_outcome(job)
            self.assertTrue(outcome["quality_valid"])
            self.assertIn("sha256", outcome["artifacts"]["ctrf"])
            reward.write_text("0\n")
            self.assertFalse(collect_native_outcome(job)["quality_valid"])


if __name__ == "__main__":
    unittest.main()
