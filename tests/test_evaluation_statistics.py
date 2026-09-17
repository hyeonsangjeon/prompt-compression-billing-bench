import unittest

import numpy as np

from src.evaluation_statistics import (
    CONDITIONS,
    EvaluationInputError,
    bootstrap_effects,
    evaluate_bootstrap,
    evaluation_arrays,
    logical_trial_count,
    purpose_seed,
    required_repetitions,
)


class EvaluationStatisticsTests(unittest.TestCase):
    def test_fixed_quality_pair_plan_uses_ceiling_without_extra_compressor_factor(self):
        self.assertEqual(required_repetitions(89), 16)
        self.assertEqual(89 * required_repetitions(89), 1424)
        self.assertEqual(logical_trial_count(89), 5696)
        self.assertEqual(required_repetitions(15), 95)

    def test_complete_round_resampling_preserves_shared_none_and_is_reproducible(self):
        quality = np.array([
            [[1, 1, 0, 1], [0, 1, 0, 1]],
            [[0, 0, 1, 1], [1, 0, 1, 1]],
            [[1, 1, 1, 0], [1, 1, 1, 0]],
        ], dtype=float)
        cost = np.array([
            [[1.0, 0.7, 0.8, 0.9], [2.0, 1.4, 1.6, 1.8]],
            [[1.2, 0.8, 0.9, 1.0], [2.2, 1.5, 1.7, 1.9]],
            [[0.8, 0.5, 0.6, 0.7], [1.8, 1.2, 1.4, 1.6]],
        ])
        arrays = evaluation_arrays(quality, cost, ("task-a", "task-b"))
        first, metadata = bootstrap_effects(arrays, 1e-9, replications=200, base_seed=7, batch_size=23)
        second, _ = bootstrap_effects(arrays, 1e-9, replications=200, base_seed=7, batch_size=41)
        self.assertEqual(metadata["resampling_unit"], "complete_repeat_round_with_all_fixed_tasks_and_four_conditions")
        for compressor in CONDITIONS[1:]:
            np.testing.assert_array_equal(first[compressor]["quality"], second[compressor]["quality"])
            np.testing.assert_array_equal(first[compressor]["cost"], second[compressor]["cost"])

    def test_missing_cost_is_not_replaced_by_zero(self):
        quality = np.ones((3, 2, 4))
        cost = np.ones((3, 2, 4))
        cost[1, 0, 2] = np.nan
        result = evaluate_bootstrap(
            evaluation_arrays(quality, cost, ("task-a", "task-b")),
            1e-9,
            replications=100,
        )
        self.assertEqual(result["compressors"]["headroom"]["decision"], "inconclusive")
        self.assertIn("required_cost_missing", result["compressors"]["headroom"]["reasons"])
        self.assertNotIn("required_cost_missing", result["compressors"]["squeez"]["reasons"])

    def test_zero_width_bootstrap_is_inconclusive_not_success(self):
        quality = np.ones((4, 2, 4))
        cost = np.ones((4, 2, 4))
        cost[:, :, 1:] = 0.5
        result = evaluate_bootstrap(
            evaluation_arrays(quality, cost, ("task-a", "task-b")),
            1e-9,
            replications=100,
        )
        self.assertEqual(result["compressors"]["squeez"]["decision"], "inconclusive")
        self.assertEqual(
            result["compressors"]["squeez"]["quality_interval"]["reason"],
            "zero_width_bootstrap_distribution",
        )

    def test_near_zero_none_denominator_is_inconclusive(self):
        quality = np.ones((3, 1, 4))
        cost = np.ones((3, 1, 4))
        cost[:, :, 0] = 0.001
        result = evaluate_bootstrap(
            evaluation_arrays(quality, cost, ("task-a",)),
            0.001,
            replications=20,
        )
        self.assertEqual(result["compressors"]["llmlingua2"]["decision"], "inconclusive")
        self.assertIn(
            "none_task_mean_cost_zero_or_near_zero",
            result["compressors"]["llmlingua2"]["reasons"],
        )

    def test_input_shape_and_seed_contracts_are_explicit(self):
        with self.assertRaises(EvaluationInputError):
            evaluation_arrays(np.ones((2, 2, 3)), np.ones((2, 2, 3)), ("a", "b"))
        self.assertEqual(purpose_seed(20260915, "primary"), purpose_seed(20260915, "primary"))
        self.assertNotEqual(purpose_seed(20260915, "primary"), purpose_seed(20260915, "sensitivity"))


if __name__ == "__main__":
    unittest.main()
