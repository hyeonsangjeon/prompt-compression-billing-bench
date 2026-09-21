# Task-Level Changed-Condition Comparison for the Preliminary Experiment

This document expands the condition totals in the [preliminary experiment summary](README.md)
into a task-level comparison. Each of the 23 conditions whose string actually changed
appears beside the same task's `none` result. Here, inventory means the existing task list.
Tasks remain in inventory order and are not resorted by pass status, reduction, or cost.

## How to Read the Table

- **Local tokens in changed spans** recount only strings that actually changed, using
  tiktoken `0.14.0` and `o200k_base`. They are not full-request or billed tokens.
- The denominator for **reduction in changed spans** is that row's local-token count before
  transformation.
- Judgments reproduce the task's built-in `pass` and `wrong_answer` results.
- **Calculated API cost** applies the fixed price table to provider usage and is displayed
  to three decimal places. It was not reconciled to an actual invoice.
- Each compression condition and `none` ran once. A shared task does not establish equal
  request counts, cache state, or execution paths, and differences are not attributed to
  compression.
- When multiple compression conditions changed strings for one task, the comparison
  `none` judgment and cost repeat across rows. The final two columns are row-level
  references and must not be summed.

## 23 Conditions With Changed Strings

| Task | Compression condition | Changed spans | Local tokens in changed spans (before) | Local tokens in changed spans (after) | Reduction in changed spans | Compression judgment | Compression calculated API cost | Same-task `none` judgment | Same-task `none` calculated API cost |
|---|---|---:|---:|---:|---:|---|---:|---|---:|
| [`crack-7z-hash`](tasks.md#tasks-and-observations) | Headroom | 18 | 21,456 | 11,502 | 46.4% | `pass` | `$0.338` | `pass` | `$0.810` |
| [`crack-7z-hash`](tasks.md#tasks-and-observations) | LLMLingua-2 | 24 | 40,112 | 20,712 | 48.4% | `pass` | `$0.191` | `pass` | `$0.810` |
| [`dna-assembly`](tasks.md#tasks-and-observations) | LLMLingua-2 | 7 | 490 | 231 | 52.9% | `wrong_answer` | `$0.161` | `wrong_answer` | `$0.262` |
| [`modernize-scientific-stack`](tasks.md#tasks-and-observations) | Headroom | 5 | 205 | 160 | 22.0% | `pass` | `$0.062` | `pass` | `$0.073` |
| [`modernize-scientific-stack`](tasks.md#tasks-and-observations) | LLMLingua-2 | 3 | 123 | 72 | 41.5% | `pass` | `$0.036` | `pass` | `$0.073` |
| [`torch-tensor-parallelism`](tasks.md#tasks-and-observations) | LLMLingua-2 | 1 | 46 | 21 | 54.3% | `wrong_answer` | `$0.029` | `wrong_answer` | `$0.039` |
| [`gcode-to-text`](tasks.md#tasks-and-observations) | LLMLingua-2 | 7 | 518 | 252 | 51.4% | `wrong_answer` | `$0.133` | `wrong_answer` | `$0.064` |
| [`log-summary-date-ranges`](tasks.md#tasks-and-observations) | squeez | 2 | 6,654 | 1,652 | 75.2% | `wrong_answer` | `$0.037` | `wrong_answer` | `$0.029` |
| [`log-summary-date-ranges`](tasks.md#tasks-and-observations) | Headroom | 2 | 260 | 188 | 27.7% | `wrong_answer` | `$0.054` | `wrong_answer` | `$0.029` |
| [`log-summary-date-ranges`](tasks.md#tasks-and-observations) | LLMLingua-2 | 2 | 6,842 | 3,206 | 53.1% | `wrong_answer` | `$0.040` | `wrong_answer` | `$0.029` |
| [`llm-inference-batching-scheduler`](tasks.md#tasks-and-observations) | LLMLingua-2 | 6 | 288 | 138 | 52.1% | `wrong_answer` | `$0.323` | `pass` | `$0.609` |
| [`model-extraction-relu-logits`](tasks.md#tasks-and-observations) | LLMLingua-2 | 3 | 207 | 102 | 50.7% | `wrong_answer` | `$0.074` | `wrong_answer` | `$0.101` |
| [`overfull-hbox`](tasks.md#tasks-and-observations) | LLMLingua-2 | 10 | 660 | 340 | 48.5% | `pass` | `$0.105` | `wrong_answer` | `$0.204` |
| [`prove-plus-comm`](tasks.md#tasks-and-observations) | LLMLingua-2 | 7 | 446 | 210 | 52.9% | `pass` | `$0.043` | `pass` | `$0.027` |
| [`raman-fitting`](tasks.md#tasks-and-observations) | LLMLingua-2 | 10 | 385 | 195 | 49.4% | `wrong_answer` | `$0.096` | `wrong_answer` | `$0.128` |
| [`sqlite-with-gcov`](tasks.md#tasks-and-observations) | LLMLingua-2 | 4 | 284 | 140 | 50.7% | `pass` | `$0.104` | `pass` | `$0.229` |
| [`vulnerable-secret`](tasks.md#tasks-and-observations) | LLMLingua-2 | 4 | 280 | 128 | 54.3% | `pass` | `$0.062` | `pass` | `$0.065` |
| [`video-processing`](tasks.md#tasks-and-observations) | LLMLingua-2 | 6 | 438 | 192 | 56.2% | `wrong_answer` | `$0.173` | `wrong_answer` | `$0.150` |
| [`chess-best-move`](tasks.md#tasks-and-observations) | LLMLingua-2 | 14 | 1,008 | 420 | 58.3% | `wrong_answer` | `$0.232` | `wrong_answer` | `$0.112` |
| [`schemelike-metacircular-eval`](tasks.md#tasks-and-observations) | Headroom | 28 | 8,344 | 5,852 | 29.9% | `wrong_answer` | `$0.946` | `wrong_answer` | `$0.565` |
| [`schemelike-metacircular-eval`](tasks.md#tasks-and-observations) | LLMLingua-2 | 25 | 7,450 | 4,500 | 39.6% | `wrong_answer` | `$0.679` | `wrong_answer` | `$0.565` |
| [`build-pov-ray`](tasks.md#tasks-and-observations) | LLMLingua-2 | 13 | 923 | 455 | 50.7% | `wrong_answer` | `$0.362` | `pass` | `$0.600` |
| [`feal-differential-cryptanalysis`](tasks.md#tasks-and-observations) | LLMLingua-2 | 8 | 304 | 156 | 48.7% | `pass` | `$0.101` | `pass` | `$0.444` |
| **Total** | **23 conditions** | **209** | **97,723** | **50,824** | **48.0%** | **`pass` 9; `wrong_answer` 14** | **Sum rows separately** | **Do not sum repeated `none` values** | **Do not sum repeated `none` values** |

## 55 Compression Conditions With Unchanged Strings

| Scope | Conditions | `pass` | `wrong_answer` | Total calculated API cost |
|---|---:|---:|---:|---:|
| Conditions among squeez, Headroom, and LLMLingua-2 with zero recorded transformed-string changes | 55 | 20 | 35 | `$12.335` |

The 55 conditions can include both cases with no compression candidate and cases in which
a candidate existed but the profile did not change its string. The current public
aggregate cannot distinguish them. `$12.335` is the sum of precise calculated API costs,
displayed to three decimal places; it is not an actual invoice.

## Observations and Interpretation Limits

**Observation.** These 23 conditions include a `pass` at a 22.0% changed-span reduction
and a `wrong_answer` at 75.2%, with both judgments also appearing around 48%. Compression
cost is lower than same-task `none` in some rows and higher in others. The table does not
show an ordering in which greater reduction corresponds to passing or lower cost.

**Limitation.** These are preliminary observations from one run per condition; they do not
establish that correlation or causation is absent in general.

## Sources

- [Plain-language guide to the 26 tasks and four conditions](tasks.md)
- [Raw condition-level quality, cost, and changed-span token evidence](preliminary-comparison-20260916.md)
- [Preliminary experiment summary](README.md)
