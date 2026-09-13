import unittest

from src.baseline import baseline_summary, compare_quality, interim_baseline_gate
from src.native_contract import TASKS


class BaselineTests(unittest.TestCase):
    def rows(self, count, passed=3):
        return [{task: int(index < passed) for index, task in enumerate(TASKS)} for _index in range(count)]

    def test_unit_is_five_tasks_per_repetition_not_fifty_independent_tasks(self):
        summary = baseline_summary(self.rows(10), list(TASKS))
        self.assertEqual(summary["native_trials"], 50)
        self.assertEqual(summary["suite_pass_counts"], [3] * 10)
        self.assertEqual(summary["range_width"], 0)
        self.assertEqual(summary["sample_standard_deviation"], 0)
        self.assertFalse(summary["equivalence_proven"])
        self.assertEqual(summary["rule_status"], "proposal_not_approved")

    def test_stop_checkpoints_are_ten_and_twenty(self):
        self.assertEqual(baseline_summary(self.rows(9), list(TASKS))["status"], "collect_to_10")
        changed = self.rows(5, 3) + self.rows(5, 2)
        self.assertEqual(baseline_summary(changed, list(TASKS))["status"], "extend_to_total_20")
        self.assertEqual(baseline_summary(changed + self.rows(10, 1), list(TASKS))["status"], "stop_inconclusive")

    def test_five_repetition_gate_is_operational_not_stability_evidence(self):
        continued = interim_baseline_gate(self.rows(5, 3), list(TASKS))
        self.assertEqual(continued["decision"], "continue_to_10")
        self.assertFalse(continued["stability_proven"])
        changed = self.rows(5, 3)
        changed[1] = self.rows(1, 1)[0]
        stopped = interim_baseline_gate(changed, list(TASKS))
        self.assertEqual(stopped["range_width"], 2)
        self.assertEqual(stopped["decision"], "stop_for_design_audit")
        self.assertFalse(stopped["threshold_empirically_calibrated"])

    def test_task_swaps_cannot_hide_behind_equal_suite_counts(self):
        rows = self.rows(10)
        for row in rows[5:]:
            row[TASKS[0]], row[TASKS[4]] = 0, 1
        self.assertEqual(baseline_summary(rows, list(TASKS))["status"], "extend_to_total_20")

    def test_incomplete_invalid_and_excess_repetitions_are_not_zero(self):
        for rows in ([], self.rows(21), [{TASKS[0]: 1}], [dict.fromkeys(TASKS, None)], [dict.fromkeys(TASKS, True)]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                baseline_summary(rows, list(TASKS))

    def test_floor_and_no_intervention_are_not_safety_evidence(self):
        rows = self.rows(10, 0)
        self.assertFalse(baseline_summary(rows, list(TASKS))["comparison_informative"])
        self.assertEqual(compare_quality(rows, rows, list(TASKS), 18)["decision"], "inconclusive_baseline")
        rows = self.rows(10)
        self.assertEqual(compare_quality(rows, rows, list(TASKS), 0)["decision"], "no_intervention_not_a_safety_test")
        self.assertEqual(compare_quality(rows, rows, list(TASKS), 18)["decision"], "within_observed_range_with_floor_limits")

    def test_quality_degradation_and_compensating_task_improvement_are_visible(self):
        rows, changed = self.rows(10), self.rows(10)
        changed[0][TASKS[0]] = 0
        self.assertEqual(compare_quality(rows, changed, list(TASKS), 18)["decision"], "below_observed_baseline_range")
        changed[0][TASKS[4]] = 1
        result = compare_quality(rows, changed, list(TASKS), 18)
        self.assertEqual(result["decision"], "below_observed_baseline_range")
        self.assertEqual(result["previously_always_passing_tasks_now_failed"], [TASKS[0]])

    def test_comparison_repetitions_must_match(self):
        with self.assertRaises(ValueError):
            compare_quality(self.rows(10), self.rows(20), list(TASKS), 1)


if __name__ == "__main__":
    unittest.main()
