# Preliminary Experiment Protocol

This historical protocol records the fixed conditions and preregistered stopping rules in effect at the time. It is a design decision, not a results document. When the protocol was fixed, only the baseline without additional compression had been measured; the compression comparison had not been run.

## Question and Interventions

The question is how input size, quality, and total call cost change when only identified log candidates are reduced in a code-assistant workload. Code, instructions, and assistant history remain unchanged.

| Condition | Actual intervention | Classification judgment |
| --- | --- | --- |
| `none` | No additional compression; Harbor's existing output truncation remains | Baseline |
| `squeez` | Keep the first 30 content lines and delete the rest of the candidate | Discarding; lossy |
| `Headroom` | Show repeated path prefixes once and verify reverse transformation | Grouping; byte-restorable |
| `LLMLingua-2` | Select tokens to retain within the candidate | Token selection; lossy |

## Fixed Conditions

| Item | Fixed value | Classification |
| --- | --- | --- |
| Benchmark | Terminal-Bench 2.1, revision `7131e4375048a0e408a8fb404b5f499d726b695b` | Design judgment |
| Tasks | 5 purposively selected English tasks: `cancel-async-tasks`, `log-summary-date-ranges`, `multi-source-data-merger`, `nginx-request-logging`, `openssl-selfsigned-cert` | Design judgment |
| One repetition | Run and grade each of the 5 tasks once | Definition |
| Model | `gpt-5.4`, provider-reported revision `gpt-5.4-2026-03-05` | Fixed condition |
| Generation settings | temperature `0`, reasoning effort `none`, maximum completion of `2,048` tokens | Fixed condition; not a guarantee of determinism |
| Execution environment | Cloud VM, Linux kernel `6.17.0-1022-azure`, 8 vCPU | Measurement condition |
| Runner | Harbor `0.22.0` and its bundled instrumented Terminus 2 `2.0.0` | Fixed condition |
| Concurrency | 8 native trials | Comparison control |
| Provider constraints | Only provider throughput limits and service errors apply | Operating value at execution time |
| Local tokenizer | tiktoken `0.14.0`, `o200k_base` | Calculation condition |
| Grading | Use each task's built-in native verifier without modification | Fixed condition |
| Baseline execution source | `2984a3879252d51d1681b9d4f6b3bf4f4871a12e` | Measurement lineage |
| Schedule limit | 2026-09-17 | Operating condition |

temperature and reasoning effort are request settings. They are not controls that guarantee identical output, determinism, or lossless observation. Cached input tokens are observed but are not claimed as a controlled factor.

## Execution Path

Cloud-native execution is orchestrated by [`src/native_run.py`](../../src/native_run.py), and [`src/live_transport.py`](../../src/live_transport.py) sends requests after protection checks. [`accounting.py`](../../accounting.py) aggregates separate local Ollama records; it is not the runner or transport for this cloud baseline.

## Protections and Metrics

Candidate selection applies only to identified log spans. Code, mixed code output, structured data, instructions, assistant history, roles, and request settings are protected. A protection violation stops the run rather than reverting to the original text and continuing.

The following are recorded in the same units for every condition:

- Provider-reported input, output, and cached input tokens
- Message-content input tokens and visible assistant-output tokens recounted with `o200k_base`
- Turns per task, logical calls, and total HTTP calls including retries
- Counts of repeated identical commands and subcommands
- Built-in pass status and `wrong_answer`, `wrong_format`, `timeout`, `tool_error`, or `other` failure classification
- `compress_seconds`, `transport_seconds`, and `model_seconds`
- LLMLingua-2 worker inference, serialization wait, and total compression wall time

A reduction in input tokens is not classified as cost savings if output tokens, call count, repeated work, or cost increase. Failure classifications describe observed forms; they do not diagnose compression as the cause.

## Preregistered Stopping Rules

The primary decision statistic is the observed range of the number of passing tasks in one repetition. Sample standard deviation is only a supporting description.

| Decision point | Preregistered rule | Next action | Classification |
| --- | --- | --- | --- |
| 5 repetitions | Stop if the range width of passing-task counts exceeds `1` | Review verifier, operating path, and design | Operating judgment; not a statistical confidence interval |
| 5 repetitions | Continue if the width is `0` or `1` | Collect through 10 repetitions; do not call it stable | Operating judgment |
| 10 repetitions | The minima, maxima, and task-level observation sets match between repetitions 1–5 and 6–10 | End baseline-range collection | Calculation rule |
| 10 repetitions | The two halves differ | Extend to 20 total repetitions | Calculation rule |
| 20 repetitions | Repetitions 1–10 and 11–20 still differ | Stop as inconclusive; do not extend to 30 or change tasks | Calculation rule |

Protection violations, missing required records, changes in settings or model revision, and retrieval-verification failures are also stopping reasons. Compression conditions use the same repetition count as the accepted baseline.

## Execution Order

1. Run the `none` baseline.
2. Evaluate the baseline stopping rule.
3. Have a person decide whether to proceed with the compression comparison.
4. Only if approved, run squeez, Headroom, and LLMLingua-2 under the same protocol.

No condition deletes a candidate in its entirety. The 2026-09-14 baseline stopped as inconclusive after 20 repetitions, and the three compression conditions had not yet been run.
