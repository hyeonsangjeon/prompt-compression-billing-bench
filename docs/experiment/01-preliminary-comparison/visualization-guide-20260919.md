# Visualization Appendix: Reading the Figures Without Overclaiming

Use this document after the [plain-language guide](plain-language-results-20260917.md) and
[design-review appendix](experiment-briefing-20260919.md) to see the full set of figures.
**Exploratory data analysis (EDA)** examines input size and composition before the main
experiment. A **native run** has the actual model solve a task and the task's built-in
grader check the answer.

A **condition** is one way to solve the same problem. `none` means a reference without
additional compression, not that no work occurred. The external model **provider** handles
API requests. **API usage** is the provider-reported total of input, cached-input, and
output tokens.

## 30-Second Reading Guide

1. Start with the measurement flow. Samples and units differ by stage, so do not add their numbers.
2. The 10 EDA figures describe historical input composition and candidate scope. They are not achieved compression or quality results.
3. The 6 preliminary-comparison figures show only the evidence-complete **26 tasks and 104 conditions**. One run per condition cannot establish ranking, causality, or non-inferiority.
4. Local tokens in changed spans, full API usage, and calculated cost from usage times a price table are different measurements. All also differ from an invoice.

> **Citation rule:** Do not cite a figure number alone. Include its sample, denominator,
> unit, and “does not establish” statement. Use `0` only where zero was observed; do not
> convert unmeasured, unsampled, or source-missing states to zero.

## Measurement Flow

The [text-based Mermaid flow in the briefing](experiment-briefing-20260919.md#measurement-sequence)
shows EDA → baseline → static measurement → native preliminary comparison → current
conclusion.

| Item | Description |
|---|---|
| Sample | EDA: 5 tasks, 15 runs, 56 requests; baseline: 5 tasks × 20; static: 56 stored requests; preliminary comparison: 26 tasks and 104 conditions |
| Denominator and unit | Differ by stage; tasks, runs, requests, and conditions are not combined |
| Observation | Evidence answering different questions accumulated in this order |
| Does not establish | That later stages performed better or that compression caused an effect |

**SHA-256 check** for the design-review appendix:
`0f79852691b64fe7cdd4bc1202345b67acd487dcba050416e6f2e8f901230e9e`

## Ten EDA Figures

The figures follow the order and SHA-256 values pinned in the
[EDA figure manifest](../../eda/manifest.json).

### EDA 1. Task-Type Distribution

![Primary task-type distribution for official English instructions: DeepSWE n=113 and Terminal n=89. Each task counts once under its primary type; one mixed review-and-modification task retains a secondary label.](../../eda/figures/round2/01-task-types.svg)

*EDA Figure 1. The same primary-type classification is applied to 113 DeepSWE tasks and
89 Terminal-Bench 2.1 tasks.*

| Item | Description |
|---|---|
| Sample | 113 DeepSWE tasks and 89 Terminal tasks |
| Denominator and unit | Task count in each benchmark; tasks / % |
| Observation | The two task sets have different type composition, and mixed tasks retain classification ambiguity |
| Does not establish | Model performance, compression rate, or which benchmark is better |
| Source SHA-256 | `8a2f83048fcdc865b36152c96ead0f796a125bb5e208af9483bda14f51328236` |

### EDA 2. Repository, Language, and Author Classification

![Repository and primary-language distribution for 113 DeepSWE tasks and category and difficulty distribution for 89 Terminal tasks. Difficulty is author metadata, not a model-performance measurement.](../../eda/figures/round1/05-corpus-bias.svg)

*EDA Figure 2. Metadata aggregation shows concentrations by repository, language, and
author-provided classification.*

| Item | Description |
|---|---|
| Sample | 113 DeepSWE tasks and 89 Terminal tasks |
| Denominator and unit | Task count in each benchmark; tasks / % |
| Observation | Repository, language, type, and author-provided difficulty distributions are uneven |
| Does not establish | Difficulty for this model or population representativeness |
| Source SHA-256 | `29e95d987133ac1405a85a0d77a9249783eb7136d16242d8b66cf66cc14887f7` |

### EDA 3. Official Instruction Size

![Distributions of instruction UTF-8 bytes and local tokens for 113 official DeepSWE tasks and 89 Terminal tasks. These are not API-billed tokens.](../../eda/figures/round1/01-input-size.svg)

*EDA Figure 3. Official instruction-file size and local-token counts are plotted
separately.*

| Item | Description |
|---|---|
| Sample | 113 official DeepSWE tasks and 89 official Terminal tasks |
| Denominator and unit | Instruction files; UTF-8 bytes / local `o200k_base` tokens |
| Observation | Instruction size and local-token count vary widely by task |
| Does not establish | API-billed tokens, full live-request size, or cost |
| Source SHA-256 | `0e031cbf23bcfdfb4ed0f689c484fde0d185d88fc7e65730032bb18851c0dd7f` |

### EDA 4. Input Size by Task Type

![Input-size distributions separated among static DeepSWE n=113 tasks, Terminal n=89 tasks, and 56 historical Terminal requests. Values are UTF-8 bytes and local o200k_base tokens, not API tokens.](../../eda/figures/round2/03-input-size-by-type.svg)

*EDA Figure 4. Official instructions and historical live requests remain separate in
size distributions by type.*

| Item | Description |
|---|---|
| Sample | 113 official DeepSWE tasks, 89 official Terminal tasks, and 56 historical Terminal requests |
| Denominator and unit | Instruction / message content; UTF-8 bytes / local tokens |
| Observation | Size distributions differ by input and task type |
| Does not establish | API input tokens, billed cost, or compressibility |
| Source SHA-256 | `e86b10585914a2d2e8f70c2ddfaaebb1d3bc1ac9729d4429a9bc000a431abf60` |

### EDA 5. Message-Content Composition

![Content-span shares for 113 and 89 static instructions and 56 historical Terminal live requests. Each layer uses total UTF-8 content bytes as its denominator and shows unclassified content separately.](../../eda/figures/round1/02-input-composition.svg)

*EDA Figure 5. Instruction and request content is classified by span type and compared by
UTF-8 byte share.*

| Item | Description |
|---|---|
| Sample | 113 and 89 official instructions; 56 Terminal live requests |
| Denominator and unit | Total message-content UTF-8 bytes in each input layer; % |
| Observation | Official instructions and live requests have different content composition |
| Does not establish | That a span can be safely deleted or an achieved compression rate |
| Source SHA-256 | `57aa286750015af99651a230834ed458a20936a0afa189cbcb8c32bb9a98440c` |

### EDA 6. First-Pass Candidate Share by Task

![Task-level shares of first-pass log candidates, unclassified spans, and protected spans across 56 requests from 5 Terminal tasks and 3 runs per task. This is content-byte composition, not a compression result.](../../eda/figures/round1/03-compressible-share.svg)

*EDA Figure 6. First-pass candidates, unclassified spans, and protected spans are separated
across five purposively selected tasks.*

| Item | Description |
|---|---|
| Sample | 5 tasks, 3 runs each, 56 requests |
| Denominator and unit | Total task-level message-content UTF-8 bytes; % |
| Observation | Byte share classified as a candidate varies widely by task |
| Does not establish | Actual compression, safety, quality, or representative-sample savings |
| Source SHA-256 | `dea914de8808b7ec7746d01f0b60af449a38ada5473cfce3f3ca4f49ee52f5f6` |

### EDA 7. Reclassification of Unclassified Spans

![Decomposition of 58 distinct unclassified types, 168 occurrences including retransmission, and 158,258 bytes. The historical sample has n=56 requests and n=5 tasks; values are not API tokens or achieved savings.](../../eda/figures/round2/04-unknown-decomposition.svg)

*EDA Figure 7. The 158,258 bytes initially left unclassified are divided into seven
categories.*

| Item | Description |
|---|---|
| Sample | 58 distinct types, 168 occurrences including retransmission, 56 requests, 5 tasks |
| Denominator and unit | 158,258 unclassified bytes / 824,301 total message-content bytes |
| Observation | Previously unclassified content included both candidates and protected material |
| Does not establish | API-token share, achieved savings, or classification accuracy on other requests |
| Source SHA-256 | `47970d1c9203dc4d838930271e9e8c6518725c1289aa77fd4d5d6a04a07bc841` |

### EDA 8. Candidate Share by Task Type

![Candidate and content composition by type for 5 historical Terminal tasks, 15 runs, and 56 requests. Values use UTF-8 bytes; unsampled types such as debugging and review remain unmeasured.](../../eda/figures/round2/02-candidate-share-by-type.svg)

*EDA Figure 8. First- and second-pass candidate shares are compared by task type while
mixed-code spans remain protected.*

| Item | Description |
|---|---|
| Sample | 5 Terminal tasks, 15 runs, 56 requests |
| Denominator and unit | Total message-content UTF-8 bytes by type; % |
| Observation | Candidate share in this purposive sample was 0.48%–35.29% by task and 15.42% overall |
| Does not establish | Values for unsampled types, achieved compression, or that every candidate can be deleted |
| Source SHA-256 | `89cfaf57fc4c59ff8afd5c71fa6f64bf2c5c7fbf044fd799c21d29f0b0d3ff61` |

### EDA 9. Local Tokens Versus API Input Tokens

![Comparison between local message-content tokens and actual API input tokens across 56 historical requests from 5 Terminal tasks and 15 runs. The dashed line is calculated y=x; the right panel shows the difference distribution.](../../eda/figures/round1/06-api-token-calibration.svg)

*EDA Figure 9. Local content tokens and provider-reported API input tokens are compared
for the same historical requests.*

| Item | Description |
|---|---|
| Sample | 5 Terminal tasks, 15 runs, 56 requests |
| Denominator and unit | Requests / runs; API usage tokens / local content tokens |
| Observation | The token counts are close but not identical |
| Does not establish | Invoice reconciliation, new-run token counts, or compression savings |
| Source SHA-256 | `70b9a531e5bfa66d5264fd04241c229f0b4ac04b03f923373a567ed11ae48cca` |

### EDA 10. Shared Leading-Token Length

![Distribution of shared leading local token-ID lengths among pairs of official task instructions and live Terminal requests. The 1,024 dashed line is a reference for the GPT-5.4 service's cache minimum at the time, not a direct measurement of service cache prefixes.](../../eda/figures/round1/04-shared-prefix.svg)

*EDA Figure 10. The calculation counts how many local token IDs are shared from the
beginning of each instruction or request pair.*

| Item | Description |
|---|---|
| Sample | 6,328 / 3,916 static-instruction pairs and 41 / 10 / 15 historical-request pairs |
| Denominator and unit | Pair count by comparison layer; shared leading local token-ID length |
| Observation | Shared-prefix length distributions differ across comparison layers |
| Does not establish | Actual cache hits, cache billing, or independent samples |
| Source SHA-256 | `94f9a6f0c510530c676bafffd5f059e81a31345f9454510192a5f6c649a724e4` |

## Six Preliminary-Comparison Charts

All charts were drawn from the
[public aggregate JSON](../../../data/experiment/preliminary-comparison-summary.json) by
the [generation code](../../../src/experiment_figures.py). The aggregate JSON SHA-256 is
`28805f13df16c734e4e65aa4f6c323d885e605222754366cf4d3eea361d171c7`,
and the source tables appear in the [plain-language results](plain-language-results-20260917.md).

### Result 1. Quality Judgments

![Condition-level counts of pass and wrong_answer across 104 conditions from one run of four conditions on 26 tasks. Five technically incomplete runs are excluded; this is not a compressor ranking.](../../../figures/preliminary-quality.svg)

*Result Figure 1. The 104 evidence-complete conditions contain 40 `pass` and 64
`wrong_answer`, separated by condition.*

| Item | Description |
|---|---|
| Sample | 26 tasks × 4 conditions = 104 conditions; one run per condition |
| Denominator and unit | 104 completed conditions; condition count |
| Observation | Pass counts were none 11, squeez 10, Headroom 9, and LLMLingua-2 10 |
| Does not establish | Compressor ranking, quality non-inferiority, or compression as the cause |
| SVG SHA-256 | `783a322fd547a80088e84c7b2aba4e56b042838d0347b0a8a2460a045274fc56` |

### Result 2. Conditions With String Changes

![Counts of conditions with and without string changes across 104 completed conditions. Change status does not establish the cause of quality or cost.](../../../figures/preliminary-changed-conditions.svg)

*Result Figure 2. Actual strings changed in 23 of 104 conditions and remained unchanged
in 81.*

| Item | Description |
|---|---|
| Sample | 26 tasks × 4 conditions = 104 conditions; one run per condition |
| Denominator and unit | 104 completed conditions; condition count |
| Observation | Changed conditions: none 0, squeez 1, Headroom 4, LLMLingua-2 18 |
| Does not establish | Change size, quality effect, or reduced API usage |
| SVG SHA-256 | `16d5032ed5efff1437eaf8a415e97e4830bf88b7a46e93161fba1ec0266d527f` |

### Result 3. Actually Changed Spans

![Counts of actually changed spans by condition, confirmed from retained source. Span count differs from condition count, and 166 source-missing records are not treated as zero.](../../../figures/preliminary-changed-spans.svg)

*Result Figure 3. The 209 actually changed spans are separated by condition. Of 738
comparable pairs, 529 were unchanged; 166 without source remain unmeasured.*

| Item | Description |
|---|---|
| Sample | 738 pairs comparable from retained source; 209 changed |
| Denominator and unit | Confirmed changed spans by condition; span count |
| Observation | Changed spans: none 0, squeez 2, Headroom 53, LLMLingua-2 154 |
| Does not establish | Values for 166 missing pairs, full-request token reduction, or safety |
| SVG SHA-256 | `3b5c6c1ffeb1311beefd7f7ce53feb5fee70bfa41dbcee555a7289969e90cc45` |

Recounting only the 209 changed spans with local `o200k_base` gives
`97,723 → 50,824` tokens. This is not the denominator of the API-usage chart.

### Result 4. Request and Response Events

![Separate counts of logical model requests, provider HTTP attempts, successful responses, and task-delivered responses across 104 completed conditions. Each total is 1,027, but they are not the same event or a completion rate.](../../../figures/preliminary-request-events.svg)

*Result Figure 4. The four counters happened to have matching condition-level values and
totals, but represent receipt, external send, successful receipt, and task delivery.*

| Item | Description |
|---|---|
| Sample | 104 evidence-complete conditions |
| Denominator and unit | Recorded occurrence of each event; event count |
| Observation | Each of the four counters totaled 1,027 |
| Does not establish | Task completion rate, proximity to an answer, or conceptual equivalence of the events |
| SVG SHA-256 | `be8d2738f784cf7fb6581f20c9f8f0da799242cda56e9fd619cf4771f4e81e06` |

### Result 5. Full API Usage

![Provider-reported input, cached-input, and output tokens by condition across 104 completed conditions. This scope differs from local tokens in changed spans.](../../../figures/preliminary-provider-usage.svg)

*Result Figure 5. Full API usage totaled 14,510,757 input tokens, including 9,706,496
cached-input tokens, and 526,407 output tokens.*

| Item | Description |
|---|---|
| Sample | 104 evidence-complete conditions |
| Denominator and unit | Full provider-reported usage by condition; tokens |
| Observation | Request count and input, cached-input, and output tokens differed by condition |
| Does not establish | Changed-span tokens, cache control, or invoice reconciliation |
| SVG SHA-256 | `8e814c4e7605b25e6dc8c2ad1e64285f3bdfb2652e79a5e47aad2b3ba2e4e5e8` |

### Result 6. Calculated API Cost

![Calculated US-dollar cost by condition from provider usage across 104 completed conditions and a fixed price table. This is not invoice-reconciled spend or a compression-savings rate.](../../../figures/preliminary-calculated-cost.svg)

*Result Figure 6. Applying the fixed price table to API usage gives `$22.3333885` in
total. It was not reconciled to an actual invoice.*

| Item | Description |
|---|---|
| Sample | 104 evidence-complete conditions |
| Denominator and unit | API usage × price table by condition; USD |
| Observation | none `$5.6186600`, squeez `$6.6631870`, Headroom `$5.3620835`, LLMLingua-2 `$4.6894580` |
| Does not establish | Invoice amount, savings caused by compression, or a product-adoption ranking |
| SVG SHA-256 | `949a24e9c4072f8fe21cefbdef2c7fa827a1734c0291ba06ba1f9329a6867725` |

## Claim Scope for These Figures

| Supported | Not yet supported |
|---|---|
| Input composition and candidate-byte scope in the purposive sample | Achieved compression rate in a representative population |
| Observed judgments, changes, requests, usage, and calculated cost across 26 tasks and 104 conditions | Compressor ranking, causal effects, or quality non-inferiority |
| Separation of measurements with different units and denominators | Converting changed-span tokens into API usage or an invoice |
| The five long runs were separate, quality-unknown executions | `pass` or `wrong_answer` for operator-stopped executions |

## Next Reading

1. Use the [technical preliminary-comparison evidence](preliminary-comparison-20260916.md) for condition-level execution identifiers, restoration regrading, and remote hashes.
2. Use the [one-task YAML walkthrough](../../../README.md#try-it-in-five-minutes) to see the default no-call check and explicit `--execute` boundary.
3. Before execution, review the [public and private classifications](../../publication.md) and [currently unsupported scope](../../../STATUS.md).
