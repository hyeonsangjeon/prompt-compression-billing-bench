import unittest

from src.screening_cost import (
    allocate_active_vm_cost,
    blob_operation_cost,
    blob_write_cost,
    combined_direct_cost,
    provider_cost,
)


class ScreeningCostTests(unittest.TestCase):
    def test_provider_failure_remains_unknown_instead_of_becoming_zero(self):
        events = [
            {"event": "attempt_started", "trial_id": "attempt-a", "request": 1, "attempt": 1,
             "request_sha256": "a" * 64, "budget_reservation_usd": 0.25},
            {"event": "http", "trial_id": "attempt-a", "request": 1, "attempt": 1,
             "status": None, "calculated_cost_usd": None},
        ]
        result = provider_cost(events, "attempt-a")
        self.assertIsNone(result["calculated_cost_usd"])
        self.assertEqual((result["known_cost_usd"], result["unknown_attempts"]), (0, 1))
        self.assertEqual(result["conservative_unknown_reservation_usd"], 0.25)
        self.assertEqual(result["budget_accounted_cost_usd"], 0.25)

    def test_active_vm_cost_is_shared_only_during_overlap(self):
        result = allocate_active_vm_cost([
            {"attempt_id": "a", "started_epoch": 0, "finished_epoch": 20},
            {"attempt_id": "b", "started_epoch": 10, "finished_epoch": 30},
        ], 0.36)
        self.assertEqual(result["union_active_seconds"], 30)
        self.assertAlmostEqual(result["attempts"]["a"]["allocated_active_seconds"], 15)
        self.assertAlmostEqual(result["attempts"]["b"]["allocated_active_seconds"], 15)
        self.assertTrue(result["reconciles"])

    def test_blob_retries_leave_exact_write_cost_unknown(self):
        result = blob_write_cost([{
            "operations": {
                "payload_write": {"started": 2, "succeeded": 1},
                "manifest_write": {"started": 1, "succeeded": 1},
            },
        }], 0.05)
        self.assertEqual(result["confirmed_successful_operations"], 2)
        self.assertEqual(result["started_operations"], 3)
        self.assertEqual(result["ambiguous_operations"], 1)
        self.assertIsNone(result["calculated_cost_usd"])

    def test_blob_writes_reads_and_zero_priced_same_region_transfer_are_separate(self):
        result = blob_operation_cost([{
            "upload_state": "uploaded",
            "remote_verified_at": "2026-09-15T00:00:00+00:00",
            "payload": {"bytes": 1000},
            "manifest_bytes": 200,
            "operations": {
                "payload_write": {"started": 1, "succeeded": 1},
                "manifest_write": {"started": 1, "succeeded": 1},
                "payload_verify_read": {"started": 1, "succeeded": 1},
                "manifest_verify_read": {"started": 1, "succeeded": 1},
            },
        }], 0.05, 0.004, 0)
        self.assertAlmostEqual(result["writes"]["calculated_cost_usd"], 0.00001)
        self.assertAlmostEqual(result["verification_reads"]["calculated_cost_usd"], 0.0000008)
        self.assertEqual(result["network_transfer"]["calculated_cost_usd"], 0)
        self.assertEqual(result["unknown_component_count"], 0)
        self.assertEqual(result["items_not_remotely_verified"], 0)

    def test_combined_cost_propagates_unknown_component(self):
        result = combined_direct_cost(
            {"calculated_cost_usd": None, "known_cost_usd": 1},
            {"calculated_cost_usd": 2},
            {"calculated_cost_usd": 3, "confirmed_cost_usd": 3},
        )
        self.assertIsNone(result["calculated_cost_usd"])
        self.assertEqual(result["known_cost_subtotal_usd"], 6)
        self.assertEqual(result["unknown_components"], ["provider"])


if __name__ == "__main__":
    unittest.main()
