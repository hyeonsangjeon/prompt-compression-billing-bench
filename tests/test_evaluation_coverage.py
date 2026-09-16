import json
from pathlib import Path
import tempfile
import unittest

from src.evaluation_coverage import (
    _joint_probabilities,
    exact_binomial_upper_95,
    load_validation_manifest,
    synthetic_evaluation,
    throughput_check,
)
from src.evaluation_statistics import required_repetitions


ROOT = Path(__file__).resolve().parents[1]


class EvaluationCoverageTests(unittest.TestCase):
    def test_manifest_is_hash_bound_and_all_quality_variances_are_feasible(self):
        manifest = load_validation_manifest(ROOT / "data/experiment/coverage-validation-v1.json")
        for scenario in manifest["scenarios"]:
            records = _joint_probabilities(
                scenario["none_pass_probability"],
                scenario["quality_difference"],
                scenario["quality_difference_variances"],
            )
            self.assertEqual([record["variance"] for record in records], [0.1, 0.32, 0.4])

    def test_synthetic_data_preserves_shape_and_nonnegative_cost(self):
        manifest = load_validation_manifest(ROOT / "data/experiment/coverage-validation-v1.json")
        repetitions = required_repetitions(15)
        quality, cost = synthetic_evaluation(15, repetitions, manifest["scenarios"][0], 7)
        self.assertEqual(quality.shape, (repetitions, 15, 4))
        self.assertEqual(cost.shape, quality.shape)
        self.assertTrue((cost >= 0).all())

    def test_exact_binomial_upper_is_above_observed_rate(self):
        upper = exact_binomial_upper_95(80, 2000)
        self.assertGreater(upper, 80 / 2000)
        self.assertLess(upper, 0.06)

    def test_throughput_check_is_not_labeled_coverage_validation(self):
        manifest = load_validation_manifest(ROOT / "data/experiment/coverage-validation-v1.json")
        result = throughput_check(manifest, 15, 20, "a" * 40)
        self.assertEqual(result["kind"], "local_computation_throughput_check_not_coverage_validation")
        self.assertEqual(result["source_commit"], "a" * 40)
        self.assertEqual(result["logical_trials"], 4 * 15 * required_repetitions(15))

    def test_manifest_tampering_is_rejected(self):
        source = json.loads((ROOT / "data/experiment/coverage-validation-v1.json").read_bytes())
        source["quality_allowance"] = 0.1
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text(json.dumps(source))
            with self.assertRaisesRegex(ValueError, "hash differs"):
                load_validation_manifest(path)


if __name__ == "__main__":
    unittest.main()
