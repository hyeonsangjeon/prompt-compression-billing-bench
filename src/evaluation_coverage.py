"""Synthetic operating check for the fixed-task percentile-bootstrap decision."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import time

import numpy as np

from .evaluation_statistics import (
    BOOTSTRAP_REPLICATIONS,
    COMPRESSORS,
    CONDITIONS,
    COST_REDUCTION_THRESHOLD,
    PLANNED_QUALITY_PAIRS,
    QUALITY_ALLOWANCE,
    evaluate_bootstrap,
    evaluation_arrays,
    purpose_seed,
    required_repetitions,
)
from .screening_inventory import canonical_json
from .protection import digest


def load_validation_manifest(path: Path) -> dict:
    value = json.loads(path.read_bytes())
    claimed = value.get("manifest_sha256")
    payload = {name: item for name, item in value.items() if name != "manifest_sha256"}
    if claimed != digest(canonical_json(payload)):
        raise ValueError("Coverage-validation manifest hash differs")
    if value.get("schema_version") != 1 or value.get("kind") != "evaluation_coverage_validation":
        raise ValueError("Coverage-validation manifest kind differs")
    if value["simulation_count_per_scenario"] != 2000:
        raise ValueError("Coverage validation uses 2,000 synthetic data sets per scenario")
    if value["bootstrap_replications"] != BOOTSTRAP_REPLICATIONS:
        raise ValueError("Coverage validation uses the fixed bootstrap replication count")
    if value["quality_pair_target"] != PLANNED_QUALITY_PAIRS:
        raise ValueError("Coverage validation differs from the quality planning target")
    if value["quality_allowance"] != QUALITY_ALLOWANCE or value["cost_reduction_threshold"] != COST_REDUCTION_THRESHOLD:
        raise ValueError("Coverage validation differs from the policy thresholds")
    if value["near_zero_cost"] != 0.00000025:
        raise ValueError("Coverage validation differs from the fixed cost measurement unit")
    if value["conditions"] != list(CONDITIONS):
        raise ValueError("Coverage validation condition order differs")
    if value["resampling_methods"] != [
        "complete_repeat_round", "circular_moving_block_length_2"
    ]:
        raise ValueError("Coverage validation resampling methods differ")
    if len(value["scenarios"]) != 3:
        raise ValueError("Coverage validation needs the three fixed boundary scenarios")
    scenario_ids = [scenario["id"] for scenario in value["scenarios"]]
    if scenario_ids != ["quality_boundary", "cost_boundary", "both_boundaries"]:
        raise ValueError("Coverage validation boundary scenarios differ")
    for scenario in value["scenarios"]:
        if scenario["none_pass_probability"] != 0.80:
            raise ValueError("Synthetic none pass probability differs")
        if scenario["quality_difference_variances"] != [0.10, 0.32, 0.40]:
            raise ValueError("Synthetic quality difference variances differ")
        if scenario["time_copy_probability"] not in (0.0, 0.025, 0.05):
            raise ValueError("Synthetic time dependence differs")
        _joint_probabilities(
            scenario["none_pass_probability"],
            scenario["quality_difference"],
            scenario["quality_difference_variances"],
        )
    return value


def _joint_probabilities(none_probability: float, difference: float, variances: list[float]) -> list[dict]:
    compressed_probability = none_probability + difference
    if not 0 < none_probability < 1 or not 0 < compressed_probability < 1:
        raise ValueError("Synthetic pass probabilities must be inside zero and one")
    records = []
    lower = max(0.0, none_probability + compressed_probability - 1.0)
    upper = min(none_probability, compressed_probability)
    for variance in variances:
        both_pass = (compressed_probability + none_probability - variance - difference ** 2) / 2
        if not lower <= both_pass <= upper:
            raise ValueError("Synthetic variance has no valid paired Bernoulli distribution")
        records.append({
            "p_none": none_probability,
            "p_compressor": compressed_probability,
            "p_both_pass": both_pass,
            "p_compressor_given_none_pass": both_pass / none_probability,
            "p_compressor_given_none_fail": (compressed_probability - both_pass) / (1 - none_probability),
            "variance": variance,
        })
    return records


def _tail_multiplier(generator: np.random.Generator, shape: tuple[int, int], specification: dict) -> np.ndarray:
    sigma = specification["lognormal_sigma"]
    lognormal = np.exp(generator.normal(0.0, sigma, size=shape) - sigma ** 2 / 2)
    probability = specification["rare_multiplier_probability"]
    multiplier = specification["rare_multiplier"]
    rare = np.where(generator.random(shape) < probability, multiplier, 1.0)
    return lognormal * rare / ((1 - probability) + probability * multiplier)


def synthetic_evaluation(
    task_count: int,
    repetitions: int,
    scenario: dict,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    if repetitions != required_repetitions(task_count):
        raise ValueError("Synthetic validation repetition count differs from the fixed planning formula")
    generator = np.random.Generator(np.random.PCG64(seed))
    joint = _joint_probabilities(
        scenario["none_pass_probability"],
        scenario["quality_difference"],
        scenario["quality_difference_variances"],
    )
    quality = np.empty((repetitions, task_count, len(CONDITIONS)), dtype=np.float64)
    cost = np.empty_like(quality)
    task_scale = np.exp(generator.normal(0.0, 0.35, size=task_count))
    copy_probability = scenario["time_copy_probability"]
    for repetition in range(repetitions):
        if repetition and generator.random() < copy_probability:
            quality[repetition] = quality[repetition - 1]
            cost[repetition] = cost[repetition - 1]
            continue
        none = generator.random(task_count) < scenario["none_pass_probability"]
        quality[repetition, :, 0] = none
        for compressor_index, probabilities in enumerate(joint, start=1):
            conditional = np.where(
                none,
                probabilities["p_compressor_given_none_pass"],
                probabilities["p_compressor_given_none_fail"],
            )
            quality[repetition, :, compressor_index] = generator.random(task_count) < conditional
        noise = _tail_multiplier(
            generator, (task_count, len(CONDITIONS)), scenario["cost_tail"]
        )
        reductions = np.array([0.0, *([scenario["cost_reduction"]] * len(COMPRESSORS))])
        cost[repetition] = task_scale[:, None] * (1.0 - reductions[None, :]) * noise
    return quality, cost


def exact_binomial_upper_95(false_adoptions: int, simulations: int) -> float:
    if type(false_adoptions) is not int or type(simulations) is not int:
        raise ValueError("Binomial counts must be integers")
    if simulations < 1 or not 0 <= false_adoptions <= simulations:
        raise ValueError("Binomial counts are out of range")
    if false_adoptions == simulations:
        return 1.0

    def probability_at_most(probability: float) -> float:
        if probability <= 0:
            return 1.0
        if probability >= 1:
            return 0.0
        term = (1.0 - probability) ** simulations
        total = term
        odds = probability / (1.0 - probability)
        for successes in range(1, false_adoptions + 1):
            term *= (simulations - successes + 1) / successes * odds
            total += term
        return total

    low, high = 0.0, 1.0
    for _ in range(80):
        midpoint = (low + high) / 2
        if probability_at_most(midpoint) > 0.05:
            low = midpoint
        else:
            high = midpoint
    return high


def _one_simulation(arguments: tuple) -> dict:
    task_count, repetitions, scenario, simulation, manifest = arguments
    validation_seed = purpose_seed(
        manifest["independent_validation_seed"], f"{scenario['id']}:data:{simulation}"
    )
    quality, cost = synthetic_evaluation(task_count, repetitions, scenario, validation_seed)
    arrays = evaluation_arrays(
        quality, cost, tuple(f"synthetic-task-{index:03d}" for index in range(task_count))
    )
    decisions = {}
    for method in manifest["resampling_methods"]:
        bootstrap_seed = purpose_seed(
            manifest["independent_validation_seed"], f"{scenario['id']}:{method}:{simulation}"
        )
        result = evaluate_bootstrap(
            arrays,
            manifest["near_zero_cost"],
            replications=manifest["bootstrap_replications"],
            base_seed=bootstrap_seed,
            method=method,
            batch_size=manifest["bootstrap_batch_size"],
        )
        decisions[method] = any(
            result["compressors"][compressor]["decision"] == "adopt"
            for compressor in COMPRESSORS
        )
    return decisions


def _source_commit(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("Coverage validation requires one full lowercase source commit")
    return value


def run_validation(manifest: dict, task_count: int, workers: int, source_commit: str) -> dict:
    source_commit = _source_commit(source_commit)
    repetitions = required_repetitions(task_count)
    simulations = manifest["simulation_count_per_scenario"]
    started = time.monotonic()
    results = {}
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for scenario in manifest["scenarios"]:
            for simulation in range(simulations):
                arguments = (task_count, repetitions, scenario, simulation, manifest)
                futures[executor.submit(_one_simulation, arguments)] = scenario["id"]
        counts = {
            scenario["id"]: {method: 0 for method in manifest["resampling_methods"]}
            for scenario in manifest["scenarios"]
        }
        completed = {scenario["id"]: 0 for scenario in manifest["scenarios"]}
        for future in as_completed(futures):
            scenario_id = futures[future]
            decision = future.result()
            completed[scenario_id] += 1
            for method, false_adoption in decision.items():
                counts[scenario_id][method] += int(false_adoption)
    for scenario in manifest["scenarios"]:
        scenario_id = scenario["id"]
        methods = {}
        for method in manifest["resampling_methods"]:
            false_adoptions = counts[scenario_id][method]
            upper = exact_binomial_upper_95(false_adoptions, simulations)
            methods[method] = {
                "false_adoptions": false_adoptions,
                "simulations": simulations,
                "observed_rate": false_adoptions / simulations,
                "exact_binomial_one_sided_95_upper": upper,
                "entry_condition_met": upper <= 0.05,
            }
        results[scenario_id] = methods
    return {
        "schema_version": 1,
        "kind": "evaluation_coverage_validation_result",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": source_commit,
        "manifest_sha256": manifest["manifest_sha256"],
        "task_count": task_count,
        "repetitions": repetitions,
        "quality_pairs_per_comparison": task_count * repetitions,
        "logical_trials": len(CONDITIONS) * task_count * repetitions,
        "workers": workers,
        "elapsed_seconds": time.monotonic() - started,
        "scenarios": results,
        "entry_condition_met": all(
            method["entry_condition_met"]
            for scenario in results.values()
            for method in scenario.values()
        ),
        "claim_limit": "strict_operating_check_for_these_synthetic_scenarios_not_universal_coverage_proof",
    }


def throughput_check(manifest: dict, task_count: int, replications: int, source_commit: str) -> dict:
    source_commit = _source_commit(source_commit)
    repetitions = required_repetitions(task_count)
    scenario = manifest["scenarios"][0]
    quality, cost = synthetic_evaluation(
        task_count, repetitions, scenario,
        purpose_seed(manifest["independent_validation_seed"], "throughput-data"),
    )
    arrays = evaluation_arrays(
        quality, cost, tuple(f"synthetic-task-{index:03d}" for index in range(task_count))
    )
    started = time.monotonic()
    for method in manifest["resampling_methods"]:
        evaluate_bootstrap(
            arrays,
            manifest["near_zero_cost"],
            replications=replications,
            base_seed=purpose_seed(manifest["independent_validation_seed"], "throughput-" + method),
            method=method,
            batch_size=manifest["bootstrap_batch_size"],
        )
    elapsed = time.monotonic() - started
    full_projection = elapsed * manifest["bootstrap_replications"] / replications
    return {
        "kind": "local_computation_throughput_check_not_coverage_validation",
        "source_commit": source_commit,
        "task_count": task_count,
        "repetitions": repetitions,
        "logical_trials": len(CONDITIONS) * task_count * repetitions,
        "tested_bootstrap_replications_per_method": replications,
        "methods": len(manifest["resampling_methods"]),
        "elapsed_seconds": elapsed,
        "projected_seconds_per_synthetic_dataset_at_fixed_bootstrap_count": full_projection,
        "projection_excludes_process_pool_overhead": True,
    }


def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--task-count", type=int, required=True)
    parser.add_argument("--source-commit", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--throughput-check", type=int, metavar="BOOTSTRAP_REPLICATIONS")
    action.add_argument("--validate", type=Path, metavar="OUTPUT_JSON")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(arguments)
    manifest = load_validation_manifest(args.manifest)
    if args.throughput_check is not None:
        if args.throughput_check < 1:
            raise ValueError("Throughput bootstrap replication count must be positive")
        print(json.dumps(
            throughput_check(manifest, args.task_count, args.throughput_check, args.source_commit),
            sort_keys=True,
        ))
        return 0
    if not 1 <= args.workers <= 8:
        raise ValueError("Coverage validation uses one to eight local workers")
    result = run_validation(manifest, args.task_count, args.workers, args.source_commit)
    args.validate.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(args.validate),
        "entry_condition_met": result["entry_condition_met"],
        "elapsed_seconds": result["elapsed_seconds"],
    }))
    return 0 if result["entry_condition_met"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
