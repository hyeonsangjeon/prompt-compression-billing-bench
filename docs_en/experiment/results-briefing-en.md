# Token Compression and Cost: First-Study Results Briefing

**In this 26-task run, calculated API cost was 16.5% lower with LLMLingua-2 and 4.6% lower with Headroom than with no additional compression, while squeez was 18.6% higher.**

These are observations from one run per task and condition. They do not establish causal compression savings, retained quality, or a product ranking. This English report is available at [results-briefing-en.md](results-briefing-en.md), the CSV version of the main table is [results-briefing-en.csv](results-briefing-en.csv), and the underlying first-study record starts at the [English preliminary-comparison overview](01-preliminary-comparison/README.md).

> **Measurement conditions**
>
> Terminal-Bench 2.1; the same 26 tasks under four conditions, one run per task and condition, for 104 completed task runs. Execution ran on 2026-09-16-17 UTC. Requests used `gpt-5.4`; the provider reported `gpt-5.4-2026-03-05`. The conditions were no additional compression, squeez, Headroom paths-only, and LLMLingua-2. Costs were calculated from provider-reported usage with the fixed price schedule for those records, not reconciled to an invoice, and exclude server costs.

<a id="summary"></a>
<a id="cost"></a>

## 1. How calculated API cost differed by compression condition

| Compression condition | Grader passes out of 26 | Runs with changed input out of 26 | Calculated API cost | Difference from no additional compression |
|---|---:|---:|---:|---:|
| No additional compression | 11/26 | 0/26 | $5.62 | Reference |
| squeez | 10/26 | 1/26 | $6.66 | +18.6% |
| Headroom | 9/26 | 4/26 | $5.36 | −4.6% |
| LLMLingua-2 | 10/26 | 18/26 | $4.69 | −16.5% |

The percentage differences use the unrounded cost values in the public aggregate: `5.61866`, `6.663187`, `5.3620835`, and `4.689458` USD. The displayed dollar amounts are rounded to cents. The CSV keeps both computation-friendly values and display strings.

## 2. Token, request, and cost components

Provider-reported total input already includes cached input. Cached input is a subset of total input, not an extra quantity to add again.

| Compression condition | Total API input tokens | Cached input tokens (subset of total input) | Output tokens | Logical model calls | Delivered responses |
|---|---:|---:|---:|---:|---:|
| No additional compression | 3,530,471 | 2,276,224 | 127,599 | 253 | 253 |
| squeez | 4,913,043 | 3,543,168 | 156,847 | 277 | 277 |
| Headroom | 2,392,382 | 1,117,568 | 126,377 | 208 | 208 |
| LLMLingua-2 | 3,674,861 | 2,769,536 | 115,584 | 289 | 289 |

The cost calculation applies separate rates to uncached input, cached input, and output tokens. For example, the token-component recomputation differs from the public precise cost total by USD 0.000007; the cents display is unchanged. The condition-level comparisons above use the public precise costs.

## 3. What changed, and what did not follow from it

The compression tools changed recorded input in 23 compressed-condition runs: squeez in 1 of 26, Headroom in 4 of 26, and LLMLingua-2 in 18 of 26. Those 23 changed comparisons belong to 18 tasks. Cost was lower than the no-additional-compression run in 14 comparisons and higher in 9.

The 209 changed spans had local `o200k_base` token counts of `97,723 -> 50,824`, about 48% lower within those spans. That denominator is only the spans whose strings changed. It is not a 48% reduction in overall provider input, calculated API cost, or an invoice.

**Observation.** In this one-repeat cohort, lower local tokens in changed spans did not map cleanly to lower total calculated API cost. LLMLingua-2 had slightly higher total provider input than no additional compression but lower calculated API cost. Headroom had much lower total provider input but only a small cost decrease.

**Possible explanation.** Cached-input share, output tokens, request count, and execution path can move the final cost in different directions.

**Limit.** This run did not isolate those mechanisms or control cache state, request count, execution path, or cross-condition concurrency. It cannot attribute the cost differences to compression alone.

## 4. Limits on interpretation

- One repetition cannot establish causal compression savings, retained quality, or a product ranking.
- The task grader produced 9-11 passes per condition, but that does not establish quality non-inferiority. A separate baseline found a verifier false-failure case, so pass and wrong-answer values should be read as the task grader's judgment.
- The 48% changed-span local-token reduction is not an overall input or cost reduction.
- Calculated API cost is provider usage multiplied by a fixed price schedule for these records. It is not an invoice and excludes server costs.
- The study does not show whether customer work would save money. A production estimate would need that workload's input, cached-input, output, retry, and pricing conditions.

## 5. Follow-up status kept separate from the first-study table

Later follow-up attempts did not produce comparable effect results and are not part of the first-study cost table. The cache-reuse follow-up reached 18 successful calls but produced zero valid comparisons. The SWE-Lancer follow-up produced zero valid records. Those records do not support a cache effect, compression effect, pass-rate conclusion, model-quality conclusion, or ranking.

## Evidence reference layer

| Evidence item | Public location and protected detail |
|---|---|
| Aggregate values used in this briefing | [`data/experiment/preliminary-comparison-summary.json`](../../data/experiment/preliminary-comparison-summary.json), derived from `docs/experiment/01-preliminary-comparison/plain-language-results-20260917.md` with source SHA-256 `d07735db90578f2646f97399485d26a8900ff96f93ff775cbcfb8dccb5beaae8` |
| English first-study overview | [`docs_en/experiment/01-preliminary-comparison/README.md`](01-preliminary-comparison/README.md) |
| Condition-level technical evidence | [`docs_en/experiment/01-preliminary-comparison/preliminary-comparison-20260916.md`](01-preliminary-comparison/preliminary-comparison-20260916.md), including comparison ledgers such as `preliminary-20260916T022024Z-c68388c9`, `preliminary-candidate-continuation-20260916T034044Z-a7387c9f`, and the continuation records listed per task |
| Token/cost relationship records | [`docs_en/experiment/01-preliminary-comparison/metrics.md`](01-preliminary-comparison/metrics.md) and [`docs_en/experiment/01-preliminary-comparison/preliminary-comparison-20260916.md`](01-preliminary-comparison/preliminary-comparison-20260916.md) |
| Follow-up status records | [`docs_en/experiment/02-follow-up/cache-reuse/execution-20260923.md`](02-follow-up/cache-reuse/execution-20260923.md) and [`docs_en/experiment/02-follow-up/swe-lancer/fixed-trace-20260923.md`](02-follow-up/swe-lancer/fixed-trace-20260923.md) |

<!-- Source scope: English briefing created from existing public aggregate and first-study records only. No new execution. -->
