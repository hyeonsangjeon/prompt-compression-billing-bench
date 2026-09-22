# Shareable Plain-Language Guide to the Preliminary Results

This guide lets a nonspecialist see the main point in 30 seconds. The result is not a
performance ranking of compressors. It records one attempt to solve the same problems in
four ways, whether each answer passed, and whether the input string actually changed.

For detailed execution values and SHA-256 checks, continue to the
[technical evidence](preliminary-comparison-20260916.md).

## 30-Second Summary

- **What was compared:** 26 tasks—each task is one problem—ran once under each of four
  conditions. That gives 104 conditions, not 104 independent problems.
- **Did the answer pass:** There were 40 `pass` results, meaning the built-in task grader
  passed them, and 64 `wrong_answer` results, meaning execution completed but the answer
  did not pass that grader.
- **Did the actual string change:** In 23 of 104 conditions, 209 spans changed. Recounting
  only changed spans gives `97,723 → 50,824` tokens.
- **How many request events occurred:** Requests sent to the model, external API-call
  attempts, successful responses, and responses returned to the task are distinct and
  were counted separately. Across 104 completed conditions, all four observed counts
  happened to equal 1,027.
- **Can a conclusion be drawn immediately:** No. Judgments sometimes differed despite zero
  actual string changes, and each condition ran only once. Cache and model execution path
  were uncontrolled, so the evidence does not establish compressor ranking,
  non-inferiority, population cost savings, or causes of quality and cost differences.
- **What happened to separate long runs:** Five tasks ended before grading, leaving quality
  unknown. An operator stopped four; one stopped while waiting for an HTTP response. They
  are not combined with the 26-task, 104-condition results.

## Terms to Know

| Term | Plain meaning | Quality result? |
|---|---|---|
| Task | One problem to solve | Not applicable |
| Condition | One way to solve the same problem; four conditions were compared per task | Not applicable |
| `none` | Does not mean no work. The model solves the task without **additional input compression**. | Not applicable |
| `pass` | Execution completed and passed the built-in task grader; regrading after workspace restoration agreed. | Yes |
| `wrong_answer` | Execution completed, but the answer did not pass the built-in task grader; distinct from a technical error or early stop. | Yes |
| Technical incompletion | Correctness cannot be judged because execution, communication, or evidence retention did not finish. | No |
| Operator stop | Technical incompletion caused by an operator's post hoc decision to stop an active task; not a preregistered quality-failure criterion. | No |
| Requests before/after | Values such as `291 / 290` are not completion rates. They count different events, such as requests sent and responses received. | Not applicable |
| Tokens in actually changed spans | Tokens recounted only where before and after strings actually differ. | Not applicable |
| API usage | Full input, cached-input, and output tokens reported by the model API; broader than changed-span tokens. | Not applicable |
| Calculated API cost | API usage multiplied by a fixed price table; not an invoice-reconciled amount. | Not applicable |
| Virtual-machine cost | Derived by applying an hourly rate to run time; distinct from API cost, with unresolved allocation where runs overlapped. | Not applicable |

## What Was Compared

The four conditions below were applied to each task. Task image, files, and grader stayed
the same, while each condition used a fresh container and workspace.

| Condition | Meaning in this document |
|---|---|
| `none` | Reference condition without additional compression |
| `squeez` | Compression condition using squeez |
| `Headroom` | Compression condition using Headroom |
| `LLMLingua-2` | Compression condition using LLMLingua-2 |

| Item | Measurement condition |
|---|---|
| Execution dates | 2026-09-16–17 UTC |
| Model | `gpt-5.4`; provider-reported `gpt-5.4-2026-03-05` |
| Generation settings | `temperature=0`, `reasoning_effort=none` |
| Sample | 26 tasks, one run per task and condition, 104 completed conditions |
| Quality checks | Built-in task grading, matching regrade after workspace restoration, and remote artifact hash verification |

This sample was not randomly selected to represent all 89 tasks. The selection path and
exact execution identifiers remain in the technical evidence.

## Observations

### How Many Conditions Passed?

This table counts only the 104 conditions that completed execution, grading, restoration
regrading, and remote verification. It excludes technical incompletions and operator stops.

| Condition | `pass` | `wrong_answer` | Total |
|---|---:|---:|---:|
| `none` | 11 | 15 | 26 |
| `squeez` | 10 | 16 | 26 |
| `Headroom` | 9 | 17 | 26 |
| `LLMLingua-2` | 10 | 16 | 26 |
| Total | 40 | 64 | 104 |

**Limitation.** Pass counts differ, but each condition ran only once. Those differences do
not establish which compressor is more accurate.

### How Much Did the Actual String Change?

| Condition | Changed conditions | Zero-change conditions | Actually changed spans |
|---|---:|---:|---:|
| `none` | 0 | 26 | 0 |
| `squeez` | 1 | 25 | 2 |
| `Headroom` | 4 | 22 | 53 |
| `LLMLingua-2` | 18 | 8 | 154 |
| Total | 23 | 81 | 209 |

There are 738 input-output pairs whose before and after values could be recomputed from
preserved source. Of these, 209 changed and 529 were identical strings. The 209 changed
spans had `97,723 → 50,824` tokens. Another 166 spans without raw pairs were not
calculated and were not changed to zero.

`97,723 → 50,824` counts **only spans whose strings changed**. It does not mean total API
input tokens or billed cost fell by that amount.

At least one compression-condition string changed in 18 tasks. All four conditions had
zero actual changes in these eight tasks: `cancel-async-tasks`, `dna-insert`,
`extract-elf`, `financial-document-processor`, `install-windows-3.11`,
`kv-store-grpc`, `openssl-selfsigned-cert`, and `sam-cell-seg`.

### Did Judgments Ever Differ When Strings Did Not?

Yes. Of 78 paired comparisons between the uncompressed reference and three compression
conditions, 10 had different judgments.

| Condition | `pass→pass` | `wrong_answer→wrong_answer` | Same judgment |
|---|---:|---:|---:|
| `squeez` | 9 | 14 | 23 |
| `Headroom` | 8 | 14 | 22 |
| `LLMLingua-2` | 9 | 14 | 23 |
| Total | 26 | 42 | 68 |

| Condition | `pass→wrong_answer` | `wrong_answer→pass` | Changed judgment |
|---|---:|---:|---:|
| `squeez` | 2 | 1 | 3 |
| `Headroom` | 3 | 1 | 4 |
| `LLMLingua-2` | 2 | 1 | 3 |
| Total | 7 | 3 | 10 |

**Observation.** All three squeez judgment changes and all four Headroom changes occurred
in conditions with zero actual string changes. The three LLMLingua-2 judgment changes
included actual changes. `llm-inference-batching-scheduler` and `build-pov-ray` changed
from `pass→wrong_answer`; `overfull-hbox` changed from `wrong_answer→pass`.

**Possible explanation.** Model execution path, request count, and cache state may have
differed by condition. This is a hypothesis for a repeated follow-up experiment.

**Limitation.** One run per condition cannot separate causes. Seven judgment differences
occurred with zero actual string changes, so judgment differences cannot be treated as a
direct effect of compression. Conversely, a changed string alone does not establish a
quality change.

### How to Read Requests, API Usage, and Cost

Suppose one condition records 3 logical model requests, 3 provider HTTP attempts, 3
successful HTTP responses, and 3 responses delivered to Harbor. Although all values are
3, they mean different things: receipt by the proxy, transmission to the external API,
receipt of a successful response, and delivery back to the task. `3 / 3` is not a
100%-complete progress indicator.

All four counters happened to match by condition in the 104 completed conditions. The
observation that values match remains distinct from a claim that the concepts are the same.

| Condition | Logical model requests | Provider HTTP attempts | Successful HTTP responses | Responses delivered to Harbor |
|---|---:|---:|---:|---:|
| `none` | 253 | 253 | 253 | 253 |
| `squeez` | 277 | 277 | 277 | 277 |
| `Headroom` | 208 | 208 | 208 | 208 |
| `LLMLingua-2` | 289 | 289 | 289 | 289 |
| Total | 1,027 | 1,027 | 1,027 | 1,027 |

API usage covers the full model-processed scope in each condition, not only changed spans.

| Condition | Input tokens | Cached tokens | Output tokens |
|---|---:|---:|---:|
| `none` | 3,530,471 | 2,276,224 | 127,599 |
| `squeez` | 4,913,043 | 3,543,168 | 156,847 |
| `Headroom` | 2,392,382 | 1,117,568 | 126,377 |
| `LLMLingua-2` | 3,674,861 | 2,769,536 | 115,584 |
| Total | 14,510,757 | 9,706,496 | 526,407 |

Calculated API cost applies the fixed price table to this usage. It is not invoice-reconciled.

| Condition | Calculated API cost | HTTP attempts | Cost per HTTP attempt |
|---|---:|---:|---:|
| `none` | $5.6186600 | 253 | $0.022208142 |
| `squeez` | $6.6631870 | 277 | $0.024054827 |
| `Headroom` | $5.3620835 | 208 | $0.025779248 |
| `LLMLingua-2` | $4.6894580 | 289 | $0.016226498 |
| Total | $22.3333885 | 1,027 | $0.021746240 |

### Reading Cost Together With Outcome

A presentation can say:

> AI cost is read together with conditions that passed the Terminal-Bench built-in grader,
> not only as tokens consumed. Dividing `$22.3333885` in calculated API cost across 104
> completed conditions by 40 `pass` conditions gives **`$0.5583347125` per passing
> condition in the completed cohort**.

The numerator includes the cost of 64 `wrong_answer` conditions after normal grading. It
excludes `$87.771254` in confirmed cost from five long-running executions that ended
before quality judgment. A `pass` has not been validated as a proxy for customer
acceptance, and calculated API cost is not an invoice. Do not restate the value as customer
acceptance cost or program-wide cost per pass. Exact numerator, denominator, and cost
classification appear in the [technical evidence formula](preliminary-comparison-20260916.md#exact-scope-for-reading-cost-with-outcomes).

**Possible use.** In presales or fixed-price estimates, the split can help identify
potential margin leakage from normal non-passes and unknown-quality attempts. This
benchmark did not validate customer acceptance or actual contract margin.

**Observation.** Among these 26 tasks, LLMLingua-2 had the lowest total calculated API cost
and mean per HTTP attempt, squeez the highest total, and Headroom the fewest logical model
requests.

**Possible explanation.** Request count, context processed per request, cached tokens, and
model path differed by condition. Request-count differences are mixed into cost differences.

**Limitation.** Cost differences are not interpreted as compression savings or compressor
ranking. Recorded VM cost was excluded because some condition-level allocations across
overlapping execution intervals remain unresolved.

## Five Long-Running Executions Kept Separate

At `2026-09-17 23:59 KST`, an operator stopped five then-active tasks based on a post hoc
decision. All ended before first grading, so none is a `pass` or `wrong_answer`.

| Plain classification | Targets | Count | Quality |
|---|---|---:|---|
| Operator stop | `circuit-fibsqrt` / `none`, `feal-linear-cryptanalysis` / `none`, `winning-avg-corewars` / `none`, `tune-mjcf` / `Headroom` | 4 | Unknown before grading |
| Stalled while waiting for an HTTP response | `tune-mjcf` / `none` | 1 | Unknown before grading |

`291 / 291 / 290 / 290` for `tune-mjcf` / `none` does not mean 290 failures. While
trying to solve one task, it generated 291 logical model requests and 291 HTTP attempts,
with 290 successful HTTP responses and 290 deliveries to Harbor. The final 291st HTTP
attempt had no confirmed response. Request count does not indicate progress or proximity
to a correct answer.

Confirmed calculated API cost for the five tasks is `$87.771254`. A `$0.1294175`
input-only estimate for one request without usage is excluded. Never combine this cost,
execution count, or unknown-quality state with the primary 26-task, 104-condition analysis.

## Supported Statements

| Question | Answer supported by current evidence |
|---|---|
| Did actual input change? | It changed in 23 of 104 conditions, across 209 confirmed spans. |
| Did changed-span size decrease? | Recomputable changed spans went from `97,723 → 50,824` tokens. This is not a total API-usage reduction. |
| Did quality judgments differ from the uncompressed reference? | 10 of 78 comparisons differed: 3 toward improvement and 7 toward degradation. Seven of the 10 had zero actual string changes. |
| Were requests, usage, and cost equal? | No. They differed by condition, mixed with request-count and execution-path differences. |

## Unsupported Statements

| Question not yet answerable | Reason |
|---|---|
| Which compressor is best? | One run per condition, and the sample does not represent all 89 tasks. |
| Is quality non-inferior under compression? | Without repeated execution, run variability cannot be separated from condition effects. |
| What percentage of cost falls across all users? | This is not a population sample, and cache, request count, and model path were uncontrolled. |
| Did compression cause the cost or quality difference? | Judgment sometimes changed despite zero actual string changes, so causality was not established. |

## What to Check Next

First measure variability by running the same tasks and conditions repeatedly. Control
cache and concurrency, and preregister stopping rules. Keep technical incompletion separate
from correct and incorrect answers, and analyze how long it persisted and how it ended.
Until that validation is complete, do not conclude compressor ranking, non-inferiority, or
population cost savings.

## Technical Appendix

### String-Change and Quality Cross-Tabulation

Quality for the 23 changed and 81 unchanged conditions is:

| Condition | Changed `pass` | Changed `wrong_answer` | Changed total |
|---|---:|---:|---:|
| `none` | 0 | 0 | 0 |
| `squeez` | 0 | 1 | 1 |
| `Headroom` | 2 | 2 | 4 |
| `LLMLingua-2` | 7 | 11 | 18 |
| Total | 9 | 14 | 23 |

| Condition | Unchanged `pass` | Unchanged `wrong_answer` | Unchanged total |
|---|---:|---:|---:|
| `none` | 11 | 15 | 26 |
| `squeez` | 10 | 15 | 25 |
| `Headroom` | 7 | 15 | 22 |
| `LLMLingua-2` | 3 | 5 | 8 |
| Total | 31 | 50 | 81 |

### Sample-Selection Path

| Stage | Tasks | Conditions | Classification |
|---|---:|---:|---|
| Initial execution | 1 | 4 | Before candidate-confirmation rules |
| Candidate logs confirmed from preserved uncompressed records | 5 | 20 | Order in which candidates were confirmed |
| Screening in fixed-list order after candidate exhaustion | 20 | 80 | New `none` runs linked to recovery evidence |
| Total | 26 | 104 | Not 104 independent tasks |

### Exact Request-Counter Fields

| Plain name | Evidence field | Event counted |
|---|---|---|
| Logical model request | `logical_model_calls` | Call received by the proxy |
| Provider HTTP attempt | `total_model_calls` | HTTP request sent to the external provider, including retries |
| Successful HTTP response | `successful_http_responses` | Response returned with status 200 |
| Response delivered to Harbor | `delivered_responses` | Response returned by the proxy to Harbor |

`Harbor stage` in the [technical evidence](preliminary-comparison-20260916.md) is the
completed agent stage `turns`. Its value matched delivered responses in this completed
cohort, but the definitions remain distinct.

### Exact Codes for Long-Running Executions

| Plain classification | Record code | Count |
|---|---|---:|
| Operator stop | `post_hoc_operator_stopped/censored` | 4 |
| Stalled while waiting for an HTTP response | `stalled_http_response` | 1 |

The [long-tail table in the technical evidence](preliminary-comparison-20260916.md#post-hoc-operator-stopped-long-tail)
contains detailed request counts, elapsed time, usage, cost, and attempt identifiers for
the five long-running executions. The remote handoff bundle payload SHA-256 is
`4776561fd65956d6de9c8f57342e055c3d90a2272b76827add7014cdadef841c`.
