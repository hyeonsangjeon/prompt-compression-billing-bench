# Terminal-Bench 2.1 Evaluation-Task Screening Protocol

**Preregistration status:** These rules were fixed before the first screening call on 2026-09-15 UTC. Later runs stopped by technical defects do not change the rules; current execution status is recorded separately in the [documentation index](README.md). The decision at the time to remove limits is preserved as history, while future paid execution follows the [schema version 4 safety policy](execution-safety-policy.md).

## Screening Question

Screening determines which of the 89 tasks in the pinned Terminal-Bench 2.1 revision have the minimum quality evidence required for the compression comparison. A task is evaluation-eligible if it passes at least 18 of up to 20 valid quality results. This does not establish task or model stability from a small sample.

After screening, only the exact passing task-ID set becomes the evaluation population. Conclusions are not extended to rejected tasks or substituted similar tasks. Screening at 18/20 can favor easier tasks and higher pass rates, so this selection bias remains a limitation of the evaluation conclusion.

## Population and Fixed Conditions

| Item | Value | Status |
| --- | --- | --- |
| Benchmark | Terminal-Bench 2.1, 89 tasks | Fixed |
| Revision | `7131e4375048a0e408a8fb404b5f499d726b695b` | Fixed |
| Screening condition | `none`, with no additional compression | Fixed |
| Model | `gpt-5.4`; record the provider-returned revision for each request | Fixed; checked at execution |
| Request settings | temperature `0`, reasoning effort `none`; output limit 2,048 tokens | Settings record, not a guarantee of determinism |
| Runner | Harbor `0.22.0`, instrumented Terminus 2 | Fixed |
| Concurrency | 8 | Fixed |
| Provider constraints | Record provider throughput limits and service errors separately from schema version 4 safety limits | Rechecked before execution |
| Repetitions | Up to 20 valid quality results per task | Fixed |
| Grading | Benchmark verifiers and approved nginx correction | Hash-pinned |
| State-replay bundle | Revision 2; changed paths retained together and mount order fixed | Fixed |
| Local token calculation | tiktoken `0.14.0`, `o200k_base` | Recorded separately from billed tokens |

DeepSWE and protection-bypass tests are excluded from this screening matrix. Screening results are not reused as a concurrent control for evaluation. Evaluation reruns `none` and the three compression conditions within each task and repetition.

## List Fixed Before Results Are Viewed

Before execution, create one list containing the following for all 89 tasks and record its SHA-256 in the ledger:

- Task ID and type classification
- SHA-256 of the instruction, task configuration, verifier, and direct dependency files
- `linux/amd64` container-image digest
- Applied verifier revision and SHA-256 before and after any correction
- Executability and reason for exclusion

If a task cannot run, record the exclusion reason and repin the list hash before viewing model results. Do not replace a task after results are seen, even with another task of the same type.

## Evaluation-Eligibility Decision

| Item | Rule |
| --- | --- |
| Valid result | Quality result with complete evidence for provider call, agent execution, verifier, instrumentation, and retention |
| Pass | Native reward `1` agrees with structured test results |
| Quality failure | `wrong_answer` or `wrong_format`; either counts as one failure |
| Evaluation-eligible | At least 18 passes among 20 valid results |
| Early stop | Stop scheduling new executions once the third valid quality failure is confirmed |
| Failure location, type, and test ID | Record for diagnosis; do not use as an automatic exclusion criterion |

At 18/20, the minimum pass count in each half of 10 is automatically 8. Do not add a separate requirement of at least 8 passes per half. Instead, record pass counts for each half, their difference, failure order, longest failure run, and cumulative pass rate. These diagnose temporal change and do not remove tasks.

For a task with exactly 18/20, if the two failure positions are uniformly distributed over 20 positions, the proportion with both failures in the same half is `2×C(10,2)÷C(20,2)=90/190=47.37%`. Excluding tasks because both failures occur in one half would treat tasks with the same pass count differently based only on position. The 47.37% value is a combinatorial calculation, not a measurement of temporal change.

## Failure Classification and One Preparation Retry

A `trial` is one repetition of one task; an `attempt` is an execution that actually starts within it. Exactly one retry is allowed only when the same preparation fails before any provider call.

| Classification | Quality denominator | Retry | Task handling |
| --- | --- | --- | --- |
| `image_error` | Excluded | Once with the same artifact | Ineligible after a second failure |
| `setup_error` | Excluded | Once with the same artifact | Ineligible after a second failure |
| `provider_error` or `network_error` | Excluded | At most 3 total attempts for transient HTTP errors | Ineligible after exhaustion |
| `timeout` | Excluded | None | Ineligible only with evidence of actual process termination or a benchmark-internal limit |
| `verifier_crash` | Excluded | None | Ineligible |
| `evidence_missing` or `replay_mismatch` | Excluded | None | Ineligible; review whether to stop the run |
| `budget_stopped` or `censored` | Excluded | None | Technical stop with unknown quality; not counted as a wrong answer |
| `wrong_answer` or `wrong_format` | Included | None | Quality failure |
| `pass` | Included | None | Pass |

A preparation retry uses the same immutable artifact and hash as the first attempt. It starts with a new attempt ID in a fresh container and workspace rather than reusing the failed ones. A required artifact or setting change is a new revision, not a retry, and stops the run.

Without any provider call, even an incidental verifier pass is not a valid quality result. The ledger retains both attempts' times, costs, errors, and artifact hashes. Quality enters the denominator once per trial, while costs include every attempt that actually started.

Future paid runs enforce 60 provider HTTP attempts, 2,048 output tokens, 8,000,000 request bytes, 2,400 seconds elapsed, and a 300-second provider HTTP wait per attempt, together with preapproved per-attempt and full-run calculated API cost limits and a UTC deadline. Execution stops before external transmission if fewer than 3 distinct progress signals appear in the latest 8 logical requests. Harbor's internal stage timers remain disabled so they do not truncate evidence differently across stages, while the outer supervisor enforces attempt elapsed time and the full deadline. Provider context length, throughput, and policy refusals are recorded as separate external constraints.

If the provider explicitly rejects a request before first grading, reproducing it does not require sending the same task again. A completed technical exclusion must preserve the raw error and HTTP status, terminal stage, raw material that remained at the time, source commit, ledger, task-image digest, remote Blob hash, confirmed cost, and unresolved-cost status. Unexecuted initial grading, restore, and regrading times are recorded as not applicable with a reason, not as `0`. Unexplained missing evidence or a state-restore mismatch is not converted to a completed technical exclusion and stops further scheduling. Unresolved cost is not changed to zero; it enters limit calculations as conservative exposure. A historical request with neither usage nor a maximum-exposure estimate blocks paid resumption.

If, in a pre-fix run, one model-issued command explicitly used `exit` to end the terminal session and the next command in the same response was not delivered before first grading, compare the raw RuntimeError with per-command send-start, accepted, and rejected records. Only an existing result with the accepted `exit`, exactly one subsequent command rejected because the tmux session ended, a completed state save, remote Blob hash, and cost may be linked as a technical exclusion. This does not retrospectively turn a pre-fix result into a quality result. Post-fix execution treats session termination as the end of the agent loop and grades the current workspace; only results with complete save, restore, regrading, and remote hash enter the quality denominator.

Do not run the same task concurrently twice. If an execution began before the third quality failure, preserve it through completion and record its actual result, but do not reverse a confirmed ineligibility decision. Unstarted plans remain `cancelled_by_futility` and are excluded from quality and cost denominators.

After a source-commit change, do not rewrite the interrupted state database's SHA or state to resume automatically. A new execution ledger links the old ledger read-only. Link only evidence-complete results unaffected by historical and current 60-call and 2,048-output-token boundaries, once, to a new plan for the same task and repetition; do not reschedule a linked plan. Count quality once per trial and retain prior attempts and diagnostic costs in cumulative cost records. Preserve prior execution cost in cumulative reporting, but apply the new schema version 4 run's limits only once to confirmed and unresolved exposure from attempts newly started or resumed in that run.

## Verifier Validation

For every verifier, first test without a model call that it distinguishes a correct answer, an obvious wrong answer, a format error, and a technical error. Rerun the verifier once against the same retained state. A quality result is valid only if per-test results, exit code, and reward match.

### Corrected `nginx-request-logging` Verifier

The task requires the user-agent variable in the log but does not require only the `$http_user_agent` notation. Nginx `1.22.1` interprets `$http_user_agent` and `${http_user_agent}` as the same variable. The original verifier searched only for the literal `$http_user_agent` and falsely rejected the equivalent braced syntax.

`nginx-request-logging-verifier-v2` accepts `$name` and `${name}` for the four required variables without changing other checks or thresholds.

| Item | Value | Evidence status |
| --- | --- | --- |
| Original `tests/test_outputs.py` SHA-256 | `045cc716c14efde3b0dcff5fc7c85ec5d18bfc6ce66f8b40a418fa2a3a4acda0` | Pinned original |
| Corrected SHA-256 | `20812107bc3bfc541728a2d10e3da0552e907d949e1347a03d33aa26954f8902` | Pinned correction |
| Validation input using `$http_user_agent` | Pass | One model-free case |
| Validation input using `${http_user_agent}` | Pass | One model-free case |
| Incorrect `$http_referer` validation input | Fail | One model-free case |
| Corrected-module checks | 6/6 pass | Static check on 2026-09-14 UTC |

## Effect on the Existing Baseline

The two nginx failures in the existing 20-repetition baseline used `${http_user_agent}` and failed only this string check. Applying the corrected judgment to preserved traces and original verifier results calculates nginx at 20/20, but this is a static counterfactual calculation rather than an actual workspace replay. It does not replace the original 18/20 measurement.

## Time and Stopping Conditions

Across the prior 100 native trials, observed individual durations were P50 76.145 seconds and P90 93.559 seconds. Using the ratio 1.4345 between the actual interval and `sum of individual durations ÷ 8`, the 1,780 planned executions without early stopping or preparation retries project to 6.7662 hours from the P50 input and 8.3136 hours from the P90 input. This transfers five-task source data to 89 tasks; it is not an observed P50 or P90 for total screening time or an upper bound.

The projection excludes preparation-retry time, initial preparation of 89 images, long setup for unfamiliar tasks, approval waits, and final Blob verification. Preparation-retry P50 and P90 have not been measured, so the worst case is not filled with invented numbers. Time saved by early stopping is also not assumed in advance.

The reporting target at the time was `2026-09-16 23:59 KST`. It was a historical operating target, not a timer that terminated task processes. Future schema version 4 execution terminates at an approved `run_deadline_utc` independent of the reporting target.

Stop screening and record the cause and smallest correction if:

- The pinned source commit, list hash, image digest, or verifier SHA differs
- The provider-reported model revision differs from the ledger
- Concurrency or deployment limits cannot be maintained
- Required evidence or the same-state verifier rerun is incomplete
- Local evidence cannot be hash-verified against Blob
- Technical failure is established by actual process termination, an explicit error, or lack of task progress
- Any schema version 4 call, cost, time, request, output, or progress-signal limit is reached

Schedule risk itself is not a quality failure. Reaching the approved deadline or a cost limit ends as technically incomplete. Unconfirmed cost is not converted to zero and remains conservative exposure for deciding on the next send.

Do not lower pass rate, quality tolerance, cost-savings threshold, or the repetition formula to fit the schedule.

## Screening Entry Criteria

- Harbor `0.22.0` imports in an isolated Python environment and pinned dependency checks pass.
- All local tests with the tokenizer table fixed and the native-only tests pass.
- The 89-task list and image digests are hash-pinned.
- Install-only checks for all 89 tasks and actual Docker state save-and-restore checks pass.
- Blob writes and verification reads, missing-cost handling, local retention, and resume paths are verified.
- The execution ledger records source commit, schema version 4 safety limits, pricing time, deployment limits, UTC deadline, and delegated execution authority.
- The first provider call is allowed only after the input bundle is uploaded to Blob and its remote SHA-256 is verified.

Record that every criterion passed, together with the started job's PID, log location, and result location.
