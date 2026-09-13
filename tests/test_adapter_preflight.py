from pathlib import Path
import tempfile
import unittest

from native_helpers import FixtureEncoder, ledger_fixture
from src.adapter_preflight import candidate_content, run_condition


class AdapterPreflightTests(unittest.TestCase):
    def test_noop_uses_eight_guarded_live_requests_and_blocks_protected_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            record = run_condition(
                Path(temporary), ledger_fixture(), "none", "a" * 40, FixtureEncoder()
            )
        self.assertEqual(record["concurrent_candidate_requests"], 8)
        self.assertEqual(record["completed_compressor_calls"], 8)
        self.assertEqual(record["external_model_calls"], 0)
        self.assertTrue(record["protected_mutation_blocked_before_sender"])
        self.assertEqual(set(record["protected_byte_exact"]), {
            "system_instruction", "task_instruction", "assistant_history", "file_read_code",
        })
        self.assertTrue(all(record["protected_byte_exact"].values()))
        self.assertTrue(record["protected_not_sent_to_compressor"])
        self.assertIn("LiveRecorder.complete", record["adapter_path"])
        self.assertGreater(len(candidate_content()), 5000)


if __name__ == "__main__":
    unittest.main()
