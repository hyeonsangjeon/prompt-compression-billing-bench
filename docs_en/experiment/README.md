# Experiment records

This file is the **complete experiment index** for the designs, decisions, and
measurement summaries from every study. Start the current first-study material
with the [preliminary compression comparison](01-preliminary-comparison/README.md).
Private source records and temporary artifacts are not included in the public
documentation.

## Records by study

| Study | Status | Starting document | Scope |
|---|---|---|---|
| First preliminary compression comparison | Completed preliminary observations | [First-study overview](01-preliminary-comparison/README.md) | 26 tasks × 4 conditions, one run per condition |
| Third benchmark candidate: SWE-Lancer | Evaluation complete, deferred | [Candidate evaluation](swe-lancer-candidate-evaluation-20260920.md) | One pre-execution gate for one fixed task; zero live traces |

Add a new experiment as `02-<experiment-name>/README.md` only after its execution
conditions and scope have been fixed. Do not create an empty directory or result
document in advance for a second experiment that has not started.

## First-study materials

1. Read the [first-study overview](01-preliminary-comparison/README.md) for the conditions, main results, and outcome-linked costs in one sequence.
2. Read the [26 task descriptions](01-preliminary-comparison/tasks.md) for each task, its public pass target, and its time, request, and cost observations.
3. Read the [task-level changed-condition matrix](01-preliminary-comparison/metrics.md) for the 23 conditions with changed text, the corresponding `none` rows, and the 55 compressed conditions with no text change.
4. Read the [plain-language results](01-preliminary-comparison/plain-language-results-20260917.md) for the findings and limits across 26 tasks and 104 conditions.
5. Read the [experiment-design review appendix](01-preliminary-comparison/experiment-briefing-20260919.md) for the decisions the evidence can support now and the remaining design gaps.
6. Read the [lossy and lossless compression guide](01-preliminary-comparison/lossless-lossy-compression-20260919.md) for the recoverability of the four conditions and the distinction between recoverability, quality, and cost.
7. Read the [visualization appendix](01-preliminary-comparison/visualization-guide-20260919.md) for the ten EDA figures and the preliminary-comparison charts separated by unit.
8. Read the [preliminary-comparison technical evidence](01-preliminary-comparison/preliminary-comparison-20260916.md) for condition-level values, run identifiers, and SHA-256 verification values.
9. Read the [outcome cost accounting](01-preliminary-comparison/outcome-cost-accounting-20260918.md) for passed, normally failed, and pre-judgment costs and for the portions that still cannot be allocated by outcome.

## Shared execution guidance

1. Read the [next paid-run safety policy](execution-safety-policy.md) for call, cost, time, request, and output limits and the classification of technically incomplete outcomes.
2. Read the [real-data connection guide](data-connection-guide-20260919.md) for the sequence from preparation outside the public repository through no-call checks, explicit execution, and result verification.
3. Read the [single-task YAML guide](../../README.md#try-it-in-five-minutes) for the default no-call check and the explicit live-execution boundary.

## Separate candidate evaluation

- [SWE-Lancer third-benchmark candidate evaluation](swe-lancer-candidate-evaluation-20260920.md): a deferred conclusion after checking the fixed task from the official README through its pre-execution gate. No worker, model, or provider started, so there is no live trace or grader result.

## Current status

| Work item | Current status | Sample and denominator | Evidence type |
| --- | --- | --- | --- |
| Existing baseline with no additional compression | Completed on 2026-09-14 UTC, but inconclusive under the preregistered rule | Five purpose-selected tasks × 20 repetitions = 100 native `trial` records | Measurement aggregated from private source records |
| Static compressor application | Input size and transformation samples checked for three compressors | 56 stored requests; 107 candidate occurrences and 27 unique inputs | Static measurement with no model call |
| Terminal-Bench 2.1 screening | Source records for 24 formal `attempt` records under the earlier limit policy are preserved: 12 cumulative quality outcomes, 11 completed technical exclusions, and one incomplete evidence record. Provider execution also ran and ended after the limits were removed. The 26 tasks with complete evidence feed the preliminary comparison below. Five long-tail runs ended before grading and are excluded from the primary analysis as quality-undetermined. | All 89 tasks; quality denominator of 12 among the 24 earlier formal `attempt` records; one diagnostic and five long-tail runs excluded from that denominator | Operationally closed; preregistered screening and repeated evaluation incomplete |
| Preliminary compression comparison | One completed `none`, squeez, Headroom, and LLMLingua-2 condition for each of 26 tasks; 40 passes and 64 `wrong_answer` outcomes | 26 tasks × 4 conditions = 104 condition observations, not 104 independent tasks | Preliminary observations from one first-run task, five tasks whose candidates were confirmed in preserved records, and 20 tasks that link a new `none` run to recovery evidence after the candidate pool was exhausted; representativeness across all 89 tasks, non-inferiority, and population savings are not established |
| Outcome cost accounting | Exact outcome-cost joins for 9 of the 104 completed conditions, with five long-tail quality-undetermined runs kept separate | Confirmed subtotal for 4 passes and 5 normal failures; 95 remaining conditions unallocated by outcome | Program-wide cost per pass and invoice reconciliation remain undetermined |
| Preregistered evaluation | Not run | Exact task set to be fixed after screening and `ceil(1,412/K)` repetitions | Not measured |

## Current decisions

- New model execution and experiment restarts stopped after the user's decision at `2026-09-17 23:59 KST`.
- The public primary analysis is fixed to the 26 tasks and 104 conditions for which all four conditions completed. The five long-tail runs that ended before grading remain quality-undetermined and are not part of the primary analysis.
- The preregistered repeated evaluation was not run.
- Any future paid execution requires separate approval and must apply every limit in a schema-version-4 ledger and the [safety policy](execution-safety-policy.md).

## Original preregistered plan and conditions for resuming

The quality and sampling rules below are the plan recorded at the time, not a
current execution plan. If a separate decision resumes the work, retain these
rules and also apply the current schema-version-4 safety boundary.

- Screen all 89 tasks from the fixed Terminal-Bench 2.1 revision without additional compression.
- Evaluate only the exact task-ID set that passes at least 18 of up to 20 valid outcomes per task.
- During evaluation, compare `none`, squeez `1.48.4`, Headroom `0.36.5`, and LLMLingua-2 `0.2.2` at the same insertion point.
- The allowed quality reduction is 5 percentage points, and the required directly attributable cost reduction is 10%. Both are preregistered policy thresholds.
- The quality-plan target is 1,412 pairs per comparison, with `ceil(1,412/K)` repetitions per task.
- Screening can start only after all preparation and preservation checks pass before a model call.
- A new paid run applies 60 provider HTTP attempts per attempt, 2,048 output tokens, 8,000,000 request bytes, 2,400 elapsed seconds, and preapproved per-attempt and whole-run cost limits and a UTC deadline. External provider constraints and every cost and time measurement are recorded separately.
- The original plan was to continue the comparison under the existing selection rule through `2026-09-17` and use the real outcomes available by then to set the first-study publication scope. That date was not a process termination timer.

## Document index

### Shared experiment records and contracts

- [Original first-study protocol](protocol.md): fixed record for the five purpose-selected tasks
- [Original baseline](baseline.md): results and limits for 100 native `trial` records
- [Static compressor measurements](compressors.md): size changes and transformation samples for 56 stored requests
- [Screening protocol](screening-protocol.md): 89-task inventory, 18/20 rule, failures and retries, and the nginx verifier
- [Evaluation protocol](evaluation-protocol.md): four conditions, quality and cost thresholds, repetition formula, and confidence interval
- [Reproducibility contract](reproducibility-contract.md): execution evidence, stop and resume behavior, verifier reruns, and Blob retrieval
- [Next paid-run safety policy](execution-safety-policy.md): call, cost, time, request, and output limits, progress signals, and quality-undetermined termination categories

### First-study materials

- [First-study overview](01-preliminary-comparison/README.md): shareable document that presents the conditions, main observations, and outcome-linked costs in one sequence
- [Descriptions of the 26 tasks](01-preliminary-comparison/tasks.md): plain descriptions, public pass targets, and time, request, and cost observations for each task
- [Task-level changed-condition matrix](01-preliminary-comparison/metrics.md): local tokens, verdicts, and costs for 23 changed conditions and their corresponding `none` rows, plus 55 compressed conditions with no change
- [Experiment-design review appendix](01-preliminary-comparison/experiment-briefing-20260919.md): measurement stages, current conclusions, and the ten experiment-design questions
- [Lossy and lossless compression guide](01-preliminary-comparison/lossless-lossy-compression-20260919.md): differences among transport compression, caching, and prompt shortening, and the actual recovery boundary of the four conditions
- [Visualization appendix](01-preliminary-comparison/visualization-guide-20260919.md): ten EDA figures, the measurement flow, and preliminary-comparison charts separated by unit
- [Plain-language results](01-preliminary-comparison/plain-language-results-20260917.md): findings and limits for 26 tasks and 104 conditions, written for a non-specialist reader
- [Outcome cost accounting](01-preliminary-comparison/outcome-cost-accounting-20260918.md): passed, normally failed, and pre-judgment costs, including confirmed subtotals and undetermined portions
- [Outcome cost accounting plan](01-preliminary-comparison/outcome-cost-accounting-plan-20260918.md): planned accounting for passes, normal post-judgment failures, pre-judgment costs, and calculated cost per passing condition
- [Preliminary-comparison technical evidence](01-preliminary-comparison/preliminary-comparison-20260916.md): condition-level quality, usage, transformations, cost ranges, run identifiers, and source hashes

### Shared application guidance and decision records

- [Real-data connection guide](data-connection-guide-20260919.md): procedure for preparing one real task outside the public repository, running a no-call check, executing, and verifying the result
- [Decision record](decisions.md): fixed decisions and their evidence

## Interpreting document status

The baseline, static application, and preliminary comparison are different
measurements. Static application made no model call and did not measure quality
or billed cost. The preliminary comparison has one run per condition and is not
the preregistered evaluation of all 89 tasks. Do not cite its observed cost
differences as a causal compression savings rate or an adoption decision.

Static candidates are an **identified candidate range, not a validated ceiling**.
