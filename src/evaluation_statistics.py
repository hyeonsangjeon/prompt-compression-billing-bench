"""Fixed-task paired evaluation statistics for the compression comparison."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import math

import numpy as np


CONDITIONS = ("none", "squeez", "headroom", "llmlingua2")
COMPRESSORS = CONDITIONS[1:]
QUALITY_ALLOWANCE = 0.05
COST_REDUCTION_THRESHOLD = 0.10
FAMILY_ALPHA = 0.05
COMPARISON_ALPHA = FAMILY_ALPHA / len(COMPRESSORS)
PLANNED_QUALITY_PAIRS = 1412
BASE_SEED = 20260915
BOOTSTRAP_REPLICATIONS = 50_000
QUANTILE_METHOD = "linear"


class EvaluationInputError(ValueError):
    pass


@dataclass(frozen=True)
class EvaluationArrays:
    quality: np.ndarray
    cost: np.ndarray
    task_ids: tuple[str, ...]

    @property
    def repetitions(self) -> int:
        return self.quality.shape[0]

    @property
    def task_count(self) -> int:
        return self.quality.shape[1]


def required_repetitions(task_count: int) -> int:
    if type(task_count) is not int or task_count < 1:
        raise EvaluationInputError("At least one fixed task is required")
    return math.ceil(PLANNED_QUALITY_PAIRS / task_count)


def logical_trial_count(task_count: int) -> int:
    return len(CONDITIONS) * task_count * required_repetitions(task_count)


def purpose_seed(base_seed: int, purpose: str) -> int:
    if type(base_seed) is not int or base_seed < 0 or not purpose:
        raise EvaluationInputError("Bootstrap seed inputs are invalid")
    payload = f"evaluation-bootstrap-v1\0{base_seed}\0{purpose}".encode()
    return int.from_bytes(sha256(payload).digest()[:8], "big")


def evaluation_arrays(quality, cost, task_ids) -> EvaluationArrays:
    quality_array = np.asarray(quality, dtype=np.float64)
    cost_array = np.asarray(cost, dtype=np.float64)
    tasks = tuple(task_ids)
    if quality_array.ndim != 3 or quality_array.shape[2] != len(CONDITIONS):
        raise EvaluationInputError("Quality must have repetition, task and four-condition dimensions")
    if cost_array.shape != quality_array.shape:
        raise EvaluationInputError("Quality and cost arrays must have identical dimensions")
    if quality_array.shape[0] < 1 or quality_array.shape[1] < 1:
        raise EvaluationInputError("Evaluation arrays cannot be empty")
    if len(tasks) != quality_array.shape[1] or len(set(tasks)) != len(tasks) or any(not task for task in tasks):
        raise EvaluationInputError("Task identifiers must be unique and match the task dimension")
    finite_quality = quality_array[np.isfinite(quality_array)]
    if not np.all(np.isin(finite_quality, (0.0, 1.0))):
        raise EvaluationInputError("Observed quality values must be pass 1, fail 0 or missing")
    if np.any(np.isinf(cost_array)) or np.any(cost_array[np.isfinite(cost_array)] < 0):
        raise EvaluationInputError("Observed costs must be finite nonnegative values or missing")
    return EvaluationArrays(quality=quality_array, cost=cost_array, task_ids=tasks)


def repeat_indices(
    repetitions: int,
    replications: int,
    seed: int,
    *,
    method: str,
    batch_size: int,
):
    if type(repetitions) is not int or repetitions < 1:
        raise EvaluationInputError("Repetition count must be positive")
    if type(replications) is not int or replications < 1:
        raise EvaluationInputError("Bootstrap replication count must be positive")
    if type(batch_size) is not int or batch_size < 1:
        raise EvaluationInputError("Bootstrap batch size must be positive")
    if method not in ("complete_repeat_round", "circular_moving_block_length_2"):
        raise EvaluationInputError("Unknown repeat resampling method")
    generator = np.random.Generator(np.random.PCG64(seed))
    for start in range(0, replications, batch_size):
        size = min(batch_size, replications - start)
        if method == "complete_repeat_round":
            yield generator.integers(0, repetitions, size=(size, repetitions), endpoint=False)
            continue
        blocks = math.ceil(repetitions / 2)
        beginnings = generator.integers(0, repetitions, size=(size, blocks), endpoint=False)
        indices = np.empty((size, blocks * 2), dtype=np.int64)
        indices[:, 0::2] = beginnings
        indices[:, 1::2] = (beginnings + 1) % repetitions
        yield indices[:, :repetitions]


def _condition_availability(arrays: EvaluationArrays, compressor_index: int, near_zero_usd: float) -> dict:
    quality_pair = arrays.quality[:, :, [0, compressor_index]]
    cost_pair = arrays.cost[:, :, [0, compressor_index]]
    quality_reasons = []
    cost_reasons = []
    if not np.all(np.isfinite(quality_pair)):
        quality_reasons.append("required_quality_missing")
    if not np.all(np.isfinite(cost_pair)):
        cost_reasons.append("required_cost_missing")
    if not cost_reasons:
        none_task_means = cost_pair[:, :, 0].mean(axis=0)
        if np.any(none_task_means <= near_zero_usd):
            cost_reasons.append("none_task_mean_cost_zero_or_near_zero")
    reasons = quality_reasons + cost_reasons
    return {
        "available": not reasons,
        "quality_available": not quality_reasons,
        "cost_available": not cost_reasons,
        "quality_reasons": quality_reasons,
        "cost_reasons": cost_reasons,
        "reasons": reasons,
    }


def point_effects(arrays: EvaluationArrays, near_zero_usd: float) -> dict:
    if type(near_zero_usd) not in (int, float) or isinstance(near_zero_usd, bool):
        raise EvaluationInputError("Near-zero cost threshold must be a number")
    if not math.isfinite(near_zero_usd) or near_zero_usd < 0:
        raise EvaluationInputError("Near-zero cost threshold must be finite and nonnegative")
    results = {}
    for compressor_index, compressor in enumerate(COMPRESSORS, start=1):
        availability = _condition_availability(arrays, compressor_index, near_zero_usd)
        quality_difference = None
        cost_reduction = None
        if availability["quality_available"]:
            quality_means = arrays.quality[:, :, [0, compressor_index]].mean(axis=0)
            quality_difference = float(np.mean(quality_means[:, 1] - quality_means[:, 0]))
        if availability["cost_available"]:
            cost_means = arrays.cost[:, :, [0, compressor_index]].mean(axis=0)
            cost_reduction = float(np.mean(1.0 - cost_means[:, 1] / cost_means[:, 0]))
        results[compressor] = {
            **availability,
            "quality_difference": quality_difference,
            "cost_reduction": cost_reduction,
        }
    return results


def bootstrap_effects(
    arrays: EvaluationArrays,
    near_zero_usd: float,
    *,
    replications: int = BOOTSTRAP_REPLICATIONS,
    base_seed: int = BASE_SEED,
    method: str = "complete_repeat_round",
    batch_size: int = 256,
) -> tuple[dict, dict]:
    availability = {
        compressor: _condition_availability(arrays, index, near_zero_usd)
        for index, compressor in enumerate(COMPRESSORS, start=1)
    }
    quality_samples = {
        compressor: np.empty(replications, dtype=np.float64)
        for compressor in COMPRESSORS if availability[compressor]["quality_available"]
    }
    cost_samples = {
        compressor: np.empty(replications, dtype=np.float64)
        for compressor in COMPRESSORS if availability[compressor]["cost_available"]
    }
    seed = purpose_seed(base_seed, method)
    offset = 0
    for indices in repeat_indices(
        arrays.repetitions, replications, seed, method=method, batch_size=batch_size
    ):
        size = indices.shape[0]
        quality_means = arrays.quality[indices].mean(axis=1)
        cost_means = arrays.cost[indices].mean(axis=1)
        for compressor_index, compressor in enumerate(COMPRESSORS, start=1):
            if availability[compressor]["quality_available"]:
                quality_samples[compressor][offset:offset + size] = np.mean(
                    quality_means[:, :, compressor_index] - quality_means[:, :, 0], axis=1
                )
            if availability[compressor]["cost_available"]:
                none = cost_means[:, :, 0]
                valid = np.all(none > near_zero_usd, axis=1)
                destination = cost_samples[compressor][offset:offset + size]
                destination[:] = np.nan
                destination[valid] = np.mean(
                    1.0 - cost_means[valid, :, compressor_index] / none[valid], axis=1
                )
        offset += size
    metadata = {
        "replications": replications,
        "base_seed": base_seed,
        "purpose_seed": seed,
        "generator": "numpy.random.PCG64",
        "numpy_version": np.__version__,
        "resampling_unit": "complete_repeat_round_with_all_fixed_tasks_and_four_conditions",
        "method": method,
        "quantile_method": QUANTILE_METHOD,
        "shared_none_preserved": True,
        "task_weight": "one_over_fixed_task_count",
    }
    return {
        compressor: {
            **availability[compressor],
            "quality": quality_samples.get(compressor),
            "cost": cost_samples.get(compressor),
        }
        for compressor in COMPRESSORS
    }, metadata


def _interval(samples: np.ndarray | None) -> dict:
    if samples is None or not np.all(np.isfinite(samples)):
        return {"status": "inconclusive", "reason": "nonfinite_bootstrap_distribution"}
    if float(np.max(samples)) == float(np.min(samples)):
        return {"status": "inconclusive", "reason": "zero_width_bootstrap_distribution"}
    one_sided_lower = float(np.quantile(samples, COMPARISON_ALPHA, method=QUANTILE_METHOD))
    two_sided = np.quantile(
        samples,
        (COMPARISON_ALPHA / 2, 1 - COMPARISON_ALPHA / 2),
        method=QUANTILE_METHOD,
    )
    return {
        "status": "finite",
        "one_sided_confidence_level": 1 - COMPARISON_ALPHA,
        "one_sided_lower": one_sided_lower,
        "descriptive_two_sided_confidence_level": 1 - COMPARISON_ALPHA,
        "descriptive_two_sided": [float(two_sided[0]), float(two_sided[1])],
    }


def evaluate_bootstrap(
    arrays: EvaluationArrays,
    near_zero_usd: float,
    *,
    replications: int = BOOTSTRAP_REPLICATIONS,
    base_seed: int = BASE_SEED,
    method: str = "complete_repeat_round",
    batch_size: int = 256,
) -> dict:
    points = point_effects(arrays, near_zero_usd)
    samples, bootstrap = bootstrap_effects(
        arrays,
        near_zero_usd,
        replications=replications,
        base_seed=base_seed,
        method=method,
        batch_size=batch_size,
    )
    compressors = {}
    for compressor in COMPRESSORS:
        quality_interval = _interval(samples[compressor]["quality"])
        cost_interval = _interval(samples[compressor]["cost"])
        if quality_interval["status"] != "finite" or cost_interval["status"] != "finite":
            decision = "inconclusive"
        elif (
            quality_interval["one_sided_lower"] > -QUALITY_ALLOWANCE
            and cost_interval["one_sided_lower"] > COST_REDUCTION_THRESHOLD
        ):
            decision = "adopt"
        else:
            decision = "adoption_criteria_not_established"
        compressors[compressor] = {
            **points[compressor],
            "quality_interval": quality_interval,
            "cost_interval": cost_interval,
            "decision": decision,
            "lower_bound_failure_does_not_establish_quality_degradation": True,
        }
    return {
        "schema_version": 1,
        "kind": "fixed_task_compression_evaluation",
        "population": "exact_task_ids_selected_by_the_preregistered_screening",
        "task_ids": list(arrays.task_ids),
        "task_count": arrays.task_count,
        "repetitions": arrays.repetitions,
        "logical_trials": arrays.task_count * arrays.repetitions * len(CONDITIONS),
        "quality_effect": "compressor_pass_rate_minus_contemporaneous_none_in_percentage_point_units",
        "cost_effect": "one_minus_compressor_over_none_direct_attributable_cost_positive_is_saving",
        "quality_allowance": QUALITY_ALLOWANCE,
        "cost_reduction_threshold": COST_REDUCTION_THRESHOLD,
        "family_alpha": FAMILY_ALPHA,
        "compressor_comparison_alpha": COMPARISON_ALPHA,
        "adoption_rule": "quality_one_sided_lower_above_minus_allowance_and_cost_one_sided_lower_above_threshold",
        "bootstrap": bootstrap,
        "compressors": compressors,
    }
