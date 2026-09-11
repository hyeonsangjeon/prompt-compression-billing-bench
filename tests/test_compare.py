import copy
import unittest

from src.compare import assert_swap, differences
from src.measurement import billed_unavailable


class SwapComparisonTests(unittest.TestCase):
    def setUp(self):
        self.ledger = {"compressor": {"name": "none", "tools": {"none": {}, "squeez": {}}}, "execution": {"passes": 1, "judge": "not_run"}}
        self.changed_ledger = copy.deepcopy(self.ledger)
        self.changed_ledger["compressor"]["name"] = "squeez"
        self.record = {
            "source_commit": "a" * 40, "source_sha256": "b" * 64, "manifest_sha256": "c" * 64,
            "sample": {"requests": 1}, "protection": {"status": "passed"},
            "deletion_reference": {"kind": "calculated", "saved_percent": 20},
            "judge": {"status": "not_run", "score": None}, "measured_billed": billed_unavailable(),
            "measured_local": {"before": {"message_content_tokens": 100}},
            "reductions": {"saved": {"message_content_tokens": 0}},
        }

    def test_only_name_may_differ(self):
        self.assertEqual(differences(self.ledger, self.changed_ledger), ["compressor.name"])
        assert_swap(self.record, self.record, self.ledger, self.changed_ledger)
        for field in ("passes", "judge"):
            changed = copy.deepcopy(self.changed_ledger)
            changed["execution"][field] = "different"
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "more than"):
                assert_swap(self.record, self.record, self.ledger, changed)

    def test_source_sample_protection_and_deletion_cannot_change(self):
        for field in ("source_commit", "source_sha256", "manifest_sha256", "sample", "protection", "deletion_reference", "judge", "measured_billed"):
            changed = copy.deepcopy(self.record)
            changed[field] = "different"
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "conditions differ"):
                assert_swap(self.record, changed, self.ledger, self.changed_ledger)

    def test_false_noop_improvements_and_regressions_are_refused(self):
        for difference in (-1, 1):
            changed = copy.deepcopy(self.record)
            changed["reductions"]["saved"]["message_content_tokens"] = difference
            with self.subTest(difference=difference), self.assertRaisesRegex(ValueError, "identity"):
                assert_swap(changed, self.record, self.ledger, self.changed_ledger)


if __name__ == "__main__":
    unittest.main()
