# Preregistered Compression Evaluation Protocol

**Status:** This protocol records the statistical rules and policy thresholds fixed on 2026-09-15 UTC. The preregistered repeated evaluation was not run. If it is resumed separately, the task set, repetition count, and manifest must be frozen before results are viewed, together with the [schema version 4 safety policy](execution-safety-policy.md).

## Evaluation Question

For the exact Terminal-Bench 2.1 tasks that pass screening, is there a compressor that reduces directly attributable execution cost by more than 10% while limiting quality degradation to no more than 5 percentage points when only harness-identified log-like command output is compressed?

The 5-percentage-point and 10% values are policy thresholds preregistered for this study. They are not customer-agreed values and are not relaxed to fit results or schedule. If no compressor satisfies both, the record will state that adoption evidence was not established for this set of task IDs, model, price table, and profiles.

## Comparison Conditions

All four conditions use the same tasks, model, runner, concurrency, and application location. Code, instructions, noncandidate spans of user messages, and assistant history remain unchanged.

| Condition | Tool and version | Fixed profile | Actual intervention |
| --- | --- | --- | --- |
| `none` | In-house adapter | Same identification and protection checks; pass candidate text unchanged | No additional compression |
| `squeez` | squeez `1.48.4` | Fresh state; delete content after the first 30 content lines | Lossy compression that discards trailing content |
| `headroom` | Headroom `0.36.5` | Paths-only profile revision 2 with reverse-transformation check | Notational compression that groups common path prefixes |
| `llmlingua2` | LLMLingua-2 `0.2.2` | `rate=0.5`, revision `ebaba9b0e874dadd3003ffcff828e4397e568089`, CPU float32, no adapter character cap | Token-selection-based lossy compression |

Application remains fixed to command output classified by the current classifier as log-like. Structured output, file reads, and code are not added to this matrix. DeepSWE, protection-bypass tests, compression-intensity changes, and Headroom `0.37.0`'s `coding` profile are separate questions and are not mixed into this comparison.

Since 2026-09-15 22:40 KST, the LLMLingua-2 adapter passes each identified candidate string in full rather than truncating it at 5,000 characters. The observation that 31 of 79 candidate occurrences in the existing 100 uncompressed runs exceeded 5,000 characters describes only the reach of the removed adapter boundary. Historical static reduction and latency values are not transferred to the current uncapped profile.

## Shared Execution Conditions

| Item | Value |
| --- | --- |
| Model | `gpt-5.4`; verify the provider-returned revision for every request |
| Request settings | temperature `0`, reasoning effort `none`; output limit 2,048 tokens |
| Runner | Harbor `0.22.0`, instrumented Terminus 2 |
| Concurrency and provider constraints | 8; record provider throughput limits and service errors separately from schema version 4 safety limits |
| Tasks | All of the exact `K` task IDs that pass screening |
| Location | Identified log-like command output |
| Local token calculation | tiktoken `0.14.0`, `o200k_base` |
| Prices | Price table in one currency and at one point in time, fixed in the execution manifest |

temperature and reasoning effort are recorded without claiming provider determinism. Cached-input tokens are observed but not claimed as a controlled factor.

## Condition Order

Each repetition of each task contains `none`, `squeez`, `headroom`, and `llmlingua2` once. Their order is determined by a SHA-256 sort over fixed seed `20260915`, task ID, repetition number, and condition name. Condition counts remain balanced within every task and repetition, and both planned and actual start order are recorded.

At concurrency 8, conditions with different durations may have different numbers of concurrent executions. A balanced planned order makes this observable but does not remove provider-state or temporal correlation.

## Quality and Cost Effects

The sign of the quality effect is `compression-condition pass rate - none pass rate in the same repetition`. The unit is percentage points; a positive value means higher quality. First compute each task's mean across repetitions, then weight each of the `K` tasks by `1/K`.

The sign of the cost effect is `1 - compression-condition cost ÷ none cost`. A positive value means cost savings. For each task, compute the mean repetition-level cost ratio, then weight each of the `K` tasks by `1/K`. A 10% saving means that end-to-end directly attributable cost is 10% lower than `none`.

Apply the same cost contract to all four conditions:

- Provider usage multiplied by fixed prices
- Directly attributable shares of VM and worker time while actually active
- Measurable Blob writes, verification reads, and network transfer
- Costs from quality failures and all permitted retries

Do not multiply the full VM rate by every worker. Divide VM time among concurrently active executions and reconcile allocations to the total. Shared idle time, approval waits, and one-time preparation are recorded separately and excluded from the primary cost effect.

Provider cost is calculated from response usage and the fixed price table; it is not invoice reconciliation. Input tokens, cached-input tokens, output tokens, and local tiktoken counts remain separate.

## Repetition Count

The plan uses a quality tolerance of 0.05, a one-sided significance level of `0.05/3` per compressor for three compressor comparisons, target power 0.8, and quality-difference variance 0.40.

```text
Target number of required quality pairs
= ceil[0.40 × {z(1 - 0.05/3) + z(0.8)}² ÷ 0.05²]
= 1,412

Repetitions per task R(K) = ceil(1,412 ÷ K)
Actual pairs per comparison = K × R(K)
Planned logical trials = 4 × K × R(K)
```

`z(p)` is the p quantile of the standard normal distribution. Variance 0.40 is a stress assumption for planning, not an observation, upper bound, or guarantee of power. The 1,129-pair value from variance 0.32 remains only a sensitivity reference.

Evaluation is impossible when `K=0`. After screening, substitute only `K` into the formula; do not change 0.40, 1,412, the quality and cost thresholds, or the calculation method. Because repetition count was planned for quality, it does not guarantee cost power. If the cost confidence interval is too wide to decide, repetitions are not added after evaluation.

## Confidence Intervals and Adoption Decision

The primary analysis uses 50,000 percentile-bootstrap draws. The resampling unit is one complete repetition containing all `K` tasks and all four conditions. Move `none` and the three compression conditions together within a repetition to preserve pairing and shared-`none` correlation. Tasks are not resampled, so the conclusion is conditional on the exact selected task-ID set.

The one-sided significance level is `0.05/3` for each compressor. A compressor meets the adoption criterion only if both lower bounds strictly exceed their thresholds:

```text
One-sided 98.333% lower bound for quality difference > -0.05
One-sided 98.333% lower bound for cost savings > 0.10
```

Quality and cost form an intersection decision for one compressor, so significance is not split again between them. Under the chosen correction and valid component confidence-interval assumptions, this rule places the nominal family-wise error rate for all three compressor-adoption claims at no more than 5%. It does not establish the bootstrap's actual coverage.

A lower bound equal to or below its threshold means the adoption criterion was not established; it does not establish quality degradation. Two-sided 98.333% intervals are also reported for description. Because they allocate `(0.05/3)/2` to each tail, they are more conservative than the adoption decision and are not called simultaneous 95% intervals for all six effects.

If a bootstrap distribution has zero width or contains nonfinite values, the result is indeterminate. With few repetitions and identical outcomes in every repetition, a percentile bootstrap can degenerate or have inadequate coverage. Do not automatically substitute another interval or add repetitions after the fact.

## Temporal-Correlation Sensitivity

The primary analysis assumes complete repetitions are mutually independent. Residual correlation from provider state and time of day has not been estimated from current data.

The sensitivity analysis uses a circular moving-block bootstrap of length 2. Sample repetition starting positions uniformly, wrap consecutive pairs circularly, and truncate at `R`. If the primary and sensitivity adoption decisions differ, report the difference and do not claim robust adoption. The sensitivity result does not change the primary rule.

## Missing and Near-Zero Cost

A mean `none` task cost of `0.00000025 USD` or less is classified as a near-zero cost denominator. This value is the calculated price of one cached-input token under the fixed price table, not a universal statistical constant.

Record actual zero spend, missing instrumentation, unresolved provider cost, missing Blob-operation responses, and a missing price table as distinct states. Do not delete required missing costs or zero or near-zero denominators, and do not replace them with zero. The affected compressor-versus-`none` comparison is indeterminate; stop the full evaluation if a common cause damages all four conditions.

## Error-Rate Check With Synthetic Data

Run screening after environment and instrumentation verification inputs pass. After screening determines `K`, and before evaluation results are viewed, calculate `R(K)` and run the following synthetic-data checks:

- Quality exactly at its tolerance boundary while cost passes
- Cost exactly at its 10% boundary while quality passes
- Both quality and cost exactly at their boundaries
- Shared `none`, temporal shocks, and heavy-tailed cost distributions
- Only valid joint distributions, with quality-difference variance 0.10, 0.32, and 0.40 and temporal-copy probability 0, 0.025, and 0.05

Generate 2,000 synthetic datasets per scenario and apply 50,000 bootstrap draws to each. Independent validation seed is `2026091501`. Record the execution source commit, NumPy version, quantile method, and purpose-specific child seeds.

Within each boundary scenario, evaluation may proceed only if the exact one-sided 95% binomial upper bound for the proportion of synthetic datasets that falsely adopt at least one compressor is at most 0.05. This is a strict operating criterion for the specified synthetic scenarios, not a universal coverage proof. If it fails, do not repeatedly tune the method on the same synthetic data. Record the cause, corrected revision, and separate validation seed. Recalculate the 1,412-pair plan if the significance level or method changes.

## Schedule Calculation

The P50 and P90 values below are projections using individual-trial durations of 76.145 and 93.559 seconds from the existing 100 `none` runs. They are not observed P50 and P90 values for the full evaluation.

```text
native time(q) = ceil(4 × K × R ÷ 8) × none trial time(q) × 1.4345
additional LLMLingua-2 latency(q) = parallel execution interval of actual uncapped per-candidate compression wall times
```

The factor 1.4345 is the observed interval for the prior 100 runs divided by `sum of individual durations ÷ 8`. The value 0.79 is not a probability; it extrapolates 79 identified candidate occurrences per 100 logical trials to the new evaluation. Under the removed 5,000-character cap, 8 concurrent LLMLingua-2 calls had P50 260.668 seconds and P90 260.912 seconds. This measurement excludes uncapped candidate lengths, worker initialization, first image preparation, preparation retries, candidate-arrival spacing, and different candidate distributions in new tasks, so it is not used as the current LLMLingua-2 schedule value.

Software preflight showed that the processing interval for 8 candidate occurrences did not exceed 0.21 seconds for either squeez or Headroom. This is calculated as separate added latency rather than converted to zero. Preparation-retry time has not been measured, so it remains symbolic in the worst-case expression.

The reporting target at the time was `2026-09-16 23:59 KST`; it was not a task-process termination timer. A future schema version 4 run uses an approved UTC deadline independent of the reporting schedule. If the full `K`-task evaluation does not fit the target, do not automatically select a subset or lower thresholds; record the smallest feasible design revision instead.

## Entry Criteria

- The exact screened task-ID set and `K` are hash-pinned.
- `R(K)`, four-condition order, and every trial ID are frozen in the execution manifest.
- Cost-verification inputs pass under the same source commit and price table.
- Per-attempt and full-run calculated API cost limits and a future UTC deadline are approved, and safety-policy checks pass.
- The synthetic-data error-rate check using `K` and `R(K)` meets the entry criterion.
- The P90-input projection includes preparation, retries, and compressor latency and is checked against the execution deadline.
- A coordinator reviews screening results, validation results, and schedule records and records whether evaluation may begin.

Do not change tasks, repetition count, seed, confidence interval, cost contract, or thresholds after evaluation results are viewed.
