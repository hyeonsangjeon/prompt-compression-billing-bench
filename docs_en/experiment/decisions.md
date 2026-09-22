# Decision Log

This document tracks the basis and status of design decisions. Measurements remain in the
[baseline](baseline.md) and [static compressor measurements](compressors.md).

## Design Fixed on 2026-09-15

| Decision | Fixed rule | Reason and limitation |
| --- | --- | --- |
| Conclusion scope | Conditional only on the exact screened task-ID set, `gpt-5.4`, and the fixed price table | No sampling frame for similar tasks, so generalization beyond the task set is not established |
| Evaluation eligibility | At least 18 passes among 20 valid results | Do not translate into a smaller sample with the same percentage |
| Temporal order | First-half and second-half differences and failure position are diagnostic only | Exclusion by position can create selection bias |
| Failure kinds | Count both `wrong_answer` and `wrong_format` as quality failures | Record classification and test ID, but do not use them as automatic exclusion rules |
| Preparation retry | Exactly one retry with the same artifact only for the same preparation error before a provider call | Use a fresh container and workspace; do not retry quality failures |
| Quality threshold | Lower bound versus `none` must exceed -5 percentage points | Preregistered policy value for this study, not customer-agreed |
| Cost threshold | Lower bound on directly attributable cost savings must exceed 10% | Preregistered policy value; not lowered to fit the schedule |
| Repetition count | `R(K)=ceil(1,412/K)` | Planning stress assumption using quality-difference variance 0.40; does not guarantee cost power |
| Adoption decision | Both one-sided 98.333% quality and cost lower bounds must pass for each compressor | `0.05/3` for three compressors; one failed bound does not establish degradation |
| Resampling | Jointly sample complete repetitions containing all `K` tasks and four conditions | Preserves pairing and shared `none`; tasks are not resampled |
| Temporal correlation | Length-2 circular moving-block bootstrap for sensitivity | Do not claim robust adoption when primary and sensitivity decisions differ |
| Randomness and calculation | Base seed `20260915`, 50,000 bootstrap draws, NumPy `PCG64` | Record purpose-specific child seeds and quantile method in the manifest |
| Synthetic-data check | 2,000 datasets per boundary scenario; exact one-sided 95% binomial upper bound at most 0.05 | Operating condition for specified scenarios, not a universal coverage proof |
| Missing cost | No zero substitution or row deletion; required missing and near-zero denominators are indeterminate | Separates actual zero spend from missing instrumentation |

After screening, only the number `K` of evaluation-eligible tasks is newly inserted into
the formula. Evaluation is impossible when `K=0`. Do not change tasks, repetition count,
thresholds, seed, confidence interval, or cost contract after viewing evaluation results.

## Consequences of These Choices

Failure position and kind became diagnostic records rather than task-removal criteria. A
task with 18/20 is not removed solely because of when or how it failed. Evaluation instead
reports per-condition failure classifications and test IDs to describe whether failure
patterns change after compression.

A preparation error before a provider call can recover once, but not by reusing the same
failed environment. Because actual attempt count and cost may increase, they remain
separate from planned trial count.

Repetition count was set from the quality tolerance. If a wide cost interval leaves the
10% savings threshold indeterminate, repetitions are not added after results are seen.
This accepts the risk of an indeterminate cost conclusion in exchange for preventing
post hoc sample expansion.

## nginx Verifier Correction

The original Terminal-Bench 2.1 verifier accepted `$http_user_agent` but rejected the
equivalent Nginx form `${http_user_agent}`. Screening uses a minimal correction that
recognizes both syntaxes for the four required variables.

- Original SHA-256: `045cc716c14efde3b0dcff5fc7c85ec5d18bfc6ce66f8b40a418fa2a3a4acda0`
- Corrected SHA-256: `20812107bc3bfc541728a2d10e3da0552e907d949e1347a03d33aa26954f8902`
- Validation inputs for source syntax, equivalent syntax, and an obvious wrong answer: 3/3 as expected
- Corrected-module checks: 6/6 pass

The existing nginx baseline value of 18/20 remains unchanged. The corrected 20/20
calculated from preserved traces is a static counterfactual, not an actual workspace
replay. The correction applies only to new screening.

## Correction to Headroom Measurement Scope

No location controls were observed in the measured Headroom `0.36.5` paths-only
configuration. Headroom `0.37.0`'s `coding` profile, however, includes tool-level
exclusions, file-read protection, analytical-context protection, and tree-sitter
AST-based selective compression. Its size, preservation, and quality effects remain
unmeasured.

Therefore, the conclusion “none of the eight reviewed tools distinguishes file types or
spans internally” is not used. The repository's measured 0.1976% refers only to grouping
common path prefixes under Headroom `0.36.5` paths-only.

## Tool-Name Protection and File Reads Through Bash

Excluding only by tool name can miss the same file read when it occurs through `bash`
rather than `Read`. A public issue record includes cases in which lossy compression was
applied to `view` and bash `nl` or `sed` output and the agent reread the file. A
separate external observation reported 39% compression of Python source read through
bash. Its unit and sample denominator were absent from the supplied material, and it is
not a repository measurement.

The harness therefore distinguishes input-generation path and content to protect code,
instructions, and assistant history. This experiment does not claim to validate
Headroom's internal judgment on the product's behalf.

## Excluded From This Scope

- Headroom `0.37.0` `coding` profile
- Expansion to structured output and file-read locations
- DeepSWE
- Separate protection-bypass audit
- Compression-intensity variation

External `r0.95`, `r0.9`, and `r0.5` results for compression intensity are cited only
after verifying their source model, tasks, repetitions, and denominator. This evaluation
does not add an intensity axis to tool, location, task, and quality variation.

## Decision to Proceed With Execution

On 2026-09-15, the user delegated coordination of design choices and staged execution.
That delegation did not remove pre-call entry criteria. Screening begins only after
isolated environment, full local tests, install-only checks for 89 tasks, actual Docker
state replay, cost instrumentation, and Blob retrieval are verified.

After screening, compare `K`, measured throughput, cost, and the synthetic-data error-rate
check before deciding whether evaluation may begin. If it does not fit the deadline, record
the smallest feasible design revision rather than lowering policy thresholds or the
repetition formula.

## Technical Screening Stops

**Observation:** Three runs started on 2026-09-15 UTC recorded 54, 115, and 67 successful
provider responses but produced 0 valid quality results. The first stopped because
screening changed Docker paths took too long. In the second, a response-delivery
connection closure for one task stopped the full run, and Docker rejected relative
symlink archives in verifier reruns for two tasks. The third completed all 8 started
tasks without 429 responses or response-delivery closures, but 8/8 were excluded from the
quality denominator for state-replay mismatch. For 6/8, first and second judgments both
ran inside Harbor's 900-second judgment limit, cancelling the second; 2/8 had different
restored-state hashes. Calculated provider costs were 1.322095 USD, 2.8807495 USD, and
1.5341365 USD, not invoice-reconciled values.

**Treatment:** The three runs are excluded from screening pass-rate numerator and
denominator. Connection closure remains a technical failure of the affected task, while a
correction lets other task requests continue. Changed paths inside a container are
preserved and restored in one NUL-delimited tar file rather than copied path by path.
Mounts are ordered by target path. The second judgment runs in the same container after
the first judgment's 900-second limit has ended and before container removal.

**Validation:** In the latest correction, 237 tests with the tokenizer table pinned
passed; 2 optional integration tests were skipped because execution-environment conditions
were unavailable. The Harbor-only group passed 57 tests, with 1 actual Docker test skipped
locally. In a disposable VM container, added, modified, and deleted paths, relative
symlinks, and mounted files restored to the same state hash. A separate disposable
container preserved 12,040 changed paths in one tar file; the state hash matched after
2.132662891 seconds to preserve and 6.850701672 seconds to restore and rehash. This
validation made 0 model calls.

**Limitation:** This validates the corrected file-state preservation path, not a quality
result from new screening. Running-process memory is not reconstructed from an archive.
Rerun is allowed only if process lists before and after judgment and nonarchivable socket
lists match, but those comparisons do not establish byte equality of process memory. The
costs and raw sources from the three stopped runs remain private evidence; a new run uses
a new source commit and execution manifest.

**Cost stopping condition:** Calculated provider cost across the three technical stops was
5.736981 USD. To retain the 300 USD full-screening provider limit, the new execution
ledger's limit was 294.263019 USD. Both are provider usage multiplied by a fixed price
table, not invoice reconciliation.

## Pre-Execution Validation on 2026-09-15

- **Measurement:** Before first screening, 235 static tests with a pinned tokenizer table passed; 2 optional integration tests were skipped because local execution conditions were absent. Historical Harbor-only and actual Docker state-preservation and restoration checks remain separate from the post-correction validation above.
- **Measurement:** VM install-only checks recorded results for all 89 tasks. On the first run, 88/89 ended without exceptions, while 1/89, `pytorch-model-recovery`, ended at Harbor's internal 120-second installation limit. There were 0 model calls.
- **Measurement:** Rechecking the same task on a warm-cache VM without changing the ledger's 600-second setup limit completed without exception after 1.34 seconds of environment setup and 9.62 seconds of agent setup.
- **Classification judgment:** The 89 failures in the initial record were not actual failure count. An aggregation bug added 88 failures by comparing Harbor names with a `terminal-bench/` prefix directly against inventory task IDs. It was corrected by mapping prefixed names one-to-one to inventory IDs.
- **Measurement:** The 65,935,360-byte actual install-only artifact was uploaded to Blob, SHA-256-verified by remote GET, and downloaded again in a separate collection environment. The VM and collector SHA-256 matched at `f38b3df36e4a25353293825d1900e8ccbf22e8d778960eae49b20115d8a0236f`.
- **Limitation:** This verifies executability on the current warm-cache VM. It does not guarantee that first installation on a fresh VM finishes within 120 seconds; the screening rule allowing one preparation retry before a provider call remains.

## Relationship to the Earlier Experiment

The existing purposively selected five-task baseline ended inconclusively after 100 native
trials. It also did not satisfy the final-workspace replay contract and is not reused for
new screening. The [original preliminary protocol](protocol.md) and [baseline record](baseline.md)
remain the original judgments from that execution.

## Handling the Provider-Call Limit

**Observation:** Formal screening for `gpt2-codegolf` ended before first grading when its
fourth provider request returned HTTP 400 `content_filter`. A new single-task diagnostic
excluded from the formal denominator received 60 HTTP 200 provider responses, including
2 with `finish_reason=length`. Terminus 2 used corrective calls after output-length
limits and skipped the verifier when the 61st call was blocked locally. The two
executions had different requests and task histories, so they do not establish whether
the HTTP 400 was reproducible under equal input.

**Treatment at the time:** The system kept only the 60 provider-call limit per task and
`max_turns=60`, without changing the time or cost policy then in force. At 60 calls it
ended agent execution without another provider call and graded the current workspace.
Only results with complete save, restore, regrading, and remote-hash verification entered
the quality denominator. This is historical, predating the schema version 4 decision
below, and is not the current operating rule. The two pre-fix `gpt2-codegolf` executions
remain technical diagnostics rather than retrospective quality results.

**Limitation:** This correction fixes an execution path in which Terminus 2 omitted the
verifier after reaching the call limit. It does not fix why the model failed to interrupt
a long-running terminal command or an HTTP 400 policy refusal. Full single-task path
validation runs separately on the corrected source commit.

## 60-Call Boundary Diagnostic and Read-Only Continuation

**Observation:** The latest formal run on 2026-09-15 UTC completed 16 attempts. Ten were
quality results: 5 `pass` and 5 `wrong_answer`. The other six were technical results
excluded from the quality denominator: 5 `timeout` and 1 `provider_error`. The formal
`gpt2-codegolf` provider error ended before first grading after the fourth-request HTTP
400 refusal. Its raw error and preserved material remain unchanged.

**Measurement:** A new single-task `gpt2-codegolf` diagnostic outside the formal
denominator received 60 provider responses, including 2 with `finish_reason=length`.
There was no 61st external call. After first grading of the current workspace, state save
took 1.09470895 seconds, restoration 8.157927154 seconds, regrading 21.35600655 seconds,
and Blob upload and remote verification 2.236660551 seconds. First grading and regrading
both returned `wrong_answer`, and remote Blob hash verification passed. The diagnostic
is excluded from the numerator and denominator of formal 89-task screening.

**Validation:** A model-free integration test connecting actual Harbor `0.22.0`, LiteLLM
`1.100.0`, and a local fake upstream forwarded exactly 60 external calls including the
corrective call after the first `length` response. The 61st call did not reach upstream,
and execution entered the verifier-result collection path. HTTP 400 and other exceptions
were not converted into 60-call-limit exceptions. This validation does not replace save,
restore, regrading, and evidence from the paid single-task diagnostic.

**Treatment:** The formal HTTP 400 result remains a technical exclusion and is not replaced
by the diagnostic's `wrong_answer`. An explicit provider refusal before first grading
becomes a completed technical exclusion only when raw error, stage-level state, available
source, remote hash, and confirmed cost or conservative reservation are complete. Times
for unexecuted grading stages remain not applicable with reasons, not `0`.

**Continuation:** A changed source commit prevents automatic resume, so the prior 16
records are linked read-only. Only evidence-complete results that did not cross the
60-call change boundary are applied once to the same task and repetition. Completed plans
are not rescheduled. Quality is counted once per trial, while every attempt and diagnostic
cost remains cumulative.

**Cost:** Before continuation, the provider cost record separates 17.41161 USD confirmed
from 0.074985 USD unresolved conservative reservation. The confirmed value adds this
single diagnostic's 0.6759435 USD to the prior 16.7356665 USD. Subtracting both from the
300 USD provider limit leaves 282.513405 USD. These values are provider usage multiplied
by a fixed price table, not invoice reconciliation. Prior cost remains in cumulative
reporting but is not subtracted from the new balance twice.

**Limitation:** The 16 formal results alone do not establish evaluation eligibility for
any task. No result from a later batch is claimed before read-only linkage checks and
complete evidence for the first new batch finish.

## First Read-Only Continuation Batch

**Observation:** On 2026-09-15 UTC, the process linked 16 prior formal attempts read-only
once and ran 8 previously unstarted tasks at concurrency 8. Two new tasks produced valid
quality results, both `wrong_answer`. One completed as `provider_error`, four as
`timeout`, all completed technical exclusions. The remaining `make-doom-for-mips`
ended before first grading and remained evidence-incomplete under checks at the time.
The cumulative formal record therefore contains 24 attempts, a quality denominator of 12,
11 completed technical exclusions, and 1 evidence-incomplete record. It scheduled 0 next
batch tasks.

**Cause review:** The 19th model-issued command for `make-doom-for-mips` ran
`exit $rc` after building, and the terminal accepted it. The 20th command in the same
model response was sent to the ended tmux session and rejected with a `no server running`
RuntimeError. Task-process wall time was 259.66233909 seconds, state save
5.996326086 seconds, and Blob upload and remote verification 5.326878152 seconds. First
grading, restoration, and regrading did not run, so their times are not applicable. The
task-process wall time includes preparation and agent execution; it is not isolated model
work time.

**Treatment:** Do not change the pre-fix raw RuntimeError, command trace, native-result and
trace hashes, state save, remote Blob hash, or cost. When all evidence agrees, link the
existing result as a technical exclusion without making it a quality result. Later runs
treat terminal-session termination as the end of the agent loop and pass the current
workspace to the verifier. Do not apply this handling when the session remains alive or
the raw RuntimeError differs.

**Cost:** Before this continuation, confirmed provider cost was 17.41161 USD and
unresolved conservative reservation was 0.074985 USD. The eight new executions added
3.9968745 USD confirmed and 0.302345 USD reserved. Cumulative confirmed cost is
21.4084845 USD, cumulative conservative reservation is 0.37733 USD, and 278.2141855 USD
remains under the 300 USD limit. These are calculated from provider usage and fixed
prices, not invoice-reconciled values.

**Limitation:** Completed technical exclusions are neither quality passes nor quality
failures. Four `timeout` and one `provider_error` make the affected tasks ineligible
without becoming compression-comparison results. The terminal-exit correction passed
local regression checks and comparison against preserved source. Read-only linkage,
duplicate, and cost reconciliation repeat before a new continuation under the same final
source commit.

## Removal of User-Defined Execution Limits: Historical Decision on 2026-09-15

**Decision at the time:** After 2026-09-15 22:40 KST, screening and evaluation did not
apply the harness-defined 300 USD stop, balance-subtraction block, 2 USD diagnostic limit,
60 provider calls per task, `max_turns=60`, 2,048-token maximum output, request-byte
limit, agent, setup, verifier, or task-execution time limits, full-run duration, or
deadline stop. This paragraph is a historical record of conditions at the time. Future
paid execution follows schema version 4 below; this decision is not reused as the current
operating rule.

**Implementation validation at the time:** The execution ledger represented the
unlimited state as explicit policy values rather than very large numbers. Harbor
`0.22.0` phase-duration calculations returned `None` through the execution entry
point, and Terminus 2 did not receive `max_turns` or `max_completion_tokens`. Omitting
`max_turns` invokes Terminus 2's internal default of 1,000,000, so it was not called
unlimited. Provider throughput limits and service errors, context length, request size,
and policy refusal remained external product constraints.

**Model-free validation:** A test connecting actual Harbor `0.22.0`, LiteLLM
`1.100.0`, and a local fake upstream forwarded 62 calls, including the corrective call
after the first `finish_reason=length` response. Calls after the 60th were forwarded,
`max_completion_tokens` was absent from every request, and the run entered verifier
result collection. Harbor's agent, agent-setup, environment-setup, and verifier limit
calculations were all `None`, and the native supervisor had no deadline. This was not
actual provider execution or a new quality result.

**Continuation:** Do not overwrite the 24 existing formal attempts or raw single-task
diagnostic. A historical result that reached or may have been affected by a call, output,
or time boundary is not linked as a quality result under the new policy; only the required
task and repetition reruns under a new execution ID. Evidence-complete unaffected results
are linked read-only once. Confirmed provider cost of 21.4084845 USD and the then-unresolved
reservation of 0.37733 USD retain their observation lineage as confirmed and old-policy
unresolved estimates, respectively, and do not block new execution.

**Schedule:** At the time of this decision, the operating target was to obtain actual
comparison values and evidence by `2026-09-16 23:59 KST`. This was not a process
termination timer and replaced the earlier `2026-09-17 09:00 KST` execution-end target
and `2026-09-17 21:00 KST` reporting target. Actual provider screening under the new
unlimited policy had not started when the decision was recorded.

## Safety Limits for Future Paid Execution: Schema Version 4

**Decision:** Future paid provider execution follows the
[stopping and cost-safety policy](execution-safety-policy.md). It fixes 60 provider HTTP
attempts, 2,048 output tokens, 8,000,000 request bytes, 2,400 seconds elapsed, and the
progress-signal rule per attempt. Per-attempt and full-run calculated API cost limits and a
future UTC deadline require per-run approval. If any of the three is blank, execution
fails before a provider call.

**Classification:** Reaching a limit is `technical_incomplete` with `unknown` quality.
Call and cost boundaries become `budget_stopped`; time, size, output, and progress-signal
boundaries become `censored`. Neither becomes `wrong_answer`. Preserve confirmed cost,
unresolved exposure, final request, response, and usage, workspace and state replay, and
whether the verifier ran.

**Natural-termination observation:** Not permitted in a general comparison. Only a
separate pilot with preapproved cost, maximum exposure, and manual stopping conditions
fixed in an independent contract may be considered. The current runner has no entry point
for that pilot.
