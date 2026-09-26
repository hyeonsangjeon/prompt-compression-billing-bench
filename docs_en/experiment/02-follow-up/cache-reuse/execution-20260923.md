# Cache Reuse Execution Report: Why the First Comparison Cycle Was Invalid

## What the run was trying to learn

This run asked whether a provider could reuse work on repeated leading input, and whether
compressing that input with `squeez` changed the result. Prompt caching is not the reuse of
a stored answer. It is provider-specific reuse of input processing when repeated leading
content is recognized as the same. A provider may expose cached-input usage without
guaranteeing a particular financial effect, so a cache-related setting alone cannot
establish savings.

Compression is a separate intervention. The `none` condition left the input uncompressed;
the planned `squeez` condition reduced the input before dispatch. To distinguish reuse from
compression, the design needed comparable individual requests from the same task at the
same logical ordinal. If the requests could not be paired, the run could not attribute a
difference to either condition.

Reuse `0`, `1`, and `2` describe a planned series of matching predecessor opportunities,
not SDK retries, outer retries, or three different tasks. Within one cycle, compression
condition, task, and logical request ordinal, reuse 0 is the first observation with no
admitted predecessor. Reuse 1 follows one successful matching predecessor, and reuse 2
follows two. Reuse contrasts therefore hold compression fixed, while compression contrasts
hold reuse fixed. The latter comparison does not require `none` and `squeez` message bytes
to be identical, because changing the input is the compression intervention itself.

## Result

Provider-backed execution occurred, but the first comparison cycle did not become valid.
The `none`, reuse `0` bundle completed. During the next `none`, reuse `1` bundle,
`cancel-async-tasks` reached logical request ordinal `3`, while its reuse-0 predecessor had
produced only `2` requests. There was no predecessor request at ordinal `3`, so validation
rejected the current request before provider dispatch. The cycle was preserved as invalid,
with no outer retry or replacement, and the planned `squeez` condition was never reached.

One cycle was attempted, zero were valid, and one was invalid. The run therefore produced
no Cache-effect estimate, cache miss rate, reuse contrast, savings estimate, or stability
result. The provider reported `0` cached-input tokens for successful calls in the partial
cycle, but that value is descriptive API usage. It is not an effect estimate, a miss rate,
or evidence that provider caching did not operate.

> **Public quotation boundary.** Any quotation of this result must state that one cycle
> was attempted, that it was invalid, and that zero valid cycles were available. It must
> also retain the conclusion that no Cache-effect estimate or reuse comparison was
> produced. The partial-cycle value `cached input 0` cannot be quoted as a miss rate or
> Cache-effect result.

## Why the requests had to match

A request prefix is the leading compared portion within one individual request's
serialized message content. It is not a sequence of whole requests. The task and logical
request ordinal select which individual requests are paired across reuse levels; the number
of requests and their ordinals are different from a prefix length measured in bytes or
tokens.

For the third request in reuse `1` to be comparable, the same task needed a third request
in reuse `0`. It had only two. No differing prefix or prefix length was measured for the
absent ordinal-3 pair because that pair did not exist. This does not mean that every local
prefix measurement was absent: the earlier structural screening and the checks on request
pairs that did exist are separate observations.

Rejecting the unmatched request kept a request-count change out of the planned reuse and
compression contrasts. The pre-dispatch stop preserved the technical cost already incurred
without turning an incomparable partial run into a result.

## How the comparison was planned

The sealed design combined conditions `{none, squeez}` with reuse levels `{0, 1, 2}`. The
reuse order within a condition was `0 -> 1 -> 2`. Every cell contained the same five fixed
tasks and ran at concurrency `1`. A bundle was the five-task execution unit for one
condition and one reuse level. A valid cycle required all six bundles to complete and pass
the prefix, usage, provenance, and execution predicates.

The initial plan called for 10 valid cycles, 60 bundles, and 300 task trials. A predeclared
stability rule could extend the run once, to at most 20 valid cycles, but only if the first
10 valid cycles met that rule's extension condition. Because this run produced no valid
cycle, the stability comparison and extension did not run.

Only two tasks had been classified as structurally eligible for the primary cache
denominator before provider execution: `multi-source-data-merger` and
`nginx-request-logging`. The other three tasks, `cancel-async-tasks`,
`log-summary-date-ranges`, and `openssl-selfsigned-cert`, remained in every bundle for
descriptive usage, calculated cost, and native quality. Their cache opportunity was
`not_applicable`, not a numeric zero or a cache miss.

The run held the source commit and tree, model/deployment/revision binding, generation
settings, task and input identities, pricing schedule, request-prefix contract,
cycle-isolation contract, concurrency, order, and safety limits fixed. It used source
commit `e78a32edca9d5ce4f991700e3a299d72164e94be` and tree
`63f969519c93a58faf800ed91cc464f9b955fe2b`.

## How 18 successful calls still produced zero valid cycles

The counts describe different layers of the run. The recorded count of 18 successful
provider calls means 18 provider responses returned usable usage observations; it does not
count every request merely because it was dispatched. A task trial is one task execution.
A bundle contains five task trials for one condition and reuse level. A cycle is the
complete six-bundle comparison. Success at a lower layer does not complete the layers above
it.

Before validation stopped the run, 18 provider calls succeeded. Six task trials started and
five completed. Two bundles started, but only the reuse-0 bundle completed; the reuse-1
bundle remained incomplete. Because the complete six-bundle unit was missing, none of the
successful calls or completed trials supplied a valid cycle denominator.

The terminal status was `stopped_invalid_cycle`.

| Denominator | Planned | Attempted or started | Complete or valid | Invalid or incomplete | Replacement |
|---|---:|---:|---:|---:|---:|
| Cycles | 10 initially | 1 | 0 | 1 | 0 |
| Bundles | 60 initially | 2 | 1 | 1 | 0 |
| Task trials | 300 initially | 6 | 5 | 1 | 0 |

| Provider execution count | Value |
|---|---:|
| Successful provider calls | 18 |
| Missing usage records | 0 |
| HTTP 429 responses | 0 |
| Transport failures | 0 |
| Eligible request observations | 10 |
| Not-applicable request observations | 8 |
| Five-task descriptive request observations | 18 |

## Reading usage, calculated cost, and quality

API usage, calculated cost, an invoice, and native quality answer different questions.
They are not interchangeable measures of success.

| Provider-reported usage | Tokens | Provenance |
|---|---:|---|
| Input | 65,423 | API-reported, partial invalid cycle |
| Cached input | 0 | API-reported input subset from the partial invalid cycle; not additive, not a Cache-effect estimate, and not a miss rate |
| Output | 9,690 | API-reported, partial invalid cycle |

Cached input is a subset of input rather than an additional amount. The provider-reported
zero cannot be converted into an effect percentage or miss rate without a valid comparison
denominator.

| Calculated amount | USD | Meaning |
|---|---:|---|
| Input cost | $0.1635575 | API-reported input usage multiplied by the fixed admitted prices |
| Output cost | $0.14535 | API-reported output usage multiplied by the fixed admitted prices |
| Total calculated cost | $0.3089075 | Preserved technical cost for the partial invalid cycle |
| Invoice | `not_measured` | No reconciled billed amount was measured |

The calculated total comes from multiplying the recorded successful-call usage by the
admitted price schedule. It is not a reconciled invoice and does not establish realized
savings.

Five task trials completed and received native verifier outcomes; 3 of 5 passed. The sixth
started task trial was incomplete. That result describes only the completed trials before
the integrity stop. It is not a `none` versus `squeez` comparison, a condition-level quality
result, a rank, a non-inferiority result, or a general model-quality claim.

## Supported finding, possible explanation, and limit

**Supported finding.** The integrity check prevented an unmatched request from entering the
comparison. The first attempted cycle remained invalid, so no Cache-effect comparison was
computed.

**Possible explanation.** The two executions of `cancel-async-tasks` produced different
request counts. Temperature `0` and reasoning effort `none` were configured, but those
settings do not establish deterministic request counts. A non-deterministic execution path
could produce this pattern, but the run did not test that explanation.

**Limit.** The evidence did not isolate whether the request-count difference came from the
model, task, transport, namespace, compression, or another mechanism. It also cannot use
cached input `0` as a cache miss rate, calculated cost as an invoice, or `3/5` completed
trials as condition or general quality. With zero valid cycles, the run cannot support a
Cache effect, reuse contrast, savings, ranking, non-inferiority, or stability claim.

## Measurement terms

| Term | Meaning in this report |
|---|---|
| API-reported usage | Input, cached-input, and output token fields returned by the provider for successful requests. It is not an invoice. |
| Calculated cost | API-reported usage multiplied by the fixed admitted price schedule. It is not a reconciled billed amount. |
| Invoice | A separately reconciled billing record. It was `not_measured` for this run. |
| Valid cycle | A complete six-bundle cycle across both conditions and all three reuse levels that satisfied the admitted prefix, usage, provenance, and execution predicates. |
| Successful provider call | A request for which the provider returned a successful response with the usage observation counted in this report; not merely a dispatched request. |
| Eligible request observation | A successful provider request from one of the two structurally eligible tasks. This is the only task stratum admitted to the primary cache denominator. |
| Not-applicable request observation | A successful request from one of the three structurally ineligible tasks. It remains in descriptive usage, cost, and quality totals but not in the primary cache denominator. |
| Five-task descriptive observation | Any successful provider request from the fixed five-task bundle, reported only as descriptive provider usage, calculated cost, or quality context. |
| Native quality | The existing native task verifier outcome for a completed task trial. It is separate from cached-token usage. |

## Measurement conditions

| Item | Sealed condition |
|---|---|
| Source | Commit `e78a32edca9d5ce4f991700e3a299d72164e94be`; tree `63f969519c93a58faf800ed91cc464f9b955fe2b` |
| Execution window | The sealed public-safe evidence available for this report does not retain an execution date, time window, or timezone. The run-manifest hash is preserved below; no timestamp was inferred from the filename, publication date, or chat metadata. |
| Provider and model | Provider `foundry`; model `gpt-5.4`; provider-reported revision `gpt-5.4-2026-03-05` |
| API and endpoint type | `openai_v1_chat_completions` through a project-scoped Foundry endpoint binding; the endpoint value and resource identifier are not published |
| Generation settings | Temperature `0`; reasoning effort `none`; `determinism_claimed=false`. Temperature `0` does not establish deterministic request counts. |
| Runtime boundary | Project-owned private Linux runtime using managed identity; serial concurrency `1`; hash-bound namespace/isolation and external-matching-traffic evidence. Runtime names, identifiers, paths, and endpoint values are not published. |
| Judge account | The native task verifier applied only to completed task trials; `3/5` is descriptive for those five trials. The sealed report contains no evidence of independent judge validation. |
| Fixed price source | Admitted fixed schedule checked at `2026-09-22T14:30:31.954Z`; its source reference is retained privately and bound by the cache/native ledger SHA-256 values below. No separate source reference is published. |
| Conditions | `{none, squeez}` |
| Reuse levels | `{0, 1, 2}`, ordered `0 -> 1 -> 2`; reuse contrasts hold compression fixed, and compression contrasts hold reuse fixed |
| Task population | Five fixed tasks in every cell; two eligible and three `not_applicable` for the primary cache denominator |
| Concurrency | `1` |
| Planned initial denominator | 10 valid cycles; 60 useful bundles; 300 task trials |
| Maximum stability extension | 20 valid cycles; extension only if the predeclared stability rule required it |
| Provider result source | API-reported usage from successful provider calls |
| Cost source | API-reported usage multiplied by the admitted fixed price schedule |
| Invoice source | `not_measured` |
| Failure treatment | Prefix drift stops before dispatch; invalid cycles and their technical cost are preserved; no outer retry of a started provider attempt |
| Public evidence grade | Sanitized aggregate and hash-only evidence; no raw prompt, response, endpoint, credential, private path, or private resource identifier |

## Safety controls

The following values were hard execution ceilings derived from the source and fixed price
schedule. They were controls, not forecasts, spend, or an invoice.

| Control | Sealed value |
|---|---:|
| Per-task ceiling | $1,202.4576 |
| Per-bundle ceiling | $6,012.288 |
| Maximum 20-cycle design ceiling | $721,474.56 |
| Run deadline | `2026-10-10T10:48:45.452539Z` |

Actual calculated cost before the integrity stop was `$0.3089075`.

## Factual guard record

The figure generator and focused tests read this stable record instead of depending on the
wording or line wrapping of the explanatory prose. The record repeats admitted public facts;
it does not add evidence or change the report's quotation boundary.

| Field | Value |
|---|---|
| `source_commit` | `e78a32edca9d5ce4f991700e3a299d72164e94be` |
| `source_tree` | `63f969519c93a58faf800ed91cc464f9b955fe2b` |
| `conditions` | `none,squeez` |
| `reuse_order` | `0,1,2` |
| `tasks_per_cell` | `5` |
| `concurrency` | `1` |
| `initial_valid_cycles` | `10` |
| `initial_bundles` | `60` |
| `initial_task_trials` | `300` |
| `maximum_valid_cycles` | `20` |
| `cycles_attempted` | `1` |
| `cycles_valid` | `0` |
| `cycles_invalid` | `1` |
| `replacement_cycles` | `0` |
| `bundles_started` | `2` |
| `bundles_complete` | `1` |
| `bundles_incomplete` | `1` |
| `task_trials_started` | `6` |
| `task_trials_complete` | `5` |
| `task_trials_incomplete` | `1` |
| `successful_provider_calls` | `18` |
| `input_tokens` | `65,423` |
| `cached_input_tokens` | `0` |
| `output_tokens` | `9,690` |
| `input_cost_usd` | `0.1635575` |
| `output_cost_usd` | `0.14535` |
| `total_cost_usd` | `0.3089075` |
| `invoice_status` | `not_measured` |
| `completed_trial_quality` | `3/5` |
| `eligible_tasks` | `2` |
| `not_applicable_tasks` | `3` |
| `stop_condition` | `none` |
| `stop_reuse` | `1` |
| `predecessor_reuse` | `0` |
| `stop_task` | `cancel-async-tasks` |
| `stop_ordinal` | `3` |
| `predecessor_request_count` | `2` |
| `dispatch_status` | `rejected_before_dispatch` |
| `terminal_status` | `stopped_invalid_cycle` |
| `execution_time_status` | `date_window_timezone_not_retained` |
| `cache_comparison_status` | `not_computed_zero_valid_cycles` |
| `cached_input_interpretation` | `input_subset_not_additive_not_effect_or_miss_rate` |
| `quality_scope` | `completed_trials_only_not_condition_or_general_quality` |

## Evidence hashes

| Artifact | SHA-256 |
|---|---|
| Cost/deadline derivation | `b0cbc6a291769c034546a89979b5dfaa29a0d522df137c91224541c12cd1221f` |
| Cache ledger | `a23acd062978825530940db92d013f6ee387dbd69f9daaba90d854d5a0f48ce6` |
| Native ledger | `f978be7d59f253508d6f47689ca03da2941ce0470fed05ea493f195271351cf5` |
| Runtime facts | `dc8726d30d2b804ced536173de38bdf92e81bb2962856bb746a3dde6c6ea5063` |
| Doctor result | `8d10ed7bc056b46be1d3e241473c63cafba64fde265320199f5308565d0a46d1` |
| Admission seal | `760d05559bc2973639aec2d00d57f3f2439466e855d18d7c71fd73651b0a320a` |
| Execution plan | `660024baa192e28c6ac9b3f698e0af32054513352b001dc0a6c09378d0a3d181` |
| Run manifest | `4736ac072016d7d501d5dbee6011569e92abcc3fef52a5c29aae9a61a9673e21` |
| Cycle failure | `c8d83baf8bfc99b15decd275bb45e6c4ae46b0ab8d9ee5faa5958cdded691ed6` |
| Failure aggregate | `dfeb88f3291226a5f8fa503e32f841cdf55653bcc4593fa654a204ced985f9d0` |
| Stability decision | `d0a56c0725ba4e8ab43d162bd8859d153b0119f762025638edf28af0b022f1b9` |
| Cleanup receipt | `98292b4c810933ca319e9933fab4e08ad4b006903fa7e1b8880d02ed02fc6ec7` |
| Completion seal | `88496d641b155f9b9b293956b692cb9103058a31b592707cd737c311e196b3b0` |
| VM deallocation receipt | `6823e8e04e1db35aababbe6f45ab08dd60b7c7e66743a04f7995f810044d87e2` |

## Validation and cleanup

- 68 unique tests passed and 0 were skipped after two invalid test-path
  invocations were corrected.
- Private evidence remained no-clobber and used restrictive permissions.
- Cleanup survivors were `0`.
- The runtime VM was deallocated.
- No endpoint, credential, private path, raw prompt or response, or private
  resource identifier is included in this report.

This report is post-snapshot material. It does not modify the preserved English snapshot
or the Korean experiment records. See the
[Cache-reuse execution contract](../../../../docs/cache-reuse.md) for the public design
boundary.
