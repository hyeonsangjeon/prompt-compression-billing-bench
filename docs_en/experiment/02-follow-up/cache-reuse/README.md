# Cache Reuse Execution: Zero Valid Cycles

This page is a short substudy summary and reading guide. The
[complete measured report](execution-20260923.md) remains the evidence source for exact
conditions, hashes, controls, and the public quotation boundary.

## Result first

Provider execution occurred, but the comparison produced no valid cycle. One cycle was
attempted and became invalid, leaving an observed valid-cycle count of `0`. No Cache-effect
estimate, miss rate, savings, reuse contrast, or stability result was computed.

Here, a **bundle** is the execution unit for one condition and one reuse level. A
**task trial** is one task execution within that bundle. A **request prefix** is the
leading compared portion within one request's serialized message content. The task and
logical request ordinal identify which individual requests are paired across reuse; the
sequence of requests is not itself the prefix. Request count and ordinal are separate
from byte or token prefix length.

- **Question:** Could the run preserve each task's request prefix across reuse while
  comparing `none` with `squeez`?
- **Fixed design:** The plan was `{none, squeez}` × reuse `{0, 1, 2}`, ordered
  `0 → 1 → 2`, with five fixed tasks in every cell, concurrency `1`, and an initial
  target of 10 valid cycles.
- **Observation:** One cycle was attempted and invalid. The 18 successful provider calls
  and `3/5` completed-trial verifier result describe the incomplete invalid cycle.
- **Limit:** With zero valid cycles, the record does not support a condition effect,
  general quality comparison, causal claim, ranking, non-inferiority claim, or total
  savings claim.

A valid cycle required all six bundles across both conditions and all three reuse levels
to complete while satisfying the prefix, usage, provenance, and execution predicates.

## Execution denominators and stop flow

[![The initial plan required 10 valid cycles, 60 bundles, and 300 task trials. One cycle was attempted and invalid, leaving zero valid cycles and zero replacements. Two bundles started, one completed and one remained incomplete and invalid. Six task trials started, five completed and one remained incomplete. In none reuse 1, cancel-async-tasks reached logical request ordinal 3, but reuse 0 had only two predecessor requests, so no request pair existed at ordinal 3 and validation rejected the current request before provider dispatch. The 18 successful provider calls and 3-of-5 completed-trial quality result are descriptive values from the invalid partial run, not a Cache-effect estimate.](../../../../figures/follow-up/cache-execution-denominators-en.svg)](../../../../figures/follow-up/cache-execution-denominators-en.svg)

*The figure keeps planned, attempted, complete, and invalid denominators separate by
unit, then shows the stop at logical request ordinal `3`. With zero valid cycles, no
Cache effect, reuse contrast, savings, ranking, or stability result was computed. Open
the link to view the SVG at full size.*

### Complete text alternative

| Unit | Plan | Observation and interpretation |
|---|---|---|
| Cycles | 10 valid | 1 attempted, 0 valid, 1 invalid, 0 replacement |
| Bundles | 60 | 2 started, 1 complete, 1 incomplete and invalid |
| Task trials | 300 | 6 started, 5 complete, 1 incomplete |
| Request-prefix stop | Planned order `0 → 1 → 2` within `none` | The reuse-0 bundle completed. In reuse 1, `cancel-async-tasks` reached logical request ordinal `3`, but the predecessor execution had only `2` requests. With no predecessor request at ordinal `3`, no prefix difference or length was measured; validation rejected the current request before provider dispatch. |
| Descriptive values | Not a condition or reuse-effect denominator | 18 successful provider calls; 3/5 completed task trials passed |
| Task strata | Five fixed tasks in each cell | 2 in the primary cache-analysis denominator; 3 `not_applicable` |
| `cached input` | Not planned as an effect or miss-rate measure | 0 provider-reported tokens; not a Cache effect of 0% or a miss rate |
| Claim boundary | A comparison required valid cycles | No effect, reuse contrast, savings, ranking, or stability result was computed |

## Measurement conditions

| Item | Fixed or observed condition |
|---|---|
| Execution source | Commit `e78a32edca9d5ce4f991700e3a299d72164e94be`; tree `63f969519c93a58faf800ed91cc464f9b955fe2b` |
| Execution time | The public-safe sealed evidence retains no execution date, time window, or timezone. None is inferred from the filename or publication date. |
| Provider and model | `foundry`; `gpt-5.4`; provider-reported revision `gpt-5.4-2026-03-05` |
| API boundary | `openai_v1_chat_completions` through a project-scoped Foundry endpoint binding; endpoint values and resource identifiers are not published |
| Generation settings | Temperature `0`; reasoning effort `none`; `determinism_claimed=false`. Temperature `0` does not establish identical request counts. |
| Conditions and order | The plan was `{none, squeez}` with reuse `{0, 1, 2}` in the order `0 → 1 → 2`. In the observed sequence, `none`/reuse `0` completed and `none`/reuse `1` remained incomplete. |
| Task population | Five fixed tasks per cell; two were included in the primary cache-analysis denominator and three were `not_applicable` |
| Planned denominator | 10 valid cycles, 60 bundles, and 300 task trials; concurrency `1` |
| Usage and cost source | API-reported usage from successful calls, multiplied by the admitted fixed price schedule; not an invoice |
| Judge | The native task verifier applied only to completed trials. The sealed report inspected for this summary contains no evidence of independent judge validation. |

## Observed denominators, usage, and quality

| Unit | Planned | Attempted or started | Complete or valid | Invalid or incomplete | Replacement |
|---|---:|---:|---:|---:|---:|
| Cycles | 10 | 1 | 0 | 1 | 0 |
| Bundles | 60 | 2 | 1 | 1 | 0 |
| Task trials | 300 | 6 | 5 | 1 | 0 |

| Observation | Value | Scope |
|---|---:|---|
| Successful provider calls | 18 | Five-task descriptive total from the partial invalid cycle |
| API-reported input | 65,423 tokens | Provider usage |
| API-reported cached input | 0 tokens | Not a Cache-effect estimate or miss rate |
| API-reported output | 9,690 tokens | Provider usage |
| Calculated API cost | USD 0.3089075 | Fixed-price calculation, not an invoice |
| Invoice | `not_measured` | No billing reconciliation was performed |
| Completed-trial quality | 3/5 passed | Five completed trials only; the sixth started trial was incomplete |

## Why the cycle stopped

**Observation.** The `none`, reuse `0` bundle completed. In the following `none`, reuse
`1` bundle, `cancel-async-tasks` reached logical request ordinal `3`, but its reuse-0
predecessor had only `2` requests, so no predecessor request existed at ordinal `3`.
No prefix difference or prefix length was measured for that absent pair. Request-prefix
validation rejected the current ordinal-`3` request before provider dispatch. The cycle
remained invalid, with no outer retry or replacement.

**Possible explanation.** The two task executions produced different request counts. A
non-deterministic execution path could produce this pattern, but the run did not test that
explanation.

**Limit.** “Request width” in the complete report means the number of requests, not a
token or byte width. The evidence did not isolate whether the request-count difference
came from the model, task, transport, namespace, compression, or another mechanism. The
zero-valid-cycle denominator prevented the cache comparison and stability extension.

## Further reading

- [Complete Cache execution report](execution-20260923.md)
- [Public Cache execution contract](../../../../docs/cache-reuse.md)
- [Follow-up study entry](../README.md)
- [한국어 요약](../../../../docs/experiment/02-follow-up/cache-reuse/README.md)
