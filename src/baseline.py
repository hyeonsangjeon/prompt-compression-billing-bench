"""Descriptive, pre-baseline stopping proposal; never a test of equivalence."""

from collections import Counter
import statistics


RULE = "equal_half_support_v1_proposal"


def baseline_summary(repetitions: list[dict[str, int]], tasks: list[str]) -> dict:
    if len(tasks) != 5 or len(set(tasks)) != 5:
        raise ValueError("One repetition must contain exactly the five fixed tasks")
    if not 1 <= len(repetitions) <= 20:
        raise ValueError("Supply 1 through 20 complete baseline repetitions")
    for repetition in repetitions:
        if set(repetition) != set(tasks) or any(type(value) is not int or value not in (0, 1) for value in repetition.values()):
            raise ValueError("Every repetition needs five valid binary native rewards; missing trials are not zero")
    counts = [sum(row.values()) for row in repetitions]
    task_counts = {task: sum(row[task] for row in repetitions) for task in tasks}
    result = {
        "kind": "calculated", "rule": RULE, "rule_status": "proposal_not_approved",
        "unit": "passed_tasks_per_five_task_native_repetition", "repetitions": len(counts),
        "native_trials": len(counts) * 5, "suite_pass_counts": counts,
        "range_min": min(counts), "range_max": max(counts), "range_width": max(counts) - min(counts),
        "mean_pass_count": statistics.mean(counts),
        "sample_standard_deviation": statistics.stdev(counts) if len(counts) > 1 else None,
        "task_pass_counts": task_counts,
        "floor_tasks": [task for task, count in task_counts.items() if count == 0],
        "ceiling_tasks": [task for task, count in task_counts.items() if count == len(counts)],
        "status": "collect_to_10" if len(counts) < 10 else "collect_to_20",
        "statistical_stability_proven": False, "equivalence_proven": False,
    }
    if len(counts) not in (10, 20):
        return result
    midpoint = len(counts) // 2
    first, second = counts[:midpoint], counts[midpoint:]
    suite_support_equal = (min(first), max(first)) == (min(second), max(second))
    task_support_equal = all(
        {row[task] for row in repetitions[:midpoint]} == {row[task] for row in repetitions[midpoint:]}
        for task in tasks
    )
    result["half_checks"] = {
        "repetitions_per_half": midpoint, "suite_range_equal": suite_support_equal,
        "task_support_equal": task_support_equal,
        "first_counts": dict(Counter(first)), "second_counts": dict(Counter(second)),
        "mean_difference": statistics.mean(second) - statistics.mean(first),
    }
    stabilized = suite_support_equal and task_support_equal
    result["status"] = (
        "observed_range_stabilized" if stabilized
        else "extend_to_total_20" if len(counts) == 10 else "stop_inconclusive"
    )
    result["comparison_informative"] = stabilized and result["range_width"] < 5 and len(result["floor_tasks"]) < 5
    return result


def compare_quality(baseline: list[dict[str, int]], intervention: list[dict[str, int]],
                    tasks: list[str], changed_occurrences: int) -> dict:
    reference = baseline_summary(baseline, tasks)
    observed = baseline_summary(intervention, tasks)
    if len(baseline) != len(intervention) or len(baseline) not in (10, 20):
        raise ValueError("Compare equal complete arms of 10 or 20 five-task repetitions")
    if type(changed_occurrences) is not int or changed_occurrences < 0:
        raise ValueError("Actual intervention count must be recorded")
    floors = reference["floor_tasks"]
    lower_trials = [index + 1 for index, count in enumerate(observed["suite_pass_counts"]) if count < reference["range_min"]]
    new_task_failures = [task for task in reference["ceiling_tasks"] if observed["task_pass_counts"][task] < len(intervention)]
    if reference["status"] != "observed_range_stabilized" or not reference["comparison_informative"]:
        decision = "inconclusive_baseline"
    elif changed_occurrences == 0:
        decision = "no_intervention_not_a_safety_test"
    elif lower_trials or new_task_failures:
        decision = "below_observed_baseline_range"
    elif observed["range_max"] > reference["range_max"]:
        decision = "above_observed_baseline_range_requires_review"
    else:
        decision = "within_observed_range_with_floor_limits" if floors else "within_observed_range"
    return {
        "kind": "calculated_decision", "rule": RULE, "rule_status": "proposal_not_approved",
        "decision": decision, "baseline_range": [reference["range_min"], reference["range_max"]],
        "unit": reference["unit"], "below_range_repetitions": lower_trials,
        "previously_always_passing_tasks_now_failed": new_task_failures,
        "floor_tasks_without_degradation_detection": floors,
        "statistical_equivalence_proven": False,
        "truncation_causality": "not_established_by_scores_or_reexecution_counts_alone",
    }
