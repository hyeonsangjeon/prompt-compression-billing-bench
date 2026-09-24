# Cache Reuse Execution Result: Zero Valid Cycles

## Finding

Actual provider-backed execution occurred, but the comparison produced zero
valid cycles. Prefix validation stopped the first cycle after 18 successful
provider calls. Because the valid-cycle denominator was `0`, no Cache-effect
estimate, reuse contrast, or stability result was computed.

The provider reported `0` cached input tokens for the partial cycle. That value
is API-reported usage from an invalid, incomplete cycle. It is not a Cache-effect
estimate, a cache miss rate, or evidence that the provider cache did not operate.

> **Public quotation boundary.** Any quotation of this result must state that
> one cycle was attempted, that the cycle was invalid, and that zero valid cycles
> were available. It must also retain the conclusion that no Cache-effect estimate
> or reuse comparison was produced. The partial-cycle value `cached input 0`
> cannot be quoted as a miss rate or Cache-effect result.

## What was compared

The sealed design planned conditions `{none, squeez}` at reuse levels `{0, 1, 2}`.
`none` added no compression; `squeez` was the compression intervention. Reuse
levels were ordered `0 -> 1 -> 2` within each condition. Every cell retained the
same five fixed tasks and concurrency `1`. The initial design required 10 valid
cycles, or 60 useful bundles and 300 task trials. A predeclared stability rule
could extend the run once to a maximum of 20 valid cycles.

The primary cache denominator included only the two tasks classified as
structurally eligible before provider execution: `multi-source-data-merger` and
`nginx-request-logging`. The other three tasks, `cancel-async-tasks`,
`log-summary-date-ranges`, and `openssl-selfsigned-cert`, remained in every
five-task bundle for descriptive provider usage, calculated cost, and native
quality. Their cache opportunity was `not_applicable`, not a numeric zero or a
cache miss.

The run held the source commit and tree, model/deployment/revision binding,
generation settings, task and input identities, pricing schedule, request-prefix
contract, cycle-isolation contract, concurrency, order, and safety limits fixed.
It used source commit `e78a32edca9d5ce4f991700e3a299d72164e94be`
and tree `63f969519c93a58faf800ed91cc464f9b955fe2b`.

## Measurement terms

| Term | Meaning in this report |
|---|---|
| API-reported usage | Input, cached-input, and output token fields returned by the provider for successful requests. It is not an invoice. |
| Calculated cost | API-reported usage multiplied by the fixed admitted price schedule. It is not a reconciled billed amount. |
| Invoice | A separately reconciled billing record. It was `not_measured` for this run. |
| Valid cycle | A complete six-bundle cycle across both conditions and all three reuse levels that satisfied the admitted prefix, usage, provenance, and execution predicates. |
| Eligible request observation | A successful provider request from one of the two structurally eligible tasks. This is the only task stratum admitted to the primary cache denominator. |
| Not-applicable request observation | A successful request from one of the three structurally ineligible tasks. It remains in descriptive usage, cost, and quality totals but not in the primary cache denominator. |
| Five-task descriptive observation | Any successful provider request from the fixed five-task bundle, reported only as descriptive provider usage, calculated cost, or quality context. |
| Native quality | The existing native task verifier outcome for a completed task trial. It is separate from cached-token usage. |

## Measurement conditions

| Item | Sealed condition |
|---|---|
| Source | Commit `e78a32edca9d5ce4f991700e3a299d72164e94be`; tree `63f969519c93a58faf800ed91cc464f9b955fe2b` |
| Execution window | The sealed public-safe evidence available for this report does not retain an execution date/time window or timezone. The run-manifest hash is preserved below; no timestamp was inferred from publication or chat metadata. |
| Provider and model | Provider `foundry`; model `gpt-5.4`; provider-reported revision `gpt-5.4-2026-03-05` |
| API and endpoint type | `openai_v1_chat_completions` through a project-scoped Foundry endpoint binding; the endpoint value and resource identifier are not published |
| Generation settings | Temperature `0`; reasoning effort `none`; `determinism_claimed=false`. Temperature `0` does not establish deterministic request counts. |
| Runtime boundary | Project-owned private Linux runtime using managed identity; serial concurrency `1`; hash-bound namespace/isolation and external-matching-traffic evidence. Runtime names, identifiers, paths, and endpoint values are not published. |
| Judge account | The native task verifier applied only to completed task trials; `3/5` is descriptive for those five trials. The sealed report contains no evidence of independent judge validation. |
| Fixed price source | Admitted fixed schedule checked at `2026-09-22T14:30:31.954Z`; its source reference is retained privately and bound by the cache/native ledger SHA-256 values below. No separate source reference is published. |
| Conditions | `{none, squeez}` |
| Reuse levels | `{0, 1, 2}`, ordered `0 -> 1 -> 2` |
| Task population | Five fixed tasks in every cell; two eligible and three `not_applicable` for the primary cache denominator |
| Concurrency | `1` |
| Planned initial denominator | 10 valid cycles; 60 useful bundles; 300 task trials |
| Maximum stability extension | 20 valid cycles; extension only if the predeclared stability rule required it |
| Provider result source | API-reported usage from successful provider calls |
| Cost source | API-reported usage multiplied by the admitted fixed price schedule |
| Invoice source | `not_measured` |
| Failure treatment | Prefix drift stops before dispatch; invalid cycles and their technical cost are preserved; no outer retry of a started provider attempt |
| Public evidence grade | Sanitized aggregate and hash-only evidence; no raw prompt, response, endpoint, credential, private path, or private resource identifier |

## Execution result

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

## Usage, cost, and quality

| Provider-reported usage | Tokens | Provenance |
|---|---:|---|
| Input | 65,423 | API-reported, partial invalid cycle |
| Cached input | 0 | API-reported, partial invalid cycle; not a Cache-effect estimate or miss rate |
| Output | 9,690 | API-reported, partial invalid cycle |

| Calculated amount | USD | Meaning |
|---|---:|---|
| Input cost | $0.1635575 | API-reported input usage multiplied by the fixed admitted prices |
| Output cost | $0.14535 | API-reported output usage multiplied by the fixed admitted prices |
| Total calculated cost | $0.3089075 | Preserved technical cost for the partial invalid cycle |
| Invoice | `not_measured` | No reconciled billed amount was measured |

Five completed task trials produced native quality outcomes, and 3 of 5 passed.
The sixth started task trial was incomplete. These outcomes describe only the
completed trials before the integrity stop; they do not form a condition,
reuse, rank, non-inferiority, or general quality comparison.

## Why the cycle stopped

**Observation.** The `none`, reuse `0` bundle completed. During `none`, reuse
`1`, `cancel-async-tasks` reached logical request ordinal `3`, while its reuse
`0` predecessor had only `2` requests. Prefix validation therefore had no
same-task predecessor at ordinal `3` and rejected the request before provider
dispatch. The cycle was preserved as invalid. No outer retry or replacement
was performed.

**Possible explanation.** The request count differed between the two task
executions. Temperature `0` was configured, but that setting does not establish
deterministic request counts. A non-deterministic execution path could produce
this pattern, but the run did not test that explanation.

**Limit.** The run did not isolate why the request widths differed. The evidence
does not attribute the difference to the model, task, transport, namespace,
compression, or another mechanism. With zero valid cycles, the run cannot
support a cache comparison, a Cache-effect estimate, a reuse contrast, or the
predeclared stability comparison. The extension did not run.

## Safety controls

The following values were hard execution ceilings derived from the source and
fixed price schedule. They were controls, not forecasts, spend, or an invoice.

| Control | Sealed value |
|---|---:|
| Per-task ceiling | $1,202.4576 |
| Per-bundle ceiling | $6,012.288 |
| Maximum 20-cycle design ceiling | $721,474.56 |
| Run deadline | `2026-10-10T10:48:45.452539Z` |

Actual calculated cost before the integrity stop was `$0.3089075`.

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

This report is post-snapshot material. It does not modify the preserved English
snapshot or the Korean experiment records. See the
[Cache-reuse execution contract](../../../../docs/cache-reuse.md) for the public
design boundary.
