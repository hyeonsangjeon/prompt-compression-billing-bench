import json
import sqlite3
import unittest

from src.preliminary_comparison import _linked_candidates, condition_order


class PreliminaryComparisonTests(unittest.TestCase):
    def test_selection_accepts_a_complete_wrong_answer_without_success_filtering(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        connection.execute(
            """CREATE TABLE continuation_links (
                 task_id TEXT, result TEXT, evidence_disposition TEXT,
                 evidence_sha256 TEXT, record_json TEXT
               )"""
        )
        evidence_sha256 = "a" * 64
        image_digest = "sha256:" + "b" * 64
        record = {
            "task_id": "first-task",
            "result": "wrong_answer",
            "evidence_disposition": "quality_result_complete",
            "evidence_sha256": evidence_sha256,
            "image_platform_digest": image_digest,
            "artifact_manifest_sha256": "c" * 64,
            "blob_payload_sha256": "d" * 64,
            "blob_remote_verified_at": "2026-09-16T00:00:00+00:00",
            "prior_attempt_id": "e" * 64,
            "no_limit_policy_reuse": {"reusable": True},
        }
        connection.execute(
            "INSERT INTO continuation_links VALUES (?,?,?,?,?)",
            (
                "first-task",
                "wrong_answer",
                "quality_result_complete",
                evidence_sha256,
                json.dumps(record),
            ),
        )
        inventory = {
            "tasks": [{
                "task_id": "first-task",
                "exclusion": None,
                "image": {"platform_digest": image_digest},
            }],
        }

        selected = _linked_candidates(connection, inventory)

        self.assertEqual(selected["first-task"]["result"], "wrong_answer")
        self.assertEqual(
            selected["first-task"]["evidence_source"],
            "read_only_linked_quality_result",
        )

    def test_condition_order_is_seeded_and_contains_each_condition_once(self):
        first = condition_order("first-task", "f" * 64)
        second = condition_order("first-task", "f" * 64)

        self.assertEqual(first, second)
        self.assertEqual(set(first), {"none", "squeez", "headroom", "llmlingua2"})
        self.assertEqual(len(first), 4)


if __name__ == "__main__":
    unittest.main()
