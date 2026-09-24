# SWE-Lancer Fixed Trace: Zero Valid Protocol Traces

This page is a short substudy summary and reading guide. The
[complete measured report](fixed-trace-20260923.md) remains the evidence source for exact
conditions, hashes, controls, and the public quotation boundary.

## Result first

The fixed candidate did not produce a valid provider-backed trace. One execution was
planned, but two **runner groups** were observed. A runner group is a separate private
output group left by the runner; it is not a provider request or a valid trace. Both
groups timed out while the sandbox was starting, before any logical model request,
provider HTTP attempt, or grader call. The observed valid-protocol-trace count was `0`.

- **Question:** Could the preselected candidate `28565_1001` produce one actual trace
  under the fixed provider, sandbox, grader, and safety contract?
- **Fixed design:** Split `diamond`, one `ic_swe` task, pinned solver, catalog, selected
  row and image, concurrency `1`, runner retries `0`, SDK retries `0`, and exactly one
  planned execution.
- **Observation:** Initial pre-dispatch verification passed `27/29` checks and failed
  `task.row` and `image.config`. Corrected verification passed `31/31`, but a second
  runner group appeared and the guard observed `allow_internet=true` against configured
  `disable_internet=true`. Both groups ended in startup timeout.
- **Limit:** The two `correct=False` rows are startup-error placeholders, not graded
  failures. They do not support task quality, pass rate, ranking, stability, or population
  cost.

A valid protocol trace required exactly one execution to start after every pre-dispatch
predicate passed, retain the fixed sandbox-isolation contract, and seal its result and
cleanup.

## Protocol execution flow

[![One fixed execution was planned, but two runner groups were observed. Initial pre-dispatch verification passed 27 of 29 checks and failed task.row and image.config; the first runner group ended in a sandbox startup timeout. Corrected verification later passed 31 of 31, but a second runner group breached the one-execution rule, observed allow_internet=true against configured disable_internet=true, and also timed out during startup. The sandbox had two startup attempts and zero ready states. Provider, model, API, and grader calls were 0/0/0/0. Valid protocol traces were zero, the grader was not run, runner exit was unknown, and task quality, invoice, and host cost were not measured. Two error result rows are not graded failures, and cleanup survivors were zero.](../../../../figures/follow-up/swe-protocol-outcome-en.svg)](../../../../figures/follow-up/swe-protocol-outcome-en.svg)

*The figure keeps the one-execution plan, two observed runner groups, gate states,
network-setting contradiction, startup timeouts, and cleanup in sequence. Valid protocol
traces and grader executions were zero. Open the link to view the SVG at full size.*

### Complete text alternative

| Gate or status | Plan | Observation and interpretation |
|---|---|---|
| Fixed execution | Exactly 1 | 2 runner groups; the second breached the one-execution rule |
| Initial gate and group 1 | Every pre-dispatch predicate must pass | 27/29; failed `task.row` and `image.config`, then `computer_startup_timeout` |
| Corrected gate and group 2 | Recheck owner-controlled inputs | 31/31; a second group then appeared and ended in `computer_startup_timeout` |
| Network isolation | `disable_internet=true` | Guarded start observed `allow_internet=true`; the isolation predicate did not hold |
| Sandbox | Prepare the sandbox for the one fixed execution | 2 startup attempts; 0 ready; 2 startup timeouts |
| Calls | Fixed provider, model, API, and grader | Provider/model/API/grader `0/0/0/0` observed |
| Trace and grader | Target of 1 valid protocol trace | 0 valid; grader `not_run` |
| Error result rows | Keep startup errors separate from grading | 2 `correct=False` startup-error placeholders, not graded failures; task quality `not_measured` |
| Runner and cost status | Keep measurement units separate | Runner exit `unknown`; calculated API cost `USD 0.000000`; invoice and host cost `not_measured`. This does not establish zero host cost. |
| Cleanup | Require zero survivors | 0 container, process, workspace, Docker-network, and network-rule survivors |
| Claim boundary | Quality claims require a valid trace and grader result | No pass rate, ranking, candidate-quality, stability, or population-cost conclusion |

## Measurement conditions

| Item | Fixed or observed condition |
|---|---|
| Repository source | Commit `cf8960a6121e91c8ec6a796d470009a27504bf61`; tree `70e0961bf2a3009d9a2c8e36471744be81775daa` |
| Upstream and candidate | `openai/frontier-evals` commit `51052cede8cc608f95bb00346635e03759013e5a`; candidate `28565_1001`; split `diamond`; type `ic_swe`; one task |
| Image and runtime | Pinned Linux/amd64 image on a project-owned private Linux carrier |
| Provider and model | `openai`; model setting `openai/gpt-4o`; request model `gpt-4o`; reported revision `gpt-4o-2024-11-20`, pinned and verified in the admitted contract. No inference response occurred. |
| API boundary | `openai-v1-chat-completions`; credential and sandbox endpoint values and identities are not published |
| Execution settings | Concurrency `1`; multiprocessing, Slack, and registry pull disabled; runner retries `0`; SDK retries `0`; no determinism claim |
| Network condition | The command set `disable_internet=true`; the guarded start observed `allow_internet=true`, so the isolation predicate did not hold |
| Evidence window | `2026-09-23T02:12:29Z` to `2026-09-23T02:18:27.355804Z`, UTC; derived from UTC runner-group names and private run-log modification times, not an independently timed workload duration |
| Judge | The benchmark grader was not invoked. The sealed evidence inspected for this summary contains no independent grader-validation evidence. |

The candidate was fixed from the one `ic_swe` example in the pinned upstream README
before task content was viewed. The earlier
[candidate evaluation](../../swe-lancer-candidate-evaluation-20260920.md) records the
historical admission boundary, not the later protocol-invalid execution result.

## Execution record

| Gate or denominator | Observation |
|---|---:|
| Planned fixed executions | 1 |
| Initial pre-dispatch verification | 27/29; failed `task.row`, `image.config` |
| Final pre-dispatch verification | 31/31 |
| Runner groups observed | 2 |
| Sandbox startup attempts / timeouts | 2 / 2 |
| Sandbox ready | 0 |
| Valid protocol traces | 0 |
| Provider / model / API / grader calls | 0 / 0 / 0 / 0 |
| Cleanup survivors | 0 |

The first group appeared after the initial failed check record and ended in
`computer_startup_timeout`. After owner-controlled corrections, the final verification
passed `31/31`, but the second group breached the one-execution rule and preserved the
network-flag contradiction before ending in the same timeout. The later `31/31` result
did not erase the initial `27/29` result or authorize the second group.

## Usage, cost, and quality

| Item | Status | Meaning |
|---|---:|---|
| Provider input / output tokens | 0 / 0 | Observed zero because no provider request was dispatched |
| Cached / reasoning tokens | `not_applicable_no_provider_call` | No provider response existed |
| Calculated API cost | `USD 0.000000` | Provider-usage calculation, not an invoice |
| Provider-reported cost | `not_measured` | Not measured in this record |
| Invoice / host cost | `not_measured` / `not_measured` | Neither was measured in this record |
| Runner exit | `unknown` | No runner-execution record was sealed |
| Grader / task quality | `not_run` / `not_measured` | Error rows are not grader outcomes |

Zero model or API calls do not make this a successful or cost-free benchmark.

## Why the trace is invalid

**Observation.** An extra runner group appeared, and the second guarded start observed
`allow_internet=true`. Both groups ended in sandbox startup timeout before provider and
grader dispatch.

**Possible explanation.** Both private run logs ended while waiting for the sandbox
computer to start. That pattern is consistent with a startup problem, but the evidence
did not isolate image startup, runtime wiring, container health, network handling, or
another mechanism.

**Limits.** The two-group history breached the one-execution contract, and the network
flag breached the isolation condition. The record therefore cannot establish task pass
or failure, provider reliability, model quality, causality, pass rate, ranking, stability,
non-inferiority, representative performance, or population cost.

## Further reading

- [Complete SWE-Lancer execution report](fixed-trace-20260923.md)
- [Historical candidate evaluation](../../swe-lancer-candidate-evaluation-20260920.md)
- [Runtime-owner handoff](../../../../docs/runtime-owner-handoff.md)
- [Follow-up study entry](../README.md)
- [한국어 요약](../../../../docs/experiment/02-follow-up/swe-lancer/README.md)
