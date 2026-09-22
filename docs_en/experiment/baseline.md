# Baseline Without Additional Compression

**Evidence status:** Measurement aggregated from private raw records. This is not a compression-comparison result.

The `none` condition was run 20 times on 2026-09-14 UTC. The preregistered rule returned `stop_inconclusive` and `comparison_informative=false`. This result alone therefore does not establish an acceptable quality range for the compression conditions.

## Measurement Conditions

| Item | Value | Classification |
| --- | --- | --- |
| Sample | 5 purposively selected tasks × 20 repetitions = 100 native trials | Measurement denominator |
| Benchmark | Terminal-Bench 2.1, revision `7131e4375048a0e408a8fb404b5f499d726b695b` | Fixed condition |
| Model | `gpt-5.4`, provider-reported revision `gpt-5.4-2026-03-05` | Fixed condition |
| Runner | Harbor `0.22.0`, instrumented Terminus 2 `2.0.0` | Fixed condition |
| Environment | Cloud VM, Linux kernel `6.17.0-1022-azure`, 8 vCPU | Measurement condition |
| Concurrency and provider constraints | 8 concurrent native trials; only provider throughput limits and service errors applied | Comparison control and operating value |
| Generation settings | temperature `0`, reasoning effort `none` | Fixed condition; not a guarantee of determinism |
| Local tokens | tiktoken `0.14.0`, `o200k_base` | Calculation condition |
| Execution source | `2984a3879252d51d1681b9d4f6b3bf4f4871a12e` | Measurement lineage |

## Variability and Stopping

The number of passing tasks in each repetition was as follows. Each value has a denominator of 5 tasks.

```text
4, 3, 3, 3, 4, 3, 3, 2, 2, 3, 4, 4, 3, 3, 3, 4, 3, 3, 3, 3
```

| Metric | Value | Sample or denominator | Classification |
| --- | ---: | --- | --- |
| Overall observed minimum and maximum | 2 and 4 tasks | 20 repetitions, 5 tasks per repetition | Measurement |
| Observed range width | 2 tasks | 20 repetitions | Calculation |
| Mean | 3.15 tasks | 20 repetitions | Calculation |
| Sample standard deviation | 0.5871 tasks | 20 repetitions | Calculation; supporting metric |
| First 5 repetitions | 3–4 tasks, width 1 | 5 repetitions | Measurement and calculation; continuation criterion met |
| Repetitions 1–10 | 2–4 tasks | 10 repetitions | Measurement |
| Repetitions 11–20 | 3–4 tasks | 10 repetitions | Measurement |
| Final decision | `stop_inconclusive` | One preregistered rule | Decision from a calculation rule |

At 10 repetitions, the ranges for the first and second groups of five and the sets of task-level observations differed, so collection continued to 20 repetitions. At 20 repetitions, the ranges of the two halves still differed, as did the task-level observation sets for `log-summary-date-ranges` and `nginx-request-logging`.

## Results by Task

| Task | Passes | Denominator | Failure classification | Classification |
| --- | ---: | ---: | --- | --- |
| `cancel-async-tasks` | 4 | 20 | 16 `wrong_answer` | Measurement and classification judgment |
| `log-summary-date-ranges` | 1 | 20 | 19 `wrong_answer` | Measurement and classification judgment |
| `multi-source-data-merger` | 20 | 20 | None | Measurement |
| `nginx-request-logging` | 18 | 20 | 2 `wrong_answer` | Measurement and classification judgment |
| `openssl-selfsigned-cert` | 20 | 20 | None | Measurement |

Native judgment evidence was valid for 100/100 trials. At execution time, the automatic classifier recorded all 37 failures as `wrong_answer` based on the `native_assertion_failed` signature. This is an automatic classification of the observed failure form, not a diagnosis that the answer itself was wrong. Because no additional compression was applied, these failures cannot be attributed to compression.

**Proposed clarification to the 2026-09-14 UTC classification:** A later static comparison found that the two nginx `wrong_answer` cases were false failures caused by the original verifier rejecting equivalent syntax. The record should therefore not describe these as “37 actual wrong answers.” The execution-time automatic classification of 37 cases remains in the ledger, while the causal comparison status distinguishes two nginx verifier false failures from 35 automatic classifications whose causes were not independently verified. This proposes a clarification to the classification; it does not change the original pass counts.

The table reports measurements from the original verifier at execution time. A later static comparison found that the two nginx failures used equivalent `${http_user_agent}` syntax that the original verifier rejected. Under the corrected variable check, the calculated values would be nginx 20/20 and 65/100 overall. This is a static counterfactual calculation based on preserved traces and the original verifier results, not a replay of the actual workspaces. It does not replace a new run or the original measurements. The evidence and pinned SHA values are recorded in the [screening protocol](screening-protocol.md#effect-on-the-existing-baseline).

## Usage and Execution Volume

| Metric | Value | Sample or denominator | Classification |
| --- | ---: | --- | --- |
| Provider-reported input tokens | 1,340,765 | 351 successful responses | Measurement; API usage, not invoice reconciliation |
| Provider-reported cached input tokens | 222,080 | Subset of input tokens | Measurement; observation only |
| Provider-reported output tokens | 179,805 | 351 successful responses | Measurement; API usage, not invoice reconciliation |
| Local input tokens | 1,333,459 | Message content from 351 requests | `o200k_base` calculation |
| Local output tokens | 178,145 | Visible assistant content from 351 responses | `o200k_base` calculation |
| Agent turns | 332 | 100 trials | Measurement |
| Logical model calls and total HTTP calls | 351 and 351 | 100 trials | Measurement |
| HTTP 200 responses and retries | 351 and 0 | 351 HTTP attempts | Measurement |
| Repeated identical commands | 11 | Command blocks accepted by the terminal across 100 trials | Calculation |
| Repeated identical subcommands | 18 | Conservatively split shell subcommands across 100 trials | Calculation |
| Calculated cost | `$5.5493075` | Provider usage × fixed ledger rates | Calculation; not invoice reconciliation |
| Native-trial observation interval | 1,405.368 seconds, about 23 minutes 25 seconds | Earliest start to latest finish across 100 trials | Difference between measured timestamps |

Calculated cost applies the ledger rates of `$2.50`, `$0.25`, and `$15.00` per million tokens to uncached input, cached input, and output, respectively. Local token counts and provider usage are not interchangeable.

Twenty repetition-level result payloads totaling 51.846 MiB were retrieved from object storage. On the collection host, size, SHA-256, execution source, and ledger lineage matched for 20/20 payloads before the execution VM was deallocated. The native-trial observation interval excludes preparation before execution and final retrieval verification. Raw requests and responses are not published in this repository.

## Limitations

- The baseline did not meet the preregistered stability condition after 20 repetitions. The observed range of 2 is not a confirmed tolerance for the compression comparison.
- Two tasks were at the ceiling with 20/20 passes, while two were near the floor with 4/20 and 1/20. Floor tasks may not reveal further degradation adequately.
- The five tasks were purposively selected and are not representative of all Terminal-Bench 2.1 tasks or code-assistant work.
- temperature `0` and reasoning effort `none` do not guarantee deterministic output. Cached input was also not a controlled factor.
- `none` means no additional compression. It does not mean raw input without Harbor's existing 10,000-byte intermediate truncation.
- The 2026-09-14 baseline experiment did not measure native quality, tokens, cost, or time for squeez, Headroom, or LLMLingua-2.
