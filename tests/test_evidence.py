import copy
import json
import tempfile
import unittest
from pathlib import Path

from accounting import totals
from evidence import check, result_text, validate_public_files


class EvidenceContractTests(unittest.TestCase):
    def setUp(self):
        attempt = {
            "record_type": "provider_attempt", "run_id": "synthetic-unit-fixture",
            "ledger_sha256": "unit", "source_sha256": "unit", "model": "unit",
            "call_id": "unit-call", "attempt_id": "unit-attempt",
            "attempt_number": 1, "is_retry": False, "http_status": 200,
            "provider_usage": {"prompt_tokens": 10, "completion_tokens": 3},
            "tokens": {
                "input_tokens": 10, "output_tokens": 3,
                "cached_input_tokens": None, "cache_status": "not_reported",
            },
            "included_in_totals": True,
        }
        self.data = {
            "disclosure": "sanitized_measurements", "status": "passed",
            "run_id": "synthetic-unit-fixture", "ledger_sha256": "unit",
            "source_sha256": "unit", "model": "unit", "repetitions": 1,
            "expect": {"reward_min": 1, "reward_max": 1},
            "attempts": [attempt], "usage_totals": totals([attempt]),
            "trials": [{"reward": 1, "tests": [{"name": "unit", "status": "passed"}]}],
        }

    def check_data(self, data):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "evidence.json"
            path.write_text(json.dumps(data))
            return check(path)

    def test_consistent_fixture(self):
        self.check_data(self.data)

    def test_changed_headline_rejected_both_directions(self):
        for difference in (-1, 1):
            changed = copy.deepcopy(self.data)
            changed["usage_totals"]["input_tokens"] += difference
            with self.assertRaises(ValueError):
                self.check_data(changed)

    def test_public_prompts_rejected(self):
        changed = copy.deepcopy(self.data)
        changed["attempts"][0]["request_body"] = "Must remain private"
        with self.assertRaises(ValueError):
            self.check_data(changed)

    def test_false_passing_reward_rejected(self):
        changed = copy.deepcopy(self.data)
        changed["trials"][0]["tests"][0]["status"] = "failed"
        with self.assertRaises(ValueError):
            self.check_data(changed)

    def test_changed_outcome_rejected_in_both_directions(self):
        changed = copy.deepcopy(self.data)
        changed["trials"][0]["reward"] = 0
        with self.assertRaises(ValueError):
            self.check_data(changed)
        changed = copy.deepcopy(self.data)
        changed["status"] = "failed"
        with self.assertRaises(ValueError):
            self.check_data(changed)

    def test_raw_and_unclassified_files_are_not_publishable(self):
        validate_public_files(["ledger.toml", "evidence/local-baseline.json"])
        for path in ("runs/example/response.json", ".env", "unclassified.json", "server.key"):
            with self.assertRaises(ValueError):
                validate_public_files([path])


class HeadlineContractTests(unittest.TestCase):
    def test_readme_result_matches_generated_evidence(self):
        root = Path(__file__).resolve().parents[1]
        data = check(root / "evidence/local-baseline.json")
        readme = (root / "README.md").read_text()
        actual = readme.split("<!-- measured-result -->", 1)[1].split("<!-- /measured-result -->", 1)[0].strip()
        self.assertEqual(actual, result_text(data))


if __name__ == "__main__":
    unittest.main()
