# SWE-Lancer Fixed Trace Result: Zero Valid Protocol Traces

## Finding

The fixed candidate did not produce a valid provider-backed trace. Two runner
groups were observed, although the sealed plan allowed exactly one execution.
Both stopped while the sandbox computer was starting, before any logical model
request, provider HTTP attempt, tool call, or grader call. The terminal result
is therefore `invalid_protocol_trace`, not a task pass, task failure, provider
failure, or grader outcome.

Three predicates invalidate the result. The first runner group began after the
initial pre-dispatch verification had passed `27/29` checks and failed
`task.row` and `image.config`. A corrected verification later passed `31/31`,
but a second runner group breached the one-execution rule. During the guarded
second start, the private observer recorded `allow_internet=true` even though
the command configured `disable_internet=true`.

> **Public quotation boundary.** Any quotation of this result must retain all
> of the following: two runner groups were observed against a one-execution
> plan; zero valid protocol traces were produced; both groups ended in sandbox
> startup timeout before provider dispatch; provider/model/API/grader calls
> were `0`; and the result does not measure candidate quality or cost.

## What was attempted

This was a descriptive execution of one fixed configuration, not an A/B test.
Candidate `28565_1001` was selected from the single `ic_swe` example in the
pinned upstream README before task content was viewed. The execution retained
split `diamond`, task count `1`, the pinned solver and catalog bytes, the exact
selected-row identity, the fixed Linux/amd64 image, and the admitted provider,
model, API, sandbox, price, and safety contracts.

The intended path used
`swelancer.solvers.swelancer_agent.solver:SimpleAgentSolver` through the pinned
upstream runner, with concurrency `1`, multiprocessing disabled, Slack
disabled, registry pulling disabled, and runner retries `0`. No replacement
task, gold solution, `DummySolver`, model substitution, or second candidate was
permitted.

## Measurement terms

| Term | Meaning in this report |
|---|---|
| Valid protocol trace | Exactly one execution that begins only after every pre-dispatch predicate is green, keeps the fixed sandbox isolation contract, and seals its result and cleanup. The observed denominator was `0`. |
| Runner group | A distinct private runner output group. Two groups were preserved. A runner group is not evidence of a provider request or valid trace. |
| Logical model request | One solver-level model request before transport retries. None occurred. |
| Provider HTTP attempt | One outbound HTTP attempt to the admitted model API. None occurred. |
| Provider-reported usage | Token fields returned with a provider response. No provider usage record existed because no request was dispatched. |
| Local runner result row | A runner-generated error row. The two `correct=False` rows carried zero local token columns and are not grader outcomes. |
| Calculated API cost | Provider usage multiplied by the admitted fixed prices. It was `USD 0.000000` because no provider request was dispatched; it is not an invoice. |
| Invoice | An independently reconciled billed amount. It was `not_measured`. |

## Measurement conditions

| Item | Sealed condition |
|---|---|
| Repository source | Commit `cf8960a6121e91c8ec6a796d470009a27504bf61`; tree `70e0961bf2a3009d9a2c8e36471744be81775daa` |
| Upstream source | `openai/frontier-evals` commit `51052cede8cc608f95bb00346635e03759013e5a` |
| Candidate | `28565_1001`; split `diamond`; type `ic_swe`; task count `1` |
| Solver pin | 15,177 bytes; SHA-256 `860c8bf2e65d02de9d768ff36fee6d80bb8d3dfa9955e6b83ad983ea49c62012` |
| Catalog pin | 8,403,631 bytes; SHA-256 `5c3a6d4570b49be0d9fced98f5b32487420b16f25c98d6658830e31fa03f049a` |
| Selected row | 2,761 UTF-8 bytes; SHA-256 `ff7ea7f9d37739a30adff1d26f51eb3baee87a1cad421d4e1cc17c26adb19702` |
| Image | Linux/amd64; manifest `sha256:b6ee529bbc589b251d2e287aa28068ea4f7e69b3eac2927b393091ac968e7587`; config `sha256:3ac386d8f793eb2c3fdef76766b551bb2c04da8b7dd9703a01b561c293b82400` |
| Runtime | `nanoeval_alcatraz.alcatraz_computer_interface:AlcatrazComputerRuntime`; environment `alcatraz.clusters.local:LocalConfig`; project-owned private Linux carrier |
| Provider and model | Provider `openai`; model setting `openai/gpt-4o`; request model `gpt-4o`; reported revision `gpt-4o-2024-11-20` |
| API and private boundary | `openai-v1-chat-completions`; admitted credential and sandbox endpoint environment bindings were present, but their values and identities are not published |
| Execution settings | Concurrency `1`; multiprocessing disabled; runner retries `0`; SDK retries `0`; registry pull disabled; Slack disabled; no determinism claim |
| Sandbox network setting | The command configured `disable_internet=true`; the guarded start observed `allow_internet=true`, so the isolation predicate did not hold |
| Evidence window | `2026-09-23T02:12:29Z` to `2026-09-23T02:18:27.355804Z`, UTC; derived from UTC run-group names and private run-log modification times |
| Deadline | `2026-09-23T02:36:39Z`; the observed execution evidence ended before the deadline |
| Price schedule | `USD 2.50` per million input tokens and `USD 10.00` per million output tokens; retained only as the admitted calculation schedule |
| Judge | The benchmark grader was not invoked. Independent grader validation was not available in the sealed evidence. |
| Public evidence grade | Sanitized aggregate and hash-only evidence; no raw task, reference, message, solver, catalog, review, endpoint, credential, private path, runtime identifier, or raw trace text |

## Admission and protocol result

The fresh carrier admission exited `0` with `status=ready` and `ready=true`.
Independent carrier verification passed `98/98` checks, and carrier negative
controls passed `11/11`. Those results established the carrier input contract;
they did not make a later trace valid.

| Gate or denominator | Result |
|---|---:|
| Planned fixed executions | 1 |
| Initial pre-dispatch verification | 27/29; failed `task.row`, `image.config` |
| Final pre-dispatch verification | 31/31 |
| Runner groups observed | 2 |
| Valid protocol traces | 0 |
| Replacement attempts recorded by the plan | 0 |
| Sandbox startup attempts | 2 |
| Sandbox ready | 0 |
| Instrumented sandbox start / stop events | 1 / 1 |
| Runner exit codes sealed | 0 |

The plan's `replacement_attempts=0` field does not reconcile the two observed
runner groups. The report preserves the contradiction rather than treating the
second group as an allowed replacement.

## Execution counts

| Recorded unit | Count |
|---|---:|
| Logical model requests | 0 |
| Provider HTTP attempts | 0 |
| SDK retries | 0 |
| Provider calls | 0 |
| Model calls | 0 |
| API calls | 0 |
| Grader calls | 0 |
| Tool calls / results | 0 / 0 |
| Provider usage records | 0 |
| Trace events | 3 |
| Runner result rows | 2 |
| Sandbox startup timeouts | 2 |

| Runner group | Evidence window (UTC) | Outcome | Provider usage rows |
|---|---|---|---:|
| 1 | `2026-09-23T02:12:29Z` to `2026-09-23T02:14:39.545726Z` | `computer_startup_timeout` | 0 |
| 2 | `2026-09-23T02:16:25Z` to `2026-09-23T02:18:27.355804Z` | `computer_startup_timeout` | 0 |

No `runner-execution` record was sealed, so the runner process exit code is
unknown. The preserved failure class comes from both private run logs, not from
an inferred exit code.

## Usage, cost, and quality

| Usage unit | Value | Provenance |
|---|---:|---|
| Provider-reported input tokens | 0 | No provider request was dispatched |
| Provider-reported cached input tokens | `not_applicable_no_provider_call` | No provider response existed |
| Provider-reported output tokens | 0 | No provider request was dispatched |
| Provider-reported reasoning tokens | `not_applicable_no_provider_call` | No provider response existed |
| Provider request wire bytes | 0 | No provider request was dispatched |
| Local runner input / output / reasoning tokens | 0 / 0 / 0 | Two error-placeholder rows; not provider usage |

| Cost unit | Value | Meaning |
|---|---:|---|
| Calculated API cost | `USD 0.000000` | Zero dispatched provider requests and zero provider usage; not an invoice |
| Provider-reported cost | `not_measured` | No provider cost record existed |
| Invoice | `not_measured` | No billing reconciliation was performed |
| Host-compute cost | `not_measured` | No independent host-cost observation was sealed |

The benchmark grader was not invoked, so task pass is `not_measured`. Each
runner group wrote one `correct=False` row after the startup error. Those rows
are error placeholders and must not be quoted as two graded failures or as a
quality denominator.

## Why the trace is invalid

**Observation.** The initial pre-dispatch record failed two checks. A first
runner group nevertheless appeared immediately afterward and ended with
`computer_startup_timeout`. After the owner-controlled corrections, the final
pre-dispatch verification passed `31/31`, but a second runner group created a
second execution record. Its guard recorded `allow_internet=true` while the
fixed command configured `disable_internet=true`. It also ended with
`computer_startup_timeout`, before any provider request or grader call.

**Possible explanation.** Both private run logs ended while waiting for the
sandbox computer to start. That is consistent with a sandbox-startup problem,
but the evidence did not isolate whether image startup, runtime wiring,
container health, network handling, or another mechanism caused it.

**Limits.** The two-group history breaches the one-execution contract, and the
observed network flag breaches the admitted isolation condition. The evidence
therefore supports zero valid protocol traces. It does not support a candidate
pass/fail judgment, provider reliability claim, model-quality claim, token or
cost distribution, causal explanation, stability estimate, pass rate, ranking,
non-inferiority conclusion, representative performance claim, or population
cost estimate. A new execution would require a separate project item; it cannot
be treated as a continuation or replacement for this result.

## Safety controls and cleanup

These values were hard ceilings, not observed usage, forecast spend, or an
invoice.

| Control | Sealed value |
|---|---:|
| Attempt wall time | 4,920 seconds |
| Cleanup reserve | 120 seconds |
| Logical request timeout | 1,200 seconds |
| Provider HTTP attempts | 40 maximum |
| SDK retries | 0 |
| Maximum output | 2,048 tokens |
| Maximum request wire size | 8,000,000 bytes |
| No-progress window | 8 logical requests |
| Minimum distinct no-progress signals | 3 |
| Attempt calculated-cost cap | USD 20.00 |
| Run calculated-cost cap | USD 20.00 |
| Runtime process concurrency | 1 |
| Task workspaces | 1 |
| Cleanup survivors | 0 required |

Post-result verification found `0` container, process, workspace, Docker-network,
and network-rule survivors. The private raw trace remained no-clobber with mode
`0600`; sanitized evidence verification passed `61/61`, offline mutation controls
passed `14/14`, privacy findings were `0`, and the focused repository suite
passed `45/45`. The VM reached `deallocated` at
`2026-09-23T03:01:53.152209Z`.

## Evidence hashes

### Carrier and admission

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Admission ledger | 2,275 | `bfcc404dd25a4f02ca7c1f237f8e876ea296e0dd40ae6e1314d54257485ffe80` |
| Carrier attestation | 1,157 | `bea2ebbd3de926c1c0e43ffef83eddf1a179a0e6f1387b961f68bdc1a2af48b4` |
| Carrier result | 7,677 | `cfaff9121067948e1d75d9af990791869906a80f04251a95c5c1b27ad77b1ff7` |
| Provider-contract receipt | 709 | `cbee89b3ffe606345968a78caf368565e3f1a3c92dfbb4422e63bd09b8c1320c` |
| Price receipt | 603 | `77365638018ac22378a562d11164c5e364841275eb10e79c6366ae56b70e58ec` |
| Outbound receipt | 806 | `8b059b3560b6f8592ec811df111424070596fea43af86ec500392788d25bbaab` |
| Independent carrier verification | 4,883 | `cbc0c7332581c5c2487ebde0d4132a89c554557c19c58098838a086681e3cd9f` |
| Carrier negative controls | 1,282 | `860a66d4fd716e23769617b999ada7e8c6745dfd5c277aa06ea1826fe39d195f` |
| Carrier privacy scan | 318 | `e8db5e1cfc17249acbb34d1a17f322b5cd427b932fdbe5a9720b07f4d59c88d7` |
| Carrier cleanup seal | 824 | `f8085e22492db60bd89dcbc2c6166a084a88bdb2e8a3109e06a71a830c0056a9` |

### Execution and private trace inventory

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Execution plan | 3,581 | `c875e8c193c2301ba212ce88586089cff91d229c1edcae31642a52fa9d04bdc5` |
| Private runtime guard | 34,704 | `a30973dddfc746c5a89945b4dde10863ed82fe7b919ab9e45c6f76cf90502c1c` |
| Runner stderr | 31,978 | `2c1873ab46abfa9cd6361d326e388be7f5f20dc69912f2ce61ca32af377f75d6` |
| Runner stdout | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| Raw provider log | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| Raw tool log | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| Trace events | 1,718 | `60da7b736e16e9658f8169b4efc11fa3b8f8a360103eff73bc302d78dccc81ea` |
| Runner group 1 log | 4,255 | `4c70cb2401c52defee23d534f37fb12315f88c4a489c9c8210dd96e3c947aa1c` |
| Runner group 2 log | 5,555 | `d140b01bf32d381f950e0aee3bab72077b6082c40ae8e65bdda11624348b9328` |
| Runner result CSV, both groups | 111 each | `5cb038090490e69f98ed311567564a1910571046e06e4fca2f0a8d8051de3242` |

### Sealed result and cleanup

| Artifact | SHA-256 |
|---|---|
| Sanitized aggregate canonical self-hash | `cd7bc4b17e1c861380af118464438e8d7fe1c3ae187ac02f2fb134ba1bf565f3` |
| Sanitized aggregate file | `4d820df569c9f1f3ecc7ffb61580c427c98bed82bfa1138939fbc096fb2f3cce` |
| Result verification | `b79cfa1f3ba2a646ba41bb614663c745b90e1a279a9fc030c9c8248f21a40fc3` |
| Offline mutations | `8df744649cd1f4452f875310085c8cf38e87a3e1522b65773a39e85c6754b8dd` |
| Result privacy scan | `3e3c3cb17648133a5d889c56f3969c929de597275a9924f4683deb6de3d5b99c` |
| Runtime cleanup receipt | `426a425521b6a9fdaa8b3976d5181afdf963fbb1a79e8923803d0bfc68be71b2` |
| Sanitized manifest canonical self-hash | `b84bc274f60def51f2beb0a5d9a161ff1230d5c926486fb6e6339ce6c50d7ff5` |
| Sanitized manifest file | `2013a6277486470e3f206f5fdeb1722bf3c87321a959b1eb5c9ef274d32d3d13` |
| Remote completion canonical self-hash | `cb83835bf03363421fd0c9306816433c87591c680d9616cb2d8efe478510761e` |
| Remote completion file | `fb10807bba9dc157a50391ce715e5c49582e98e88a7ef17a2114cbc77e855e33` |
| VM deallocation receipt | `3defdd52dbb9363de37af4eb49133812972889be00f4e3af697b15b7e87f304e` |
| Final completion canonical self-hash | `31699e886f151ed47c297442aa959a21d45150e34652acc761e56c4f9c196d59` |
| Final completion file | `89b81e0930b5d827792721e37f6d6e1ac7c7143ee4db2dcb9f8f3e41a9bb4630` |
| Focused repository test log | `6f0a196684be31fe01e825e0ddae71ec3352645e058b0927ee82d739a591648a` |

This report is post-snapshot material. It does not modify the preserved English
snapshot, Korean documents, historical candidate evaluation, or private trace.
See the [SWE-Lancer candidate evaluation](../experiment/swe-lancer-candidate-evaluation-20260920.md)
for the earlier no-trace boundary and the
[runtime-owner handoff](../../docs/runtime-owner-handoff.md) for the public
carrier input contract.
