# Preliminary Observations Comparing No Compression with Three Compression Conditions

New readers should start with the [plain-language summary](plain-language-results-20260917.md).
This document preserves the run identifiers, condition-level figures, cost scope, and
SHA-256 verification values that support that summary. The conclusions appear first;
repeated task-level tables and identifiers remain as evidence for reproduction and audit.

## Summary

- The study ran 26 tasks, each representing one problem, once under the same four conditions. This yields 104 conditions, not 104 independent problems.
- There were 40 `pass` results (passed the task's built-in grader) and 64 `wrong_answer` results (the run completed but did not pass grading). Technically incomplete attempts are excluded from this quality denominator.
- Strings actually changed in 209 segments across 23 conditions. Retokenizing only those changed segments gives `97,723 → 50,824` tokens. This is not a reduction in total API usage or billed cost.
- Logical model requests, external model-service (provider) HTTP attempts, successful HTTP responses, and responses delivered to
  the execution tool (Harbor) are distinct events. Across the 104 completed conditions, all four
  observed counters happened to equal 1,027.
- Some conditions produced different quality verdicts even though no string changed. Because each condition ran only once and neither caching nor model path was controlled, these observations do not establish compressor rankings, non-inferiority, population-level cost savings, or causality.
- Of five separate long-running attempts, an operator stopped four and one stalled before an HTTP response. All remained quality-unknown before the first grading step and are not combined with the 26 tasks and 104 conditions.

## Terms in Plain Language

| Term | Meaning in this document |
|---|---|
| Task | One problem to solve |
| Condition | One way of solving the same problem. Four conditions ran for each task. |
| `none` | Not “no work”; the **baseline condition that solves the task without added compression** |
| `pass` | A completed run and grading process that passed the task's built-in grader |
| `wrong_answer` | A completed run and grading process whose answer did not pass |
| Technically incomplete | Execution, communication, or evidence storage did not finish, so quality cannot be determined |
| Operator-stopped | A technically incomplete attempt stopped through a post-hoc operator decision; not a wrong answer |
| Before/after request counts | Counts of distinct events such as requests and responses, not a completion rate. For example, `291 / 290` does not mean that 290 of 291 steps completed. |
| Tokens in actually changed segments | Tokens retokenized only for segments whose strings differ before and after compression |
| API usage | Total input, cached-input, and output tokens reported by the provider; broader than the actually changed segments |
| Calculated API cost | API usage multiplied by a fixed price table; not an invoice-reconciled amount |

## How to Read This Document

1. Check the denominators and limitations in **Fixed Results and Permitted Claims**.
2. Find task-level results in **Quality, Actual Changes, API Usage, and Cost**.
3. Review execution conditions and representativeness limits in **Comparison Conditions and Interpretation Limits**.
4. Use the task sections in the expandable area to inspect run IDs, remote hashes, restored regrading, and cost evidence.
5. Read **Post-hoc Operator-Stopped Long Tail** as a separate operational record, not as part of the main analysis.

## Fixed Results and Permitted Claims

Through 2026-09-17 UTC, the study completed one observation for each of `none`, `squeez`,
`Headroom`, and `LLMLingua-2` across 26 tasks, for 104 condition observations. All 104
passed workspace save-and-restore, matching regrade verdicts, and remote-data verification.
The four conditions for each task are paired and must not be counted as 104 independent tasks.

- Quality verdicts were 40 `pass` and 64 `wrong_answer`. Completed conditions in this table exclude technically incomplete attempts. The detailed verification evidence separates incomplete no-compression screening and virtual-machine interruption attempts from completed attempts.
- Strings actually changed in 23 conditions. Retokenizing 209 changed segments from preserved source text yielded `97,723 → 50,824` tokens.
- This figure describes only transformed segments. Treating it as a reduction in total API input, cached tokens, or billed cost would be incorrect.
- Each task-condition pair ran only once, so the observations cannot establish non-inferiority, population-level cost savings, or compressor rankings.
- No-compression screening of later tasks proceeded separately, but a user decision at 2026-09-17 23:59 KST stopped new model runs. The public main analysis is fixed at 26 tasks and 104 conditions for which all four conditions completed; it excludes the five long-tail attempts stopped before grading.

| Selection path | Tasks | Condition observations | `pass` / `wrong_answer` | Conditions with actual changes |
|---|---:|---:|---:|---:|
| First run before the candidate-screening rule was applied | 1 `cancel-async-tasks` task | 4 | 0 / 4 | 0 |
| Order in which eligible log candidates appeared in preserved no-compression records | 5 | 20 | 12 / 8 | 6 |
| Candidate screening in new no-compression runs, following task-list order after existing candidates were exhausted | 15 tasks from `extract-elf` through `video-processing`, followed by completed `chess-best-move`, `schemelike-metacircular-eval`, `build-pov-ray`, `dna-insert`, and `feal-differential-cryptanalysis` | 80 | 28 / 52 | 17 |
| Total | 26 | 104 | 40 / 64 | 23 |

## Exact Scope for Reading Cost with Outcomes

**Calculated API cost per passing condition in the completed cohort** is an arithmetic value computed only for the 104 completed conditions. The numerator is the calculated API cost obtained by applying the fixed price table to provider usage across all 104 conditions; the denominator is the number of those conditions that passed the Terminal-Bench built-in grader.

```text
$22.3333885 ÷ 40 = $0.5583347125
Calculated API cost for 104 completed conditions ÷ 40 passing conditions
```

The `$22.3333885` numerator includes the cost of all 40 `pass` conditions and all 64 `wrong_answer` conditions that completed normal grading. This completed cohort had 0 `wrong_format` conditions. The arithmetic value is neither customer-acceptance cost nor an actual invoice, and `pass` has not been validated as a proxy for customer acceptance.

| Scope and classification | Conditions or attempts | Verified calculated API cost | Meaning in this table |
|---|---:|---:|---|
| `pass` results with exact outcome-cost linkage in the completed cohort | 4 conditions | `$2.277506` | Exact-linked subset of all 40 `pass` conditions |
| Normal non-passing results with exact outcome-cost linkage in the completed cohort | 5 conditions | `$7.56232` | 5 `wrong_answer` conditions and 0 `wrong_format` conditions |
| Completed-cohort cost not allocated by outcome | 95 conditions | `$12.4935625` | Quality is known as 36 `pass` and 59 `wrong_answer` conditions, but exact attempt-cost linkage is unavailable |
| Operator-stopped before a quality verdict | 4 attempts | `$80.879013` | Excluded from the denominator of 104 conditions |
| HTTP response stall before a quality verdict | 1 attempt | `$6.892241` | Excluded from the denominator of 104 conditions |

The first three rows sum to `104 conditions` and `$22.3333885`. The final two rows separately sum to `5 attempts` and `$87.771254`; they are excluded from both numerator and denominator of the completed cohort. The input-only estimate of `$0.1294175` for one request without usage in the stalled-HTTP-response attempt is also excluded from verified cost.

Because exact attempt linkage does not cover all 104 conditions and every technically incomplete attempt, **this document does not calculate program-wide cost per passing condition**. A metric that retains the cost of every started attempt in a program-wide numerator, regardless of outcome, can be produced only after linkage is complete. The values currently suitable for publication are the completed-cohort arithmetic value and the verified quality-unknown subtotal. Calculation inputs and bidirectional total checks are documented in [Outcome-Based Cost Accounting](outcome-cost-accounting-20260918.md).

**Possible use.** In presales or fixed-price estimation, these figures may help identify possible margin leakage by separating normal non-passing costs from quality-unknown costs. This benchmark did not validate customer acceptance or actual contract margin.

## Quality, Actual Changes, API Usage, and Cost

Token counts are input, cached-input, and output tokens reported by the API provider. Calculated API cost applies the fixed price table to that usage and is not an invoice-reconciled amount. Virtual-machine cost applies `$0.403` per hour to actual work intervals and allocates overlapping intervals evenly among the conditions running at that time. Verified Blob and network operation cost is `<$0.001` for every condition and is shown separately.

| Task | Condition | Quality | Actual changes | API input / cached-input / output tokens | Calculated API cost | Allocated virtual-machine cost | Total condition time |
|---|---|---:|---:|---:|---:|---:|---:|
| `cancel-async-tasks` | none | wrong_answer | 0 occurrences | 2,375 / 1,152 / 593 | $0.012 | $0.011 | 1m 53s |
|  | squeez | wrong_answer | 0 occurrences | 2,527 / 1,024 / 542 | $0.012 | $0.009 | 1m 23s |
|  | Headroom | wrong_answer | 0 occurrences | 7,610 / 4,224 / 991 | $0.024 | $0.010 | 2m 23s |
|  | LLMLingua-2 | wrong_answer | 0 occurrences | 2,544 / 0 / 585 | $0.015 | $0.010 | 3m 28s |
| `crack-7z-hash` | none | pass | 0 occurrences | 1,217,052 / 1,082,624 / 13,538 | $0.810 | $0.066 | 14m 30s |
|  | squeez | pass | 0 occurrences | 261,471 / 138,880 / 7,123 | $0.448 | $0.020 | 7m 40s |
|  | Headroom | pass | 18 occurrences | 233,658 / 146,432 / 5,575 | $0.338 | $0.010 | 4m 44s |
|  | LLMLingua-2 | pass | 24 occurrences | 159,676 / 128,000 / 5,311 | $0.191 | $0.034 | 7m 16s |
| `dna-assembly` | none | wrong_answer | 0 occurrences | 83,272 / 27,392 / 7,703 | $0.262 | $0.007 | 3m 7s |
|  | squeez | wrong_answer | 0 occurrences | 81,442 / 49,024 / 5,634 | $0.178 | $0.006 | 2m 39s |
|  | Headroom | wrong_answer | 0 occurrences | 157,470 / 27,008 / 12,172 | $0.515 | $0.011 | 3m 43s |
|  | LLMLingua-2 | wrong_answer | 7 occurrences | 81,455 / 56,960 / 5,709 | $0.161 | $0.016 | 3m 55s |
| `modernize-scientific-stack` | none | pass | 0 occurrences | 23,131 / 5,504 / 1,864 | $0.073 | $0.005 | 2m 5s |
|  | squeez | pass | 0 occurrences | 24,857 / 4,480 / 2,169 | $0.085 | $0.004 | 2m 4s |
|  | Headroom | pass | 5 occurrences | 22,246 / 8,832 / 1,749 | $0.062 | $0.004 | 2m 3s |
|  | LLMLingua-2 | pass | 3 occurrences | 11,573 / 4,992 / 1,241 | $0.036 | $0.008 | 2m 43s |
| `sam-cell-seg` | none | pass | 0 occurrences | 43,579 / 19,328 / 8,081 | $0.187 | $0.013 | 5m 19s |
|  | squeez | pass | 0 occurrences | 37,841 / 10,240 / 4,764 | $0.143 | $0.010 | 4m 16s |
|  | Headroom | pass | 0 occurrences | 38,796 / 14,720 / 7,469 | $0.176 | $0.013 | 5m 18s |
|  | LLMLingua-2 | pass | 0 occurrences | 32,391 / 18,048 / 4,451 | $0.107 | $0.029 | 5m 46s |
| `torch-tensor-parallelism` | none | wrong_answer | 0 occurrences | 6,262 / 0 / 1,565 | $0.039 | $0.024 | 10m 32s |
|  | squeez | wrong_answer | 0 occurrences | 4,660 / 0 / 1,319 | $0.031 | $0.023 | 10m 21s |
|  | Headroom | wrong_answer | 0 occurrences | 7,568 / 0 / 1,167 | $0.036 | $0.023 | 10m 8s |
|  | LLMLingua-2 | wrong_answer | 1 occurrences | 3,963 / 0 / 1,272 | $0.029 | $0.030 | 6m 5s |
| `extract-elf` | none | wrong_answer | 0 occurrences | 51,050 / 23,936 / 3,960 | $0.133 | $0.006 | 1m 56s |
|  | squeez | pass | 0 occurrences | 24,161 / 0 / 1,863 | $0.088 | $0.003 | 1m 31s |
|  | Headroom | pass | 0 occurrences | 12,773 / 0 / 1,272 | $0.051 | $0.003 | 1m 31s |
|  | LLMLingua-2 | wrong_answer | 0 occurrences | 40,836 / 23,296 / 2,779 | $0.091 | $0.010 | 2m 59s |
| `financial-document-processor` | none | wrong_answer | 0 occurrences | 56,275 / 0 / 5,600 | $0.225 | $0.010 | 3m 59s |
|  | squeez | wrong_answer | 0 occurrences | 244,315 / 129,792 / 6,280 | $0.413 | $0.015 | 4m 41s |
|  | Headroom | wrong_answer | 0 occurrences | 41,804 / 0 / 3,923 | $0.163 | $0.006 | 2m 38s |
|  | LLMLingua-2 | wrong_answer | 0 occurrences | 240,376 / 216,064 / 7,760 | $0.231 | $0.044 | 8m 27s |
| `gcode-to-text` | none | wrong_answer | 0 occurrences | 17,804 / 0 / 1,296 | $0.064 | $0.003 | 1m 27s |
|  | squeez | wrong_answer | 0 occurrences | 1,976,777 / 1,862,400 / 31,502 | $1.224 | $0.068 | 11m 31s |
|  | Headroom | wrong_answer | 0 occurrences | 50,022 / 8,576 / 3,956 | $0.165 | $0.005 | 1m 58s |
|  | LLMLingua-2 | wrong_answer | 7 occurrences | 83,235 / 69,760 / 5,489 | $0.133 | $0.013 | 3m 30s |
| `install-windows-3.11` | none | wrong_answer | 0 occurrences | 44,986 / 8,192 / 2,550 | $0.132 | $0.007 | 3m 35s |
|  | squeez | wrong_answer | 0 occurrences | 58,104 / 23,168 / 3,137 | $0.140 | $0.009 | 3m 44s |
|  | Headroom | wrong_answer | 0 occurrences | 49,485 / 28,672 / 2,774 | $0.101 | $0.007 | 3m 35s |
|  | LLMLingua-2 | wrong_answer | 0 occurrences | 77,090 / 65,024 / 3,773 | $0.103 | $0.021 | 4m 55s |
| `kv-store-grpc` | none | pass | 0 occurrences | 11,199 / 0 / 1,335 | $0.048 | $0.003 | 1m 32s |
|  | squeez | pass | 0 occurrences | 14,311 / 6,528 / 1,840 | $0.049 | $0.004 | 1m 45s |
|  | Headroom | pass | 0 occurrences | 20,979 / 11,136 / 2,410 | $0.064 | $0.004 | 1m 50s |
|  | LLMLingua-2 | pass | 0 occurrences | 16,910 / 13,440 / 1,726 | $0.038 | $0.009 | 2m 57s |
| `log-summary-date-ranges` | none | wrong_answer | 0 occurrences | 7,484 / 1,664 / 954 | $0.029 | Unknown | 1m 31s |
|  | squeez | wrong_answer | 2 occurrences | 8,376 / 0 / 1,090 | $0.037 | Unknown | 1m 33s |
|  | Headroom | wrong_answer | 2 occurrences | 14,203 / 0 / 1,206 | $0.054 | Unknown | 1m 33s |
|  | LLMLingua-2 | wrong_answer | 2 occurrences | 9,603 / 0 / 1,033 | $0.040 | Unknown | 3m 46s |
| `llm-inference-batching-scheduler` | none | pass | 0 occurrences | 269,908 / 86,144 / 8,534 | $0.609 | Unknown | 5m 11s |
|  | squeez | pass | 0 occurrences | 125,300 / 65,792 / 9,017 | $0.300 | Unknown | 4m 10s |
|  | Headroom | wrong_answer | 0 occurrences | 90,980 / 11,008 / 8,895 | $0.336 | Unknown | 3m 38s |
|  | LLMLingua-2 | wrong_answer | 6 occurrences | 107,090 / 14,848 / 5,890 | $0.323 | Unknown | 6m 58s |
| `model-extraction-relu-logits` | none | wrong_answer | 0 occurrences | 22,061 / 0 / 3,049 | $0.101 | Unknown | 3m 42s |
|  | squeez | wrong_answer | 0 occurrences | 31,808 / 0 / 3,240 | $0.128 | Unknown | 3m 45s |
|  | Headroom | wrong_answer | 0 occurrences | 5,900 / 0 / 884 | $0.028 | Unknown | 3m 3s |
|  | LLMLingua-2 | wrong_answer | 3 occurrences | 17,611 / 2,944 / 2,450 | $0.074 | Unknown | 6m 48s |
| `openssl-selfsigned-cert` | none | pass | 0 occurrences | 3,777 / 1,664 / 1,008 | $0.021 | Unknown | 4m 10s |
|  | squeez | pass | 0 occurrences | 6,586 / 1,792 / 1,143 | $0.030 | Unknown | 4m 11s |
|  | Headroom | pass | 0 occurrences | 3,806 / 0 / 1,011 | $0.025 | Unknown | 4m 11s |
|  | LLMLingua-2 | pass | 0 occurrences | 3,850 / 0 / 1,042 | $0.025 | Unknown | 4m 13s |
| `overfull-hbox` | none | wrong_answer | 0 occurrences | 91,483 / 37,248 / 3,930 | $0.204 | Unknown | 5m 14s |
|  | squeez | wrong_answer | 0 occurrences | 46,603 / 13,824 / 2,772 | $0.127 | Unknown | 4m 14s |
|  | Headroom | wrong_answer | 0 occurrences | 99,624 / 22,016 / 4,268 | $0.264 | Unknown | 5m 49s |
|  | LLMLingua-2 | pass | 10 occurrences | 37,959 / 12,672 / 2,558 | $0.105 | Unknown | 7m 22s |
| `prove-plus-comm` | none | pass | 0 occurrences | 6,036 / 0 / 782 | $0.027 | Unknown | 1m 43s |
|  | squeez | pass | 0 occurrences | 6,474 / 2,048 / 870 | $0.025 | Unknown | 1m 42s |
|  | Headroom | pass | 0 occurrences | 6,693 / 1,536 / 838 | $0.026 | Unknown | 1m 43s |
|  | LLMLingua-2 | pass | 7 occurrences | 12,298 / 3,968 / 1,418 | $0.043 | Unknown | 5m 33s |
| `raman-fitting` | none | wrong_answer | 0 occurrences | 57,186 / 42,112 / 5,310 | $0.128 | Unknown | 3m 56s |
|  | squeez | wrong_answer | 0 occurrences | 42,686 / 2,560 / 5,394 | $0.182 | Unknown | 2m 17s |
|  | Headroom | wrong_answer | 0 occurrences | 140,806 / 100,736 / 5,901 | $0.214 | Unknown | 3m 23s |
|  | LLMLingua-2 | wrong_answer | 10 occurrences | 33,069 / 25,216 / 4,641 | $0.096 | Unknown | 6m 48s |
| `sqlite-with-gcov` | none | pass | 0 occurrences | 134,414 / 65,920 / 2,759 | $0.229 | Unknown | 7m 55s |
|  | squeez | pass | 0 occurrences | 57,858 / 29,824 / 2,288 | $0.112 | Unknown | 3m 47s |
|  | Headroom | wrong_answer | 0 occurrences | 120,874 / 69,248 / 3,383 | $0.197 | Unknown | 7m 16s |
|  | LLMLingua-2 | pass | 4 occurrences | 39,810 / 9,856 / 1,784 | $0.104 | Unknown | 7m 17s |
| `vulnerable-secret` | none | pass | 0 occurrences | 22,778 / 10,496 / 2,112 | $0.065 | Unknown | 2m 25s |
|  | squeez | pass | 0 occurrences | 54,726 / 11,008 / 2,474 | $0.149 | Unknown | 1m 53s |
|  | Headroom | pass | 0 occurrences | 22,656 / 7,296 / 2,207 | $0.073 | Unknown | 1m 33s |
|  | LLMLingua-2 | pass | 4 occurrences | 30,393 / 20,480 / 2,147 | $0.062 | Unknown | 4m 46s |
| `video-processing` | none | wrong_answer | 0 occurrences | 89,043 / 66,048 / 5,072 | $0.150 | Unknown | 4m 38s |
|  | squeez | wrong_answer | 0 occurrences | 116,954 / 37,248 / 10,708 | $0.369 | Unknown | 5m 40s |
|  | Headroom | wrong_answer | 0 occurrences | 64,341 / 1,536 / 7,086 | $0.264 | Unknown | 3m 8s |
|  | LLMLingua-2 | wrong_answer | 6 occurrences | 55,444 / 16,512 / 4,742 | $0.173 | Unknown | 5m 39s |
| `chess-best-move` | none | wrong_answer | 0 occurrences | 81,844 / 70,912 / 4,473 | $0.112 | Unknown | 4m 45s |
|  | squeez | wrong_answer | 0 occurrences | 60,227 / 37,632 / 5,390 | $0.147 | Unknown | 4m 49s |
|  | Headroom | wrong_answer | 0 occurrences | 35,629 / 9,344 / 3,396 | $0.119 | Unknown | 2m 51s |
|  | LLMLingua-2 | wrong_answer | 14 occurrences | 177,390 / 150,144 / 8,407 | $0.232 | Unknown | 9m 37s |
| `schemelike-metacircular-eval` | none | wrong_answer | 0 occurrences | 267,099 / 115,200 / 10,416 | $0.565 | Unknown | 11m 32s |
|  | squeez | wrong_answer | 0 occurrences | 644,441 / 498,176 / 22,887 | $0.834 | Unknown | 20m 30s |
|  | Headroom | wrong_answer | 28 occurrences | 634,439 / 410,368 / 18,874 | $0.946 | Unknown | 27m 20s |
|  | LLMLingua-2 | wrong_answer | 25 occurrences | 433,856 / 283,392 / 15,484 | $0.679 | Unknown | 18m 45s |
| `build-pov-ray` | none | pass | 0 occurrences | 550,029 / 423,168 / 11,823 | $0.600 | Unknown | 23m 2s |
|  | squeez | wrong_answer | 0 occurrences | 770,466 / 529,664 / 9,174 | $0.872 | Unknown | 18m 47s |
|  | Headroom | wrong_answer | 0 occurrences | 277,159 / 152,192 / 7,030 | $0.456 | Unknown | 9m 40s |
|  | LLMLingua-2 | wrong_answer | 13 occurrences | 287,941 / 212,096 / 7,943 | $0.362 | Unknown | 15m 32s |
| `dna-insert` | none | wrong_answer | 0 occurrences | 139,512 / 42,624 / 6,426 | $0.349 | Unknown | 4m 9s |
|  | squeez | wrong_answer | 0 occurrences | 24,556 / 0 / 2,501 | $0.099 | Unknown | 2m 15s |
|  | Headroom | wrong_answer | 0 occurrences | 156,543 / 67,456 / 11,321 | $0.409 | Unknown | 8m 7s |
|  | LLMLingua-2 | wrong_answer | 0 occurrences | 1,654,248 / 1,415,552 / 12,327 | $1.136 | Unknown | 28m 46s |
| `feal-differential-cryptanalysis` | none | pass | 0 occurrences | 230,832 / 144,896 / 12,866 | $0.444 | Unknown | 8m 8s |
|  | squeez | wrong_answer | 0 occurrences | 185,516 / 88,064 / 11,726 | $0.442 | Unknown | 8m 11s |
|  | Headroom | pass | 0 occurrences | 76,318 / 15,232 / 6,619 | $0.256 | Unknown | 4m 34s |
|  | LLMLingua-2 | pass | 8 occurrences | 24,250 / 6,272 / 3,622 | $0.101 | Unknown | 5m 48s |

### Before-and-After Token Counts from Preserved Source Text

The table counts only string segments that actually changed. Source and transformed text were tokenized with `o200k_base` from `tiktoken 0.14.0`, preserving spaces, line breaks, and characters exactly. Each occurrence remains when the same string was actually processed in multiple requests; only duplicate reads of the same evidence were excluded.

| Task | Condition | Changed segments | UTF-8 bytes | Tokens before → after | Token reduction |
|---|---|---:|---:|---:|---:|
| `crack-7z-hash` | Headroom | 18 occurrences | 62,388 → 33,570 | 21,456 → 11,502 | 46.4% |
| `crack-7z-hash` | LLMLingua-2 | 24 occurrences | 90,606 → 45,934 | 40,112 → 20,712 | 48.4% |
| `dna-assembly` | LLMLingua-2 | 7 occurrences | 1,071 → 441 | 490 → 231 | 52.9% |
| `modernize-scientific-stack` | Headroom | 5 occurrences | 840 → 630 | 205 → 160 | 22.0% |
| `modernize-scientific-stack` | LLMLingua-2 | 3 occurrences | 504 → 291 | 123 → 72 | 41.5% |
| `torch-tensor-parallelism` | LLMLingua-2 | 1 occurrences | 95 → 40 | 46 → 21 | 54.3% |
| `gcode-to-text` | LLMLingua-2 | 7 occurrences | 1,113 → 490 | 518 → 252 | 51.4% |
| `log-summary-date-ranges` | squeez | 2 occurrences | 14,926 → 3,546 | 6,654 → 1,652 | 75.2% |
| `log-summary-date-ranges` | Headroom | 2 occurrences | 580 → 402 | 260 → 188 | 27.7% |
| `log-summary-date-ranges` | LLMLingua-2 | 2 occurrences | 15,780 → 8,286 | 6,842 → 3,206 | 53.1% |
| `llm-inference-batching-scheduler` | LLMLingua-2 | 6 occurrences | 1,110 → 558 | 288 → 138 | 52.1% |
| `model-extraction-relu-logits` | LLMLingua-2 | 3 occurrences | 444 → 195 | 207 → 102 | 50.7% |
| `overfull-hbox` | LLMLingua-2 | 10 occurrences | 1,445 → 675 | 660 → 340 | 48.5% |
| `prove-plus-comm` | LLMLingua-2 | 7 occurrences | 963 → 408 | 446 → 210 | 52.9% |
| `raman-fitting` | LLMLingua-2 | 10 occurrences | 855 → 395 | 385 → 195 | 49.4% |
| `sqlite-with-gcov` | LLMLingua-2 | 4 occurrences | 1,112 → 572 | 284 → 140 | 50.7% |
| `vulnerable-secret` | LLMLingua-2 | 4 occurrences | 604 → 248 | 280 → 128 | 54.3% |
| `video-processing` | LLMLingua-2 | 6 occurrences | 972 → 372 | 438 → 192 | 56.2% |
| `chess-best-move` | LLMLingua-2 | 14 occurrences | 2,184 → 896 | 1,008 → 420 | 58.3% |
| `schemelike-metacircular-eval` | Headroom | 28 occurrences | 24,892 → 18,676 | 8,344 → 5,852 | 29.9% |
| `schemelike-metacircular-eval` | LLMLingua-2 | 25 occurrences | 22,225 → 15,900 | 7,450 → 4,500 | 39.6% |
| `build-pov-ray` | LLMLingua-2 | 13 occurrences | 3,614 → 1,755 | 923 → 455 | 50.7% |
| `feal-differential-cryptanalysis` | LLMLingua-2 | 8 occurrences | 632 → 292 | 304 → 156 | 48.7% |
| Total | 23 conditions | 209 occurrences | 248,955 → 134,572 | 97,723 → 50,824 | 48.0% |

Token counts could be calculated for 738 preserved input-output pairs: 209 changed and 529 remained identical. Another 166 pairs lacked preserved source text and could not be calculated; they were not replaced with zero. The table's tokens cover transformed segments only and are a different measurement unit from full request context, cached tokens, or API billing tokens.

## Comparison Conditions and Interpretation Limits

- The model was `gpt-5.4`; the API provider reported `gpt-5.4-2026-03-05`. The runs used `temperature=0` and `reasoning_effort=none`.
- Each condition started in a new container and workspace with the same task image, task files, and grader. No-compression screening began in task-list order, but differing runtimes changed completion order. Before `install-windows-3.11` and `kv-store-grpc`, `LLMLingua-2` ran only after `none`, `squeez`, and `Headroom` all finished. Starting with those two tasks, `LLMLingua-2` began when any one of the three slots became free. Starting with `raman-fitting`, conditions entered free slots in a predetermined order without waiting for all three slots to become available together. Interpret these observations with actual concurrency from each task's execution ledger.
- Five tasks were selected in the order that log candidates passing protection rules appeared in preserved no-compression records. After exhausting those candidates, new no-compression runs followed a prefixed task-list order rather than quality or expected savings. Completed evidence links the 15 tasks from `extract-elf` through `video-processing`, followed by `chess-best-move`, `schemelike-metacircular-eval`, `build-pov-ray`, `dna-insert`, and `feal-differential-cryptanalysis`.
- This selection path is not representative of all 89 tasks. Each condition ran once per task and API caching was uncontrolled, so run variability cannot be separated from condition effects.
- Model paths, request counts, log-candidate counts, and cached tokens differed by condition. Cost differences also appeared in conditions with no actual changes, so API cost differences between conditions are not interpreted as causal compression savings.
- `Headroom` produced both passing and wrong-answer outcomes when no string changed. These single runs cannot identify the cause of the quality differences.
- Run timing and concurrency for the three conditions and `LLMLingua-2` varied by task. Time and virtual-machine cost are observations from these runs, not compressor-speed comparisons.
- Blob and network cost includes only recorded writes and verification reads. It excludes Blob retention, unmetered network, shared idle time, approval waiting, and one-time setup.

<details>
<summary>Run identifiers, SHA-256 verification values, and original-precision figures</summary>

### Units and Sources for Detailed Evidence

- The source revision for the first task was `c079b143a9f51eeb823b52f39d02ec7a2a9fa87a`. Later completed conditions ran from `5e1f8655950471ea15b1b428632b074070dda020` or `00a8ba5903c8407746a984a82465a9e601032146`, which only removed the Harbor response timeout. Where a source boundary fell within a task, the detailed evidence preserves each condition's revision.
- **Provider logical requests** are ledger field `logical_model_calls`; **HTTP attempts** are `total_model_calls`, including transport retries; **Harbor stages** are completed agent stages in `turns`.
- **Eligible log candidates processed** is `compressor.completed_calls`, where the condition-specific transformation path was applied to candidates that passed protection rules; **actual changes** is `compressor.changed_occurrences`, where bytes differed before and after. Because `none` passes candidates through unchanged, its processed-candidate count may be nonzero.
- Per-condition ledger virtual-machine cost does not account for overlap among separate processes. The detailed tables apply the same post-hoc allocation formula to every work interval and also preserve ledger values.

### Technical Incompleteness and Virtual-Machine Interruptions

- The 104 conditions in the main text count only completed attempts. No-compression candidate-screening attempts that did not finish `summary.json` and remote verification are not counted as quality outcomes.
- The first `squeez` run for `llm-inference-batching-scheduler`, `preliminary-squeez-20260916T080029Z-760b7572`, and its first `LLMLingua-2` run, `preliminary-llmlingua2-20260916T080540Z-03d08a32`, did not complete because the virtual machine stopped. Quality and tokens come only from the post-recovery completed runs `preliminary-squeez-20260916T081117Z-4ae2d980` and `preliminary-llmlingua2-20260916T081117Z-7372522a`. Costs from interrupted attempts were neither combined with completed-attempt costs nor replaced with zero.
- Three no-compression screening attempts raised `BrokenPipeError` while returning responses to Harbor after the API had recorded HTTP 200 and usage. They did not finish workspace save-and-restore or regrading, so they are not counted as quality outcomes or candidate comparisons.

| Task | First response-delivery failure (UTC) | Last verified successful stage | Calculated API cost |
|---|---|---|---:|
| `make-mips-interpreter` | `2026-09-16 09:07:50.792` | HTTP 200 and usage recorded | $3.934268 |
| `polyglot-rust-c` | `2026-09-16 10:44:37.392` | HTTP 200 and usage recorded | $7.302372 |
| `rstan-to-pystan` | `2026-09-16 10:53:50.245` | HTTP 200 and usage recorded | $2.3310085 |
| Total | Not applicable | Preserved separately as technically incomplete cost | $13.5676485 |

**Observation.** In all three runs, the next request for the same task arrived about 604 seconds after the preceding request. The late existing response had recorded HTTP 200 and usage, but delivery failed against an already closed connection. The failure was confined to delivery of the API response to Harbor, not model API invocation or Blob upload.

**Action and limitation.** Source `00a8ba5903c8407746a984a82465a9e601032146` explicitly configures no HTTP timeout in Harbor's model client. A test connecting actual Harbor and LiteLLM to a local fake API handled a response later than the short default timeout with one external call. Later, during a no-compression run of `schemelike-metacircular-eval`, one request waited 2,554.6 seconds in the shared queue; the API then returned HTTP 200 with `finish_reason=stop` in 5.0 seconds, and Harbor received the response and continued to the next request. This supports that the full delivery path remained intact beyond 604 seconds in the actual service, but does not mean GPT-5.4 itself took 2,559.7 seconds to respond. A subsequent virtual-machine interruption ended this attempt before grading, so it is excluded from the quality denominator; the main text includes only the completed result from a separate recovery run.
- The first `LLMLingua-2` run for `video-processing`, `preliminary-llmlingua2-20260916T114955Z-fdc4776c`, ended with `provider_error` after receiving HTTP 500 on the 37th request following 36 HTTP 200 responses. Because the error preceded the first grading step, it is not a quality outcome. Its verified calculated API cost of `$0.516869` and conservative unknown amount of `$0.0618425` for the final request without usage are preserved separately. Quality, tokens, and completed cost in the main text come only from the separately run `preliminary-candidate-retry-20260916T121415Z-f958125c`, which completed remote verification.
- The first `squeez` run for `build-pov-ray`, `preliminary-squeez-20260916T141713Z-e8d31d85`, ended in a virtual-machine interruption after delivering 46 HTTP 200 responses to Harbor. The 47th logical request has a receipt record but no record that API transmission began. The attempt's verified calculated API cost of `$1.7630285` and input, cached-input, and output token counts of `1,944,593 / 1,515,264 / 20,726` are separated as technically incomplete cost. Virtual-machine cost and unknown cost could not be verified and were not replaced with zero. The main text includes only quality and usage from the separate post-recovery completed run `preliminary-squeez-20260916T171929Z-8233531d`.
- Azure Resource Health records `UserInitiated` interruptions at `2026-09-16 08:08:22.855 UTC` and `08:08:23.498 UTC`, but the caller field is empty. The user or process that requested the stop is unknown. A successful start is recorded at `08:10:26.619 UTC`.
- The same virtual machine later became deallocated again. Operating-system records show that it received a Hyper-V shutdown request at `2026-09-16 17:10:24 UTC`, began an orderly shutdown, and completed at `17:10:49 UTC`. Azure activity records show only a successful start at `17:15:49.373 UTC`; the preceding stop operation, caller, and correlation ID are absent, so the requester is unknown. The virtual machine's automatic-shutdown schedule was `Disabled` and was not changed. The eight attempts running at interruption were not converted into quality outcomes; their source records, verified usage, and unknown cost are preserved separately.

### Post-hoc Operator-Stopped Long Tail

At `2026-09-17 23:59 KST`, an operator stopped the five attempts below. This post-hoc decision followed about 10 hours of observation; it was neither a preregistered quality rule nor a general stopping rule for other runs. No condition had completed its first grading and restored regrade before the stop, so none is added to the main analysis of 26 tasks and 104 conditions.

| Task / condition | Attempt | Elapsed time | Logical requests / HTTP attempts / HTTP 200 / Harbor deliveries | Last actual progress (UTC) | Verified input / cached-input / output tokens | Calculated API cost / cost per HTTP 200 | Actual changes | Stop classification |
|---|---|---:|---:|---|---:|---:|---:|---|
| `circuit-fibsqrt` / none | `c0e8de9bfd362c80af60bb341fe734faac7b325cecca5475a0017812b9deccb9` | 10h 25m 53.318s | 278 / 278 / 278 / 277 | 277th delivery `15:03:26.628`; the 278th received HTTP 200 at `15:05:23.732` after the stop signal and was not delivered | 24,154,545 / 21,243,008 / 40,438 | $13.1961645 / $0.047468218 | 0 | `post_hoc_operator_stopped/censored`, quality unknown |
| `feal-linear-cryptanalysis` / none | `3e087b6a7ad346ca839b55617fac30bba2c066ab649567120481cc69afaef5c1` | 10h 25m 53.990s | 738 / 738 / 738 / 737 | 737th delivery `15:02:27.687`; the 738th received HTTP 200 at `15:04:29.458` after the stop signal and was not delivered | 37,842,271 / 31,517,952 / 60,058 | $24.5911555 / $0.033321349 | 0 | `post_hoc_operator_stopped/censored`, quality unknown |
| `winning-avg-corewars` / none | `6521ee5bdc507731ac87e7a177c4920e8e50d826a024e65817ee6565a5e94eaa` | 10h 10m 20.322s | 611 / 611 / 611 / 610 | 610th delivery `15:03:24.757`; the 611th received HTTP 200 at `15:04:24.871` after the stop signal and was not delivered | 36,366,405 / 31,291,648 / 45,092 | $21.1861845 / $0.034674606 | 0 | `post_hoc_operator_stopped/censored`, quality unknown |
| `tune-mjcf` / Headroom | `63973b047f800a8176174a1945438439e0db139a2955bba5597d33ba4eb8d9ac` | 10h 5m 11.146s | 865 / 865 / 865 / 864 | 864th delivery `15:03:28.543`; the 865th received HTTP 200 at `15:04:34.267` after the stop signal and was not delivered | 36,977,081 / 31,677,824 / 49,194 | $21.9055085 / $0.025324287 | 0 | `post_hoc_operator_stopped/censored`, quality unknown |
| `tune-mjcf` / none | `060b09d4b3983ca851c578ec76bfbe00e39974ea4275eb944b0eb313095d3bca` | 10h 5m 10.985s | 291 / 291 / 290 / 290 | 291st HTTP attempt started at `08:04:26.827`; the last HTTP 200 was the 290th at `08:03:11.037` | 10,049,216 / 8,248,064 / 21,823 + 1 unknown | $6.892241 + 1 unknown / $0.023766348 | 0 | `stalled_http_response`, quality unknown |

Four attempts sent their final pre-stop logical requests to the API after the stop signal and recorded HTTP 200 and usage, but could not deliver to the already closed Harbor connections. The counters and costs above use final transport events, including these four late responses. Each run's `summary.json` was created earlier and excludes its final response, so the two scopes must not be combined.

Verified calculated API cost for the five attempts totals `$87.771254`; the input-only estimate of `$0.1294175` for the 291st `tune-mjcf` request without usage is excluded. The average over 2,782 verified HTTP 200 responses is `$0.031549696`. The `$20.636931684` sum of virtual-machine costs recorded by the five attempts counts nearly the same single-VM time five times and cannot be used as final total cost. Applying `$0.403` per hour to the 37,554.430-second union of actual task-process intervals from `2026-09-17 04:38:21.977~15:04:16.407 UTC` yields `$4.204009802`. Verified Blob and network operation cost for the five attempt payloads is `$0.000054`; it excludes shared idle time, post-stop cleanup, Blob retention, and unmetered network. The verified subtotal for API, the single-VM interval union, and attempt-payload operations is `$91.975317802`. It is not a final total because one request remains unknown.

The stop-path `replay_mismatch` is not reported as a wrong answer because no first grading or restored regrade occurred and the evidence state is `incomplete`. All five attempt payloads completed remote upload and read-back hash verification. The `tune-mjcf` `none` run summary is a static file that remained `running` after its parent worker stopped, so it is not used as evidence of stop state. The pre-stop snapshot SHA-256 is `22990c747f4b265a3cb0d556939ea74dffc0b334f09955d7227476eb5927b0f9`. Stop handoff is preserved in a private immutable stop index; remote bundle payload SHA-256 `4776561fd65956d6de9c8f57342e055c3d90a2272b76827add7014cdadef841c` and source-tree SHA-256 `d0a065fb9c7bec9a7938095a132fed63be06e12748320056c3b12a4d9b64993f` were reread and verified at `2026-09-17 15:28:55.053 UTC`.

## Separate Cohort: `cancel-async-tasks`

This task ran before eligible log candidates were used as a selection criterion. All four conditions were `wrong_answer`, with the same verdict after restored-workspace regrading. Transformer-adapter calls and actual changes were both zero in all four conditions.

- Comparison ledger: `preliminary-20260916T022024Z-c68388c9`
- Comparison manifest file SHA-256: `58027a8ca71d05afb30cf0cb4a8610e2af0c308d860b4edf1f26a0521a3e01c2`
- Comparison manifest content SHA-256: `c4f8ce229b3dd4ef8e26f36eea14ae427569ef59a51fc376d295b75e542cbf2a`
- Comparison state-file SHA-256: `fa48366cf818a9bbaa1dedec83ebc5df2c306b4158d28229c40c8173703dd7c1`
- Image digest: `sha256:84c7fae6b256dcc56a350790e2a9715eefc7dad662a9d8e8a472363aa71ef18d`
- Task-file tree SHA-256: `1b6e83a625ffda559bf8511bcf0c708bcb26b04ffd8923b1dc90f14c19ddddaa`
- Grader source-tree SHA-256: `205c267bd18adccf19239f50f82f2e60caa32cb06065219046de30d8985c3175`

| Condition | Quality | Provider logical requests / HTTP attempts | Harbor stages | Eligible log candidates processed / actual changes | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|
| none | wrong_answer | 2 / 2 | Not verified | 0 / 0 | 2,375 / 1,152 / 593 |
| squeez | wrong_answer | 2 / 2 | Not verified | 0 / 0 | 2,527 / 1,024 / 542 |
| Headroom | wrong_answer | 4 / 4 | Not verified | 0 / 0 | 7,610 / 4,224 / 991 |
| LLMLingua-2 | wrong_answer | 2 / 2 | Not verified | 0 / 0 | 2,544 / 0 / 585 |

This initial ledger did not preserve the Harbor-stage count as a separate field. The unverified value was not replaced with provider request count or zero.

| Condition | Calculated provider cost | Recorded active virtual-machine cost | Verified Blob and network cost | Direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|
| none | $0.012241 | $0.011456 | $0.0000432 | $0.023740 | 102.337 / 113.223 |
| squeez | $0.012144 | $0.008764 | $0.0000432 | $0.020951 | 78.292 / 82.797 |
| Headroom | $0.024386 | $0.010150 | $0.0000432 | $0.034579 | 90.668 / 142.629 |
| LLMLingua-2 | $0.015135 | $0.009942 | $0.0000432 | $0.025120 | 88.809 / 207.622 |

The four work intervals did not overlap. Recorded active virtual-machine cost totals `$0.040311902`. This value excludes shared idle time, approval waiting, one-time setup, Blob retention, and unmetered network.

| Condition | Condition run ID | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|
| none | `preliminary-none-20260916T022026Z-944c88e1` | `e271bc1c03cf646f118addc2b04e6d1096fca4332f14a3abf9e5e191a9c7f972` | `8520741463753ac5f09216a2a4447d3f9b52778ab36958ee4bcd00d898f8753b` |
| squeez | `preliminary-squeez-20260916T022225Z-37bbde5e` | `f81d1763aea0e36c07e4e289ba1f2531e27abe78fdd96d90f3cf3c7e19db9d09` | `95cc34ab743b77381860053656a883835d8b48ba8e65099c09c3d3b5441254a4` |
| Headroom | `preliminary-headroom-20260916T022729Z-350beb1a` | `25c326bcd30d51ad74ab14d5e1739189a9d96b5680c5b6084096862a15469b58` | `fc52e47d32a7ce5ef3a2e80d82c63323be85697e08b8e55f702a3444c715a9b9` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T022355Z-67a07031` | `dd13acc029adb2b281685a01be42788a1a861fb498eac71f5a09e4bd4b3c8a93` | `cc35275f4e9b2734645a036a44136d0e1f5baf7f323ccdcbf8bcad7d8cf44358` |

This initial comparison preserved condition results inside the comparison state file rather than in separate per-condition result files. The table links each condition's actual run summary and attempt-file hash.

## `crack-7z-hash`

- Comparison ledger: `preliminary-candidate-continuation-20260916T034044Z-a7387c9f`
- Comparison manifest file SHA-256: `b432887f2974610ed4c9ad82a418ac0cafbf546edab35159b98ebe09d6341f8b`
- Comparison manifest content SHA-256: `2a5cd56e0d2905650ecd52d4f4064a07fe4b12a1ead08d1ed07d8d30928ad498`
- Image digest: `sha256:0f4453abd774c5a3d3d7e66ba28fae88ec2e49ada3a993b324ebc16c348666d3`
- Task-file tree SHA-256: `1abd0cb371b37e665eb35f40d6e6d49fb4559866c2fc1f6e5d6db0fdd5428d7d`
- Grader source-tree SHA-256: `c196b31f22e2f89855e85551fba964e4a75dd77b96475d90f4ff6cf5a4cc37ee`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | pass | 53 | 53 | 53 | 148 | 0 | 0 | 1,217,052 / 1,082,624 / 13,538 |
| squeez | pass | 24 | 24 | 24 | 45 | 0 | 0 | 261,471 / 138,880 / 7,123 |
| Headroom | pass | 20 | 20 | 20 | 87 | 18 | 0 | 233,658 / 146,432 / 5,575 |
| LLMLingua-2 | pass | 15 | 15 | 15 | 24 | 24 | 24 | 159,676 / 128,000 / 5,311 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc overlap-allocated virtual-machine cost | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.809796 | $0.096744 | $0.066055 | $0.0000432 | $0.875894 | 864.212 / 869.605 |
| squeez | $0.448043 | $0.050960 | $0.020269 | $0.0000432 | $0.468355 | 455.228 / 459.609 |
| Headroom | $0.338298 | $0.031338 | $0.010447 | $0.0000432 | $0.348788 | 279.945 / 284.162 |
| LLMLingua-2 | $0.190855 | $0.034335 | $0.034335 | $0.0000432 | $0.225233 | 306.711 / 435.954 |

The post-hoc virtual-machine allocation totals `$0.131105642` over the `1,171.167026s` union of actual work intervals and matches the sum of per-condition allocations. The three parallel conditions and the standalone `LLMLingua-2` condition did not run under the same operating conditions, so total condition time must not be read as a compressor-speed comparison.

| Condition | Candidate-input UTF-8 bytes | Adapter-output UTF-8 bytes | Actually changed candidate input → output | Changed-segment tokens (post-hoc calculation) |
|---|---:|---:|---:|---:|
| none | 479,874 | 479,874 | Unchanged | Not applicable |
| squeez | 28,244 | 28,244 | Unchanged | Not applicable |
| Headroom | 210,130 | 181,312 | 62,388 → 33,570 bytes, 18 occurrences | 21,456 → 11,502 tokens, 18 occurrences |
| LLMLingua-2 | 90,606 | 45,934 | 90,606 → 45,934 bytes, 24 occurrences | 40,112 → 20,712 tokens, 24 occurrences |

Provider cost differences are observations of full agent runs. Request counts and subsequent paths differed by condition, and `squeez` differed substantially in cost from `none` despite 0 actual changes. The cost difference in this single group is not interpreted as a causal compression saving.

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T034100Z-15a3ef03` | `bbe9c874a0f5edfc057c44283ac908eb90768e6230b70fbb1ffbd47b4b9b9045` | `b876ce82599b1454bd5e0f0b0bb9d07297e86acb918053c873844fef39749b07` | `af3fead33eedeb64b603c9b36812ddf6616505db45da62f84c75595c407871eb` |
| squeez | `preliminary-squeez-20260916T034100Z-f076e850` | `924e305e10ed8f3bcb979ad13d04a23ddde3e96c39d0db591685d4e347523de6` | `5af6763185ec87e73dcc4ddabef751dabf435b72d4fb355c8609e378bf007681` | `f050700581062fd63e0571185c2bb4c20c86960b7863129a917d5b7f3111bb0c` |
| Headroom | `preliminary-headroom-20260916T034100Z-b6bed5dd` | `f11849c8484bb2eeffb01b32f46da19aa14c1f9d078fa8ae5ebe390892c98c3b` | `10af850c3f6a423a916cbe45d83249a13ac6bc3b3be7fb94ccd4282a4abb133d` | `dd3d4d2a4490c7b681d3b0007ee416d4b772ee066378bb8b57ab1dab7dd8ae43` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T035537Z-c55293f8` | `8480ee954b6453d17a6b1a6723922b2ae35dac84bd293f8d0464c88f5dc2a765` | `ce6eb4285e8eb63dc71919d65d20da75f9a1d195ba26c162394c026bd2889d93` | `614c41dadb5c3cfdbdb2758ccdd75e64211e03a9e41a1a260c79abcc844be5f7` |

## `dna-assembly`

- Comparison ledger: `preliminary-candidate-20260916T040804Z-5ea9af72`
- Comparison manifest file SHA-256: `d214cf5a0fa4c3e748eabf44ac5a93e4df0814e5ab29ee006eca5a177a9c6842`
- Comparison manifest content SHA-256: `4641669e7f13e24ba5dda3cb9a295c9bc809c60d2f3d3d11e7f451926a118161`
- Image digest: `sha256:d1adf6835f1dd91205ba70e452c699d0aea601010038e5617f370716efb50569`
- Task-file tree SHA-256: `33f30f34089bbbe1c266ab88301d12d2cb9eb51c9cf5696041bab13468450511`
- Grader source-tree SHA-256: `6687e7c7a79d1029bca162a97c67976c890d4c4cdc0a6ee0681024e391b1483f`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | wrong_answer | 6 | 6 | 6 | 0 | 0 | 0 | 83,272 / 27,392 / 7,703 |
| squeez | wrong_answer | 8 | 8 | 8 | 0 | 0 | 0 | 81,442 / 49,024 / 5,634 |
| Headroom | wrong_answer | 8 | 8 | 8 | 0 | 0 | 0 | 157,470 / 27,008 / 12,172 |
| LLMLingua-2 | wrong_answer | 8 | 8 | 8 | 7 | 7 | 7 | 81,455 / 56,960 / 5,709 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc overlap-allocated virtual-machine cost | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.262093 | $0.020303 | $0.007286 | $0.0000432 | $0.269422 | 181.370 / 187.215 |
| squeez | $0.177811 | $0.017197 | $0.005732 | $0.0000432 | $0.183586 | 153.620 / 159.211 |
| Headroom | $0.515487 | $0.024302 | $0.011284 | $0.0000432 | $0.526814 | 217.085 / 222.781 |
| LLMLingua-2 | $0.161113 | $0.016155 | $0.016155 | $0.0000432 | $0.177311 | 144.315 / 234.964 |

The post-hoc virtual-machine allocation totals `$0.040456759` over the `361.400329s` union of actual work intervals and matches the sum of per-condition allocations. Only `LLMLingua-2` actually changed the 7 eligible log candidates; the direct transformation boundary was `1,071 → 441 UTF-8 bytes`. Post-hoc tokenization of the same 7 segments from preserved source text yielded `490 → 231 tokens`.

All four conditions were valid `wrong_answer` quality failures rather than technical errors. Restored-workspace regrading produced the same verdicts; the failures are neither hidden nor reclassified as technical exclusions.

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T040818Z-5bd568cd` | `21e9c192bbe07c39c25b3cea57325e8f5b8f4457ece30141156983b073d2459a` | `dcac8cf69d838e845de693389fe48cdaccd53cbb275440fd54ffbe1283477b81` | `2c202e9d94b3af81bc61547d8f71aa97b470a91807debef42fe6af0c7b15dbf8` |
| squeez | `preliminary-squeez-20260916T040818Z-9a110a37` | `423dd2816d6d48e648dce72947ab51a2950e9cfe29db82d2a3dd70ddfbd61c08` | `aa8a8d6dd93f265c40602b1290d3c65779850f9d00461421de7b586a145cde8b` | `2a55c31bd357d49c3fc4877633a1139ac3f2c95ddd2e221d63253d0786459ca0` |
| Headroom | `preliminary-headroom-20260916T040818Z-44b1ca83` | `ed20f6e27120eed45c9974c93d8597e855ba811dd837545d9c398f7098846303` | `d688f1597410736087a21693951e9b99132d7a905605b7a79cb12792fd72c36b` | `f560be491800daeb4360bcc95cb1551b69e004f23e49849c12f20bdc0942aa9a` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T041209Z-bc2ff477` | `33e9e7226443045bc9c901ef404c6278f704e2e7410f0a44e9336c5354a8b979` | `6c2a4049d2cb7695ba3e5d6661df5945e55bd5a2930144d7a427c8084d1299e5` | `133195c9b3337553690604d67899fd0930e1451221f570b675e8513535fbe49b` |

## `modernize-scientific-stack`

- Comparison ledger: `preliminary-candidate-20260916T045049Z-dc600270`
- Comparison manifest file SHA-256: `1c4cf2185eb8cce5ada24fad60a586e3bed4dd4d495570105f98610088a6206e`
- Comparison manifest content SHA-256: `2a41ce97687936a9305dc256078b4b82b8225dc46fabe74c7a76da2f7ad91034`
- Image digest: `sha256:64e69cee13bf6b0b9016e735b51891bce996a60f1e2d1a005bf12c949e221d71`
- Task-file tree SHA-256: `62c5482bd23e28d9dcf59bc0dbeff773de079cc99959920c17cae815b0e748f5`
- Grader source-tree SHA-256: `e218f92db8c5f88481407eeee7d739446aba827b042c720003d11f1fe34d1192`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | pass | 6 | 6 | 6 | 5 | 0 | 0 | 23,131 / 5,504 / 1,864 |
| squeez | pass | 6 | 6 | 6 | 5 | 0 | 0 | 24,857 / 4,480 / 2,169 |
| Headroom | pass | 6 | 6 | 6 | 5 | 5 | 0 | 22,246 / 8,832 / 1,749 |
| LLMLingua-2 | pass | 4 | 4 | 4 | 3 | 3 | 3 | 11,573 / 4,992 / 1,241 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc overlap-allocated virtual-machine cost | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.073404 | $0.013407 | $0.004523 | $0.0000432 | $0.077969 | 119.761 / 125.118 |
| squeez | $0.084598 | $0.013328 | $0.004452 | $0.0000432 | $0.089093 | 119.055 / 123.830 |
| Headroom | $0.061978 | $0.013305 | $0.004438 | $0.0000432 | $0.066459 | 118.854 / 122.517 |
| LLMLingua-2 | $0.036316 | $0.008277 | $0.008277 | $0.0000432 | $0.044635 | 73.935 / 162.673 |

The post-hoc virtual-machine allocation totals `$0.021689266` over the `193.750264s` union of actual work intervals and matches the sum of per-condition allocations.

| Condition | Candidate-input UTF-8 bytes | Adapter-output UTF-8 bytes | Actually changed candidate input → output | Changed-segment tokens (post-hoc calculation) |
|---|---:|---:|---:|---:|
| none | 830 | 830 | Unchanged | Not applicable |
| squeez | 830 | 830 | Unchanged | Not applicable |
| Headroom | 840 | 630 | 840 → 630 bytes, 5 occurrences | 205 → 160 tokens, 5 occurrences |
| LLMLingua-2 | 504 | 291 | 504 → 291 bytes, 3 occurrences | 123 → 72 tokens, 3 occurrences |

All four conditions retained the same `pass` verdict after restored-workspace regrading. Candidate-input byte totals and provider usage are observations from the paths the model actually followed in each condition, not fixed inputs controlled across conditions.

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T045103Z-5e0ab8ee` | `a0133e8921c6d24a4f9017090deb9a30f0a6ab6e3f7f05771a6b025916792d6f` | `770720611ad74af6b85f04e54c47ac245a6f27acc9c9db3f3d5d7cb7945a6bae` | `1b66b32a71a2999269313914d2f50738d675737b0d3f1f3e92e31bbefe27f7c7` |
| squeez | `preliminary-squeez-20260916T045103Z-fa7f8692` | `2c893224c46e89a995747fb3f9fd029758bbcef6267794782b0db7410a385fd0` | `6b89322313a3730959fd7e5387a36a708842c24d35fed0f4c3c1d39f1104ba38` | `39b13a1d6ee6209e8ad53da9898bea2279306808fc1022cd1c61720ac6d05ca3` |
| Headroom | `preliminary-headroom-20260916T045103Z-0a5e9b31` | `c06e10fb9d8b3552c933789707fc6bb63ca4eb4653a14a48d3d2471c00995aad` | `4d35afe235819ac9055eda358c03371a7c32b56b19789e32cb9e837ecb27d7ea` | `5019ec71b60a651f3f02079838705cf774e37c2a3a291d2c97ce7b2daebe4df4` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T045316Z-ca4151e5` | `df7abf3ae646af8ee02107987ceee8a5fa7e67f89a324567498224e0a2f86a65` | `d1d4ea98a0b47e0184771549474e3f432d45433808be6502af9744e59b130bbc` | `c6ccc991f8064dfe6e5c43ee527c2d5007e44788cdcea424b6efea7ecc766f70` |

## `sam-cell-seg`

- Comparison ledger: `preliminary-candidate-20260916T050028Z-af2d2e76`
- Comparison manifest file SHA-256: `b9c36b38d2ca14e5b9163d352863c1165e04634dd9cc80cfdd6611b0c8075296`
- Comparison manifest content SHA-256: `6a23eea084bc8c383221c7a010fa37de628998ed2bae99c6d6c55bd7cfa270aa`
- Image digest: `sha256:d76bdeef19d8113f4094013249c982eca93e62e46130484846269b2d378879d0`
- Task-file tree SHA-256: `0db189b462ac19ca1c7a94bb51037c7d6f4f64cf3c626fbb2acbe643b6f4f6e6`
- Grader source-tree SHA-256: `ec76e726b89e77baee578707b9818b6376c68202d710a14cfeddf319cff2d676`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | pass | 5 | 5 | 5 | 0 | 0 | 0 | 43,579 / 19,328 / 8,081 |
| squeez | pass | 6 | 6 | 6 | 5 | 0 | 0 | 37,841 / 10,240 / 4,764 |
| Headroom | pass | 4 | 4 | 4 | 0 | 0 | 0 | 38,796 / 14,720 / 7,469 |
| LLMLingua-2 | pass | 5 | 5 | 5 | 0 | 0 | 0 | 32,391 / 18,048 / 4,451 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc overlap-allocated virtual-machine cost | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.186675 | $0.035469 | $0.012982 | $0.0000432 | $0.199699 | 316.841 / 318.514 |
| squeez | $0.143023 | $0.028578 | $0.009535 | $0.0000432 | $0.152601 | 255.284 / 256.486 |
| Headroom | $0.175905 | $0.035491 | $0.013031 | $0.0000432 | $0.188979 | 317.040 / 318.418 |
| LLMLingua-2 | $0.107135 | $0.029068 | $0.029068 | $0.0000432 | $0.136246 | 259.668 / 345.897 |

The post-hoc virtual-machine allocation totals `$0.064615492` over the `577.210349s` union of actual work intervals and matches the sum of per-condition allocations.

| Condition | Candidate-input UTF-8 bytes | Adapter-output UTF-8 bytes | Actually changed candidate input → output | Changed-segment tokens (post-hoc calculation) |
|---|---:|---:|---:|---:|
| none | 0 | 0 | No eligible log candidates | Not applicable |
| squeez | 1,090 | 1,090 | Unchanged, 5 occurrences | Not applicable |
| Headroom | 0 | 0 | No eligible log candidates | Not applicable |
| LLMLingua-2 | 0 | 0 | No eligible log candidates | Not applicable |

The preserved no-compression attempt used for advance selection had 1 eligible log candidate, but model paths differed in these four new runs and only `squeez` produced a candidate. `squeez` did not change it, so this group contains no observation of compression actually being applied. Cost differences across the four conditions are not interpreted as compression savings.

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T050030Z-e465ea92` | `d8b3c6e6161e7e6ba62ced64b144b968ec8c432526a43134a5b64379b0aeaaba` | `4504c0e6876468f925e563524ad62895a2180f644b7860c39e0bbd0e98245319` | `fa9beb39ffcc9be5f73ec0cdf6fa57c729221289a023eff8950f9add6200fbe5` |
| squeez | `preliminary-squeez-20260916T050030Z-c10b9987` | `fa35429d2188cd1130b4f2039b0b3dcac2d04452f123e177b99e7dbc4d09a050` | `3c1889d68786330bca6c623c0a1839925368a92e0e51a2dc438700ecb460f1da` | `e5eacc6402ab0a5ca6655282947b58078af89f82a0f40c516f26dee1f1c25cf7` |
| Headroom | `preliminary-headroom-20260916T050030Z-3adebd5f` | `1c26f198d5a020b14d295d20c526c275bd6228ec27c73251c51335f2e9802d34` | `89fe43ef3c58cb29995c35be1cc1671f8fe89b3fa5b78ae7b88b125c65ea7853` | `b3a6ec4d58fb51fb3d51852af22795f71a45208275d51ea5f96f6dcec236b6f2` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T050558Z-ae86b7b2` | `50309eceeb9c36a1ce0c72d513bbfa79e806e25731b7d272c7be51201595e759` | `e91906bcc9c6c6764615560cc5f8c323ced3e2072e929fd27b269eb5f90ef820` | `b148c9cbf39b8ddfb65ade434f5c7554312a663302effe8926fa830cebc71f7c` |

## `torch-tensor-parallelism`

- Comparison ledger: `preliminary-candidate-20260916T051248Z-73a0b4fd`
- Comparison manifest file SHA-256: `ac6075a9e041638fcb03a87d5ee1155ae46541289111e87de6fc9a9b7ca3605e`
- Comparison manifest content SHA-256: `b3412d33c4c74adab1a989b4d770cf99962cb98a1014761ea03ac1e788c24abb`
- Image digest: `sha256:c50ac169e11465f41b49749fe87e4487f24d31a0c39c0906cd3242cc5499c690`
- Task-file tree SHA-256: `9986acd4e26d496dbcb3ce83e6b3e036160ea93b798780dbd9c0a691a3ae09f6`
- Grader source-tree SHA-256: `a7b6a9426ab8af530c36278ff251b3435c4561897b139856e169fbc93c259a58`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | wrong_answer | 3 | 3 | 3 | 2 | 0 | 0 | 6,262 / 0 / 1,565 |
| squeez | wrong_answer | 2 | 2 | 2 | 1 | 0 | 0 | 4,660 / 0 / 1,319 |
| Headroom | wrong_answer | 3 | 3 | 3 | 2 | 0 | 0 | 7,568 / 0 / 1,167 |
| LLMLingua-2 | wrong_answer | 2 | 2 | 2 | 1 | 1 | 1 | 3,963 / 0 / 1,272 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc overlap-allocated virtual-machine cost | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.039130 | $0.070116 | $0.024445 | $0.0000432 | $0.063618 | 626.344 / 631.604 |
| squeez | $0.031435 | $0.068851 | $0.023177 | $0.0000432 | $0.054655 | 615.049 / 621.032 |
| Headroom | $0.036425 | $0.067521 | $0.022508 | $0.0000432 | $0.058976 | 603.162 / 608.294 |
| LLMLingua-2 | $0.028988 | $0.030490 | $0.030490 | $0.0000432 | $0.059521 | 272.370 / 364.824 |

The post-hoc virtual-machine allocation totals `$0.100620115` over the `898.839734s` union of actual work intervals and matches the sum of per-condition allocations.

| Condition | Candidate-input UTF-8 bytes | Adapter-output UTF-8 bytes | Actually changed candidate input → output | Changed-segment tokens (post-hoc calculation) |
|---|---:|---:|---:|---:|
| none | 190 | 190 | Unchanged, 2 occurrences | Not applicable |
| squeez | 95 | 95 | Unchanged, 1 occurrences | Not applicable |
| Headroom | 190 | 190 | Unchanged, 2 occurrences | Not applicable |
| LLMLingua-2 | 95 | 40 | 95 → 40 bytes, 1 occurrences | 46 → 21 tokens, 1 occurrences |

All four conditions were valid `wrong_answer` quality failures rather than technical errors, and restored-workspace regrading produced the same verdicts. The 1 direct `LLMLingua-2` transformation and full-run cost are separate observations; a single quality and cost difference does not establish a causal compression effect.

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T051250Z-cefdb89b` | `d6abc88b04f31c86700af89caad74ac2ca8428c96de996060a623cd2d9d59a90` | `3c2fe67a6681dc45b979a966208a1e0d658df240572ff09acc92f5af1a10b5e6` | `af0861d64c804788683595d5ba05599d9f7fe963a135737f3466c0799c1962bb` |
| squeez | `preliminary-squeez-20260916T051250Z-7c851981` | `c56da022b6b0d4cd2eccdb9abac2e1ad3214439e9bbb027ccdc17bc81ec34136` | `007eccf70bff95b4027fe3d6b40c23d0bc4e8bf73e17c453d2dc203ad5edf59e` | `9a60306cb52c61a85346d8af492b4f8da706f2af6b4e59875bcaa22131995013` |
| Headroom | `preliminary-headroom-20260916T051250Z-be58bc2f` | `914201637fbb0527fb7ef5774fc833add91cb722c0af71d80f8e009cfc2d5eb7` | `0fe85b04c1cedaf91a2c477bebc05771c28ecb59c438ea3b246dd154add64556` | `190fa69d752ab4687af6f3b8b5410726ca4c44f231ef0c0de9bcbc185eaee84a` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T052331Z-1079341c` | `804e3288bc68fecc335581535791c22be2838059897af91256442353e1322177` | `6553f52d86850b689076f2a37eb007e67d3284edc50a6b365219a9f277c0cd13` | `485b16aebf9a5a17b3bcbe954686613944252ffdbb4c7c8069916fa5c1ed7cc4` |

## `extract-elf`

After running every candidate task directly identifiable in preserved no-compression records, `extract-elf` was selected as the first untested task in the prefixed task-list order. Neither quality outcome nor expected cost savings informed selection. A separate full `none` run passed and completed regrading and Blob verification. Its second provider request exposed 1 eligible log candidate totaling 193 UTF-8 bytes without an additional model call, after which the four conditions ran.

- Comparison ledger: `preliminary-candidate-20260916T053916Z-90f05ebf`
- Comparison manifest file SHA-256: `3888c1c000cec2ed4618514f3cef094d642a52414f73f4cc98752289d6838708`
- Comparison manifest content SHA-256: `7bbbc5838153c95c723f1c6addd7011df737f8a53166aace622d7bc7ca7f8eb5`
- Comparison state-file SHA-256: `9c56da5034389f7f49fbeecb25faea5c9c8a74bbc903a7e1fd48d38f9d1ea54d`
- Image digest: `sha256:6932e4cb318464307eacd497ef8dc617eaf551b6a90231f815ec0b911895cfed`
- Task-file tree SHA-256: `ec291e5bff1262e1dc176f3b06931a53c17d45d461b398763a8cf0c217e1cec6`
- Grader source-tree SHA-256: `87b7da138926c05a1a8f878f6bc190de575e452e3e339864b01fd2c61543da91`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | wrong_answer | 6 | 6 | 6 | 0 | 0 | 0 | 51,050 / 23,936 / 3,960 |
| squeez | pass | 5 | 5 | 5 | 0 | 0 | 0 | 24,161 / 0 / 1,863 |
| Headroom | pass | 3 | 3 | 3 | 0 | 0 | 0 | 12,773 / 0 / 1,272 |
| LLMLingua-2 | wrong_answer | 5 | 5 | 5 | 0 | 0 | 0 | 40,836 / 23,296 / 2,779 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc overlap-allocated virtual-machine cost | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.133169 | $0.011915 | $0.005876 | $0.0000432 | $0.139088 | 106.438 / 116.141 |
| squeez | $0.088348 | $0.009077 | $0.003034 | $0.0000432 | $0.091424 | 81.088 / 90.906 |
| Headroom | $0.051013 | $0.009056 | $0.003031 | $0.0000432 | $0.054087 | 80.902 / 90.806 |
| LLMLingua-2 | $0.091359 | $0.009639 | $0.009639 | $0.0000432 | $0.101041 | 86.108 / 179.361 |

The post-hoc virtual-machine allocation totals `$0.021580319` over the `192.777041s` union of actual work intervals and matches the sum of per-condition allocations. The three parallel conditions and the standalone `LLMLingua-2` condition did not run under the same operating conditions.

The advance `none` run exposed an eligible log candidate, but the four new conditions followed different agent paths and produced no eligible log candidates during execution. Transformer calls and actual changes were both 0 in every condition. Quality and cost differences are valid run observations, but not evidence of an applied-compression effect. All four conditions retained their verdicts after restored-workspace regrading, and remote-data hashes were verified.

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T053918Z-c0cdf1c7` | `95c065dec75bf7fe3208d933dbd9eb0d138d8d146ab57daffab5e1c7965819ea` | `6e77326ec9b03ccec76b4a081f19b3cfbfbe28c38aeebce885e0b66be7f534ec` | `c1fc7440d32d64ebc202d5ea935b935f7cf5966181ce0a3cf57fa93ee1796130` |
| squeez | `preliminary-squeez-20260916T053918Z-db43a633` | `0337ce1a4a45a16b28a4146989a523b892376a45712670b889df97061fd69062` | `7a7c73e7055fef6127c4f22beee892cba287b99b2ac7fa52b5706d94a1d441ed` | `6d76f4fec0876f9ea7da8f864dd8e6b73ef1b0695f25f3b874d4f5824e5df618` |
| Headroom | `preliminary-headroom-20260916T053918Z-ac89be1d` | `6e6b1d5a3eb4fde3bc3013bd438eff1a393ddbda35fe93f847eb8c580943218d` | `0ccdaee63fee1ade3f069c681f48d7cf592469103f1dfec65b5799e95a61a6e6` | `056a5d5907eea9b45c33423a785311d879fafdd4a06b915a66a348210ed2f5fe` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T054115Z-a129b591` | `e21cc5df47b8ca169ef3bcd0034b4fcda87713bbcbc12d20b201c580bab0ff78` | `b29bc93ddde4eef24dcb260da51ee8fb6817b90f8ee70e9fa929ea0534abe04d` | `234587f63c42623d0c4b90070163500b8820b6bac74613baf7ee6fb7c17dc4e7` |

## `financial-document-processor`

After existing candidates were exhausted, a new no-compression run followed task-list order and exposed 1 eligible log candidate. Neither quality outcome nor expected savings informed selection. All four comparison conditions were valid `wrong_answer` outcomes rather than technical errors, and restored-workspace regrading produced the same verdicts. There were no actual changes.

- No-compression candidate-screening run: `screening-diagnostic-20260916T055249Z-5ad9bedd`
- No-compression candidate-screening attempt: `6a9e8419d3735bdb6f81c4cf9e663a8d0d75886286ac728ef1fca89b968963e5`
- Comparison ledger: `preliminary-candidate-20260916T060254Z-6b0babcd`
- Comparison manifest file SHA-256: `c0e7a757bd9b06d36fe1d105013921b962b0434652fa39eaba161d0dff8d3a0b`
- Comparison manifest content SHA-256: `6d25b90569aa3e03c061d014ac0927e89b0cb6f41297f622c5c9e14ce9e687c2`
- Comparison state-file SHA-256: `ae490a94be3940259f44283446ad486cb7633cfc579efc30855127fbfa0a1926`
- Image digest: `sha256:ef6c9cfaaf14cdd200163008a188d5baa9f626f3bfb8d3e7d6f30c08518e6251`
- Task-file tree SHA-256: `6f267566526f582e337fc2033f51437b63b8b27afa3e53802fb9fb5f25c82dc7`
- Grader source-tree SHA-256: `3088f953d754e95e9f24fcc38e92322eaba9fe193329588088f55e8a79013228`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | wrong_answer | 7 | 7 | 7 | 11 | 0 | 0 | 56,275 / 0 / 5,600 |
| squeez | wrong_answer | 13 | 13 | 13 | 4 | 0 | 0 | 244,315 / 129,792 / 6,280 |
| Headroom | wrong_answer | 7 | 7 | 7 | 0 | 0 | 0 | 41,804 / 0 / 3,923 |
| LLMLingua-2 | wrong_answer | 16 | 16 | 16 | 0 | 0 | 0 | 240,376 / 216,064 / 7,760 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc overlap-allocated virtual-machine cost | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.2246875 | $0.025552089280287425 | $0.009963519541521868 | $0.000043200000000000007 | $0.23469421954152188 | 228.25689790100114 / 239.290537 |
| squeez | $0.4129555 | $0.030271986088885202 | $0.014683416350119646 | $0.000043200000000000007 | $0.42768211635011964 | 270.419740329 / 281.075641 |
| Headroom | $0.163355 | $0.016875150591731072 | $0.005625050197243691 | $0.000043200000000000007 | $0.1690232501972437 | 150.745781960999 / 158.274173 |
| LLMLingua-2 | $0.23119600000000004 | $0.04432333626528581 | $0.04432333626528581 | $0.000043200000000000007 | $0.2755625362652859 | 395.94049328799883 / 506.609855 |

The union of actual work intervals is `666.3601996898651s`, with virtual-machine cost of `$0.07459532235417102`; this matches the sum of per-condition post-hoc allocations. Per-condition virtual-machine costs in the ledger charge the full machine rate to each overlapping process and therefore are not used as final comparison cost.

| Condition | Candidate-input UTF-8 bytes | Adapter-output UTF-8 bytes | Actually changed candidate input → output | Preserved-source token calculation |
|---|---:|---:|---:|---:|
| none | 4,654 | 4,654 | Unchanged, 11 occurrences | Not calculable because source pairs were not preserved: 11 occurrences |
| squeez | 5,680 | 5,680 | Unchanged, 4 occurrences | 2,828 → 2,828 tokens, 4 occurrences |
| Headroom | 0 | 0 | No eligible log candidates | Not applicable |
| LLMLingua-2 | 0 | 0 | No eligible log candidates | Not applicable |

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T060306Z-0589cfc5` | `0c0149d21859e96f17fd6878ea1aac7128812e8be116355dd1a693a8bc8f1dda` | `a770c97296a3778d7086ab2132c6ba2b5c2416753f22061623345c5bb2ca4d86` | `fb4bdf1dcd07a73852805046a0ae87640474764a62944db6f537aa0ee146b6b1` |
| squeez | `preliminary-squeez-20260916T060306Z-c454d40c` | `63836a8748cda821e8170ab4dd9a926720b3e435a2ff5743ea35269ae11f2a88` | `20842a63547a6add12465ba4ead5232ca564a4bf8a476e75bcf8da4ffead4cf7` | `c69e2e13d429682a389200d869fce56133fc43610bdc5c6e25e3b281efc35d31` |
| Headroom | `preliminary-headroom-20260916T060306Z-f921b110` | `5913d8f7debaa0579d83d61f75f734652bbb8980c620e24cf444adf9de8a4c3b` | `343616223018ff3d912b1c43cebda725f7b1b6012f7db800c39420cf1bd6dcdf` | `6f03d894b3cba566b5a8b72627143348e50e45fb32b6c615ade260c2157c96e4` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T060756Z-96432238` | `44c7db7db86f65eb52b68b635721c0702a1ecae8816e7cfb748969e28475c3a5` | `0b1a94dc2392b6075b63041d9422c1212c9bc8e5c0214f012cb814f49caea38f` | `036abcfcf85469e488fd2f674fb9275b30f00b72c8c62fa9c691d2b11f982f74` |

## `gcode-to-text`

After the `financial-document-processor` comparison, this was the first untested task in the prefixed task-list order. A new no-compression run exposed 1 eligible log candidate totaling 159 UTF-8 bytes in its second provider request without an additional model call, after which the four conditions ran. Neither quality outcome nor expected savings informed selection.

- No-compression candidate-screening run: `screening-diagnostic-20260916T061842Z-cce95bbe`
- No-compression candidate-screening attempt: `6e308ffc2db1411c4328e6710d4313656df2612ccd9e113f7c6983300598f09e`
- Comparison ledger: `preliminary-candidate-20260916T062836Z-6d020450`
- Comparison manifest file SHA-256: `662bc1d3659a3b3159ea32a57bafc633bc1729dba4a436040b28eadfeff1fbcf`
- Comparison manifest content SHA-256: `fabadd0a7eb93b3f8e94bbc8e4aec13b8bedc73fc98628c3d940471463ea479c`
- Comparison state-file SHA-256: `c2bbeab9cbb1950e19598f2ec3da33e15b60a0d36e9f83ca32e395f05a2a3a05`
- Image digest: `sha256:0979ef40c6a3e8c4e7ab5b6c2524c74625a84799e15cd45dd98dcf83b11efd4d`
- Task-file tree SHA-256: `c794a615c1a24a5efd184418f26a88bcf584848146b9546330a8f2024c20d8c4`
- Grader source-tree SHA-256: `045cc716c14efde3b0dcff5fc7c85ec5d18bfc6ce66f8b40a418fa2a3a4acda0`
- Applied grader SHA-256: `20812107bc3bfc541728a2d10e3da0552e907d949e1347a03d33aa26954f8902`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | wrong_answer | 4 | 4 | 4 | 3 | 0 | 0 | 17,804 / 0 / 1,296 |
| squeez | wrong_answer | 58 | 58 | 58 | 0 | 0 | 0 | 1,976,777 / 1,862,400 / 31,502 |
| Headroom | wrong_answer | 6 | 6 | 6 | 5 | 0 | 0 | 50,022 / 8,576 / 3,956 |
| LLMLingua-2 | wrong_answer | 8 | 8 | 8 | 7 | 7 | 7 | 83,235 / 69,760 / 5,489 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc overlap-allocated virtual-machine cost | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.063950 | $0.008428336291578081 | $0.0028176546285770556 | $0.000043200000000000007 | $0.06681085462857706 | 75.2903647710009 / 86.729634 |
| squeez | $1.2240725 | $0.07578125044014719 | $0.06846251434341626 | $0.000043200000000000007 | $1.2925782143434162 | 676.954116369001 / 690.500115 |
| Headroom | $0.165099 | $0.011813945551514627 | $0.004507333328414846 | $0.000043200000000000007 | $0.16964953332841486 | 105.53401855099946 / 117.589333 |
| LLMLingua-2 | $0.1334625 | $0.012785658273498217 | $0.012785658273498217 | $0.000043200000000000007 | $0.14629135827349823 | 114.21433221799998 / 209.50078 |

The union of actual work intervals is `791.2242631912231s`, with virtual-machine cost of `$0.08857316057390636`; this matches the sum of per-condition post-hoc allocations. `squeez` produced no eligible log candidates across 58 requests, `Headroom` left 5 candidates unchanged, and only `LLMLingua-2` actually changed its 7 candidates.

| Condition | Candidate-input UTF-8 bytes | Adapter-output UTF-8 bytes | Actually changed candidate input → output | Preserved-source token calculation |
|---|---:|---:|---:|---:|
| none | 477 | 477 | Unchanged, 3 occurrences | 3 identical strings |
| squeez | 0 | 0 | No eligible log candidates | Not applicable |
| Headroom | 795 | 795 | Unchanged, 5 occurrences | 5 identical strings |
| LLMLingua-2 | 1,113 | 490 | 1,113 → 490 bytes, 7 occurrences | 518 → 252 tokens, 7 occurrences |

All four conditions were valid `wrong_answer` outcomes rather than technical errors, and restored-workspace regrading produced the same verdicts. Direct `LLMLingua-2` transformations and total API usage by condition are separate observations. One run per condition on one task cannot establish a causal compression effect on quality or cost.

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T063222Z-d8d7d119` | `0aebf68c31d9e97e9eb514202d671ff1e046dd62e2147ca97496d14ccc2f0581` | `077ee0427bf38567aa74e3eb0739ed5350b183124368ab109e4852c12066f351` | `5cc820a52b4ed584a7e8233dc1d2a1b38607335f3ce9f23e6aa20d0e783eedb9` |
| squeez | `preliminary-squeez-20260916T063222Z-0a4fba8b` | `26126b9f76d4b76636d20d728502fdbb6ea0d6d370f1ef8df05b363e97583094` | `14a756f9c05611051d3ad84497f184650020818cee0517734ff588b14897e5c3` | `2623ad62da79333865880c0b49fcc03d88474cdc020efcd376fa5bc0f61d7fa9` |
| Headroom | `preliminary-headroom-20260916T063222Z-2201cd03` | `689b48d311b49a7ae871a77da41b75db960d5da24dd7eb3a908b4b05b9c88f3c` | `02b8a42e5516de56ca5d9790238ba5938fc279d329a09e59552fe97656d2e8bf` | `39d45b1b5ffe87d80b429fc2b914e9f19eeedeefe0ff86af5e32fac446938eb6` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T064353Z-5939b9df` | `5242c9a09e5b752e0093c8a8b7eee403e63ef81f34defc9f30fc23801d62cb77` | `4ffc70e3d901ce6f83f22abcd42eb848dfe3dfbb36b8a4afbd243365c9ad41cc` | `3dd335b8cea12d8f963d44b2fd023766f3c28dcdd9c2f3dc1e4c1f552b543d69` |

## `install-windows-3.11`

A new no-compression run followed the fixed task-list order. Its fourth provider request exposed 1 unprotected eligible log candidate totaling 9,934 UTF-8 bytes without an additional model call, after which the four conditions ran. Neither quality outcome nor expected savings informed selection. All four conditions were valid `wrong_answer` outcomes rather than technical errors, and restored-workspace regrading produced the same verdicts.

- No-compression candidate-screening run: `screening-diagnostic-20260916T071650Z-e6009e22`
- No-compression candidate-screening attempt: `eccf5492978a7107cc5d70d3dd6a7dc6d2febf849ec52903c586dfa7b9798956`
- Comparison ledger: `preliminary-candidate-20260916T072209Z-3471c09d`
- Comparison manifest file SHA-256: `be3755995478e94a492c4a7cb04cbead0b9f03454361dc6620f5859b24d45792`
- Comparison manifest content SHA-256: `fc526e1e04554397db54bdfd8460337fe78067d1a35a7bbbf5cc37920969ea6f`
- Comparison state-file SHA-256: `82bb1ccf52c6118cc11f72e7714308d7db5b0167769bbdb2db6c183a0e9eb875`
- Image digest: `sha256:c6695097316ef8810abce0545e347e65354aef9d51d4f7f662c3242e742f6a3e`
- Task-file tree SHA-256: `2f3a37020767ae28445a97ce5859b8e425e38c4e34d5c45600209527c0d184e0`
- Grader source-tree SHA-256: `c97cef6b63f65e3fe8bded30301bf10aaa25b6b9ae405f5580efe8529dbf7aaf`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | wrong_answer | 7 | 7 | 7 | 0 | 0 | 0 | 44,986 / 8,192 / 2,550 |
| squeez | wrong_answer | 7 | 7 | 7 | 5 | 0 | 0 | 58,104 / 23,168 / 3,137 |
| Headroom | wrong_answer | 7 | 7 | 7 | 0 | 0 | 0 | 49,485 / 28,672 / 2,774 |
| LLMLingua-2 | wrong_answer | 11 | 11 | 11 | 0 | 0 | 0 | 77,090 / 65,024 / 3,773 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc overlap-allocated virtual-machine cost | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.132283 | $0.021233 | $0.007085 | $0.0000432 | $0.139411 | 189.671 / 215.313 |
| squeez | $0.140187 | $0.022701 | $0.008566 | $0.0000432 | $0.148796 | 202.792 / 223.750 |
| Headroom | $0.100811 | $0.021212 | $0.007076 | $0.0000432 | $0.107930 | 189.486 / 214.923 |
| LLMLingua-2 | $0.103016 | $0.021403 | $0.021403 | $0.0000432 | $0.124462 | 191.192 / 294.902 |

The union of actual work intervals is `394.211443s`, with virtual-machine cost of `$0.044129780980277776`; this matches the sum of per-condition post-hoc allocations. `LLMLingua-2` occupied a free execution slot after one of the three conditions finished, so its operating conditions differ from earlier tasks where it ran alone after all three parallel conditions.

| Condition | Candidate-input UTF-8 bytes | Transformed-output UTF-8 bytes | Actual changes |
|---|---:|---:|---:|
| none | 0 | 0 | No eligible log candidates |
| squeez | 1,390 | 1,390 | Unchanged, 5 occurrences |
| Headroom | 0 | 0 | No eligible log candidates |
| LLMLingua-2 | 0 | 0 | No eligible log candidates |

The candidate-screening no-compression run and the four new conditions followed different model paths. In the new runs, only `squeez` processed candidates—5 of them—and changed no strings. Condition-level quality and cost differences are run observations, not evidence of an applied-compression effect.

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T072250Z-ccb06113` | `17524e69e09d62bfef94b14552680365e4199a3c9629a9e85be8e105b165de0c` | `70d45a6842475081138d167dc8959f20ceb6b28cc487927aee3b08be14901f1d` | `528dd5e9f54840c3536fec3ac3e6e4902ff8c29bd5a56e383b591d1f4b114336` |
| squeez | `preliminary-squeez-20260916T072250Z-b8ac7b41` | `883a4b022a5107f3a623da1ca64b87ea000b330f36f3568b26a0740e23e3f9be` | `52ddf2f4cb22a38282ea4a1c132c719d6fdc2f268c4a8fb7a114731af4498781` | `1091beb3883f855fb974e8cefc44d3f355c06360ae70eb56f03940ad16b6dd7e` |
| Headroom | `preliminary-headroom-20260916T072250Z-20a2d3b3` | `f0eba0c6bcc18297424102ed74289a843c1e5f72e486ee569ee3f5d3a4a95685` | `a06b7ccb4b535048eec38f278a7093c9965af52cdb4310ceb807708e5ace12ef` | `494a6d0553467365a989df7ea469f64ff3dc04a40e83f082583dcf43304bd972` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T072625Z-8edf8378` | `9a01e0c8f7897df5d10d12deb45e4a4c852711d7e268fed3058de8ae8467399b` | `dded466d67a08bac2e7f72a230d219d12900f87c1a2e81f4e947d0f99554b36b` | `253e124756e6238ea4a80a4b6688f7ad871b5cbfbfd426a2255619bcc67bd3c0` |

## `kv-store-grpc`

A new no-compression run followed `install-windows-3.11` in fixed task-list order. Its third provider request exposed 1 unprotected eligible log candidate totaling 375 UTF-8 bytes without an additional model call, after which the four conditions ran. All four retained the same `pass` verdict after restored-workspace regrading, and remote-data hashes were verified.

- No-compression candidate-screening run: `screening-diagnostic-20260916T073204Z-246d4b6b`
- No-compression candidate-screening attempt: `5dc13e76fe15c73b0b690f37fc56157ded76378a542d0c0183d340c935449832`
- Comparison ledger: `preliminary-candidate-20260916T073400Z-512f636f`
- Comparison manifest file SHA-256: `c4a9a3b2c3c718bcbf974581c3e16804f21ca075f918e0387070d681c74ea3e4`
- Comparison manifest content SHA-256: `60f80080bb8685410a3038ef597545e9038b1709643446124d1701c3ede87d81`
- Comparison state-file SHA-256: `c0026176bad77b00011fe22e69f2a4e416305e9df154d333bedbedf697822c7a`
- Image digest: `sha256:3399400800dcb207634daa42bc1b052e831e285cc9d221eea66c47bc0fc79791`
- Task-file tree SHA-256: `e5f25663949c47ad08b67acf47053b918b4c34742618bbfd9f56d5374400fd7e`
- Grader source-tree SHA-256: `88cd86365fd28f31619808c2e73ac9440e1f7fae2114e54ac233d0680aac89a7`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | pass | 4 | 4 | 4 | 2 | 0 | 0 | 11,199 / 0 / 1,335 |
| squeez | pass | 4 | 4 | 4 | 0 | 0 | 0 | 14,311 / 6,528 / 1,840 |
| Headroom | pass | 5 | 5 | 5 | 0 | 0 | 0 | 20,979 / 11,136 / 2,410 |
| LLMLingua-2 | pass | 5 | 5 | 5 | 0 | 0 | 0 | 16,910 / 13,440 / 1,726 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc overlap-allocated virtual-machine cost | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.0480225 | $0.008567 | $0.002868 | $0.0000432 | $0.050934 | 76.530 / 91.527 |
| squeez | $0.0486895 | $0.009952 | $0.003560 | $0.0000432 | $0.052293 | 88.901 / 105.071 |
| Headroom | $0.0635415 | $0.010574 | $0.004146 | $0.0000432 | $0.067730 | 94.455 / 109.957 |
| LLMLingua-2 | $0.037925 | $0.008692 | $0.008692 | $0.0000432 | $0.046660 | 77.645 / 176.753 |

The union of actual work intervals is `172.100076s`, with virtual-machine cost of `$0.01926564739666667`; this matches the sum of per-condition post-hoc allocations. No string changed in the four new conditions. Only `none` passed through 2 candidates totaling 576 UTF-8 bytes unchanged; the other conditions had no eligible log candidates. Quality in the four conditions is a valid observation, but not an observation comparing quality after compression was applied.

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T073402Z-2bf10201` | `16b661a4f212056fb5c1e925b427a0fed06d9ea5b6b4c2d789596c58bee61c34` | `7aba4b26672cef46789139545e161aa62d0e7c2309ae8702384b93155d20b727` | `6f89191217171e094f6e7a5092916cbc863b3fd857582a78935cc011d6874051` |
| squeez | `preliminary-squeez-20260916T073402Z-b2d259db` | `a218eb7ad464b6bfdd031591fed2c17b25053e88c39c3d3664550a200d10bd90` | `4ac490b1181d9506ac515faee1a9b21fc6bbe7689a90a581fd6f6e615138ef70` | `10b147ef932d70ebf917a528be5cf791dc1b006b544136a6213605d808f8e5b7` |
| Headroom | `preliminary-headroom-20260916T073402Z-add0f4b0` | `ee6896bdc2f5280efd852e2223b10d5f22feebbb7e6f370d0a27f6cb05fe6407` | `f69f6e49890b4ef87c8e3cff4db66344109fdf561461755b763cedb2ce7eaae3` | `97ab842fd450946938e5adcb1aec3bd8ed4e1e67630ceea0d98dedf5e13486ef` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T073534Z-656c5ef2` | `c4e7c624d8f1f3f3ed329f94ad9a3a83af26ec15c2010e31618b9d696ffcddac` | `38a5e1621ef035ca43be931d7eea437baed932212c18aaae756d36f789ab7cc7` | `29abe58783c4cf8ea831854adcab8fffe2db851e8479cd4cf9c0b3a06bf8d635` |

## `log-summary-date-ranges`

This task was selected while no-compression evidence for earlier tasks in the fixed list was being checked in order. When the comparison was prepared, no-compression evidence for the immediately preceding `llm-inference-batching-scheduler` task was not yet complete, so `log-summary-date-ranges` started first. Neither quality nor expected savings informed selection. The candidate-screening no-compression run had 1 log candidate totaling 5,427 UTF-8 bytes that passed protection rules. All four new conditions retained the same `wrong_answer` verdict after restored-workspace regrading, and remote-data hashes were verified.

- No-compression candidate-screening run: `screening-diagnostic-20260916T075252Z-435d1286`
- No-compression candidate-screening attempt: `29ac88ec1e76aca2324de41bd9a4f8db789d4ad51f973939e9454883363047a0`
- Comparison ledger: `preliminary-candidate-20260916T075935Z-316abafb`
- Comparison manifest file SHA-256: `f7b498720098712ed313446a35666112e84d93bf8d98a95717d0712a3d47cb5a`
- Comparison manifest content SHA-256: `55cd0088ae7376a83e7a3d1e339b22d565b25c2164615a683ad6a97e0540bffd`
- Comparison state-file SHA-256: `3a3aa3b6677c9d4d4f57f4e2e5a8782592874226386dbfcf8c8403bea6caf5cf`
- Image digest: `sha256:cbeb6ba905c2fec294f16cd5e16e3ea7f2e04d38ac2484d51a11de262aa7dc51`
- Task-file tree SHA-256: `629201bfd3dce82cf33c964eec2933b285aa91cfde107e262796413dae2ebad2`
- Grader source-tree SHA-256: `20812107bc3bfc541728a2d10e3da0552e907d949e1347a03d33aa26954f8902`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | wrong_answer | 2 | 2 | 2 | 1 | 0 | 0 | 7,484 / 1,664 / 954 |
| squeez | wrong_answer | 3 | 3 | 3 | 2 | 2 | 0 | 8,376 / 0 / 1,090 |
| Headroom | wrong_answer | 3 | 3 | 3 | 4 | 2 | 0 | 14,203 / 0 / 1,206 |
| LLMLingua-2 | wrong_answer | 3 | 3 | 3 | 2 | 2 | 2 | 9,603 / 0 / 1,033 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc full-overlap allocation | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.029276 | $0.008515 | Unknown | $0.0000432 | Unknown | 76.062 / 91.020 |
| squeez | $0.037290 | $0.008832 | Unknown | $0.0000432 | Unknown | 78.895 / 93.248 |
| Headroom | $0.053598 | $0.008831 | Unknown | $0.0000432 | Unknown | 78.891 / 93.312 |
| LLMLingua-2 | $0.039502 | $0.011678 | Unknown | $0.0000432 | Unknown | 104.320 / 226.021 |

This comparison overlapped in time with another comparison and no-compression screening work. Ledger virtual-machine cost is the original value calculated as though each condition used the entire VM alone. Cost allocated with one formula across every actual overlap interval, and reconciliation against the total billed amount, are not yet complete; the missing values were not replaced with zero or an arbitrary amount.

| Condition | Candidate-input UTF-8 bytes | Adapter-output UTF-8 bytes | Actually changed candidate input → output | Preserved-source token calculation |
|---|---:|---:|---:|---:|
| none | 7,669 | 7,669 | Unchanged | Not applicable |
| squeez | 14,926 | 3,546 | 14,926 → 3,546 bytes, 2 occurrences | 6,654 → 1,652 tokens, 2 occurrences |
| Headroom | 14,010 | 13,832 | 580 → 402 bytes, 2 occurrences | 260 → 188 tokens, 2 occurrences |
| LLMLingua-2 | 15,780 | 8,286 | 15,780 → 8,286 bytes, 2 occurrences | 6,842 → 3,206 tokens, 2 occurrences |

Provider cost differences are observations of full agent runs. Request counts, candidate counts, and cached tokens differed by condition, so the cost difference in this single group is not interpreted as a causal compression saving.

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T075937Z-6dab7d07` | `919a9ce085571ed8ba9415afe9e5afa3e0380be09922f7e76a58723dcc3f4968` | `98acf806f8527131b47d04d4ce6c6f98eb48b9710c3cf9e5095acb4c1d956157` | `272fce8b34ac0769b797a75522b752484198bd9f253cec6fec8c2231966f8b6a` |
| squeez | `preliminary-squeez-20260916T075937Z-9d258d18` | `1faf56036c7a3b92e66d424fbf51a0c51aea1d272a5c661c9fb2849a8f5f1429` | `818968c18a24202176896926c440d73a1015a7b6086614e9633d37da7563c6a9` | `2f1ccad8045bbd7de590782a5e55268f1019b47d9fdda43f65a33e4564f17c17` |
| Headroom | `preliminary-headroom-20260916T075937Z-77f656c9` | `38725ed2d0a8bb34409071dee2c4bcf010adeac23ad84c9585eddd3800de9679` | `2c388ca79d949471d56af5f5ee7a7d12ee57d18b19b954b3809669bcd2b4e1c3` | `f1579cfb48e26131128f6580efaef2548ac86f35699df4948b6d6b4c920d1a4a` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T080109Z-dc7bd6c7` | `61b2d5111336608fc331927e8a3420f22c5b1e8072af384b6be332c071fc009c` | `3944c943c93c81aa2da81d1aeb063e52e2d7d14f8e2a15567f0217ddbaa7d223` | `d37a2b5ade5e58ea4d980ccd6010f0c555aee141d964dcc7792319a4975a490c` |

## `llm-inference-batching-scheduler`

The task was selected after a no-compression run in the fixed task list exposed 1 eligible log candidate totaling 214 UTF-8 bytes. Remote evidence and restored-workspace regrade verdicts were verified for all four conditions. `none` and `squeez` were `pass`; `Headroom` and `LLMLingua-2` were `wrong_answer`. Actual string changes occurred only in the 6 `LLMLingua-2` occurrences.

- No-compression candidate-screening run: `screening-diagnostic-20260916T075251Z-755e4c91`
- No-compression candidate-screening attempt: `1aa19ca7f816691e57542827deefd69b766db629d669c1b26a303eca21580cda`
- Comparison ledger: `preliminary-candidate-20260916T080027Z-0c5d408f`
- Comparison manifest file SHA-256: `01b3beb8748f083dfd95a49a809729ea28b265fbd60241a663a357bdd9835f09`
- Comparison manifest content SHA-256: `4de70fac03d1599b1e4d31b2d36dcea2f3831e5e4ec1c2f4ea55f81ff02a113b`
- Comparison state-file SHA-256: `93da916a291d726de7b470a108dbb5e55991348b8bdd2fbefaae3ff591493481`
- Image digest: `sha256:19e79aa49be4e55dccca1dde966515ebe6852314b6010bcb9230afb48b996774`
- Task-file tree SHA-256: `156a9a027c164ab4f19ee5308fcd3b5707d111aaaa823fde8751fea474cf1f3a`
- Grader source-tree SHA-256: `20812107bc3bfc541728a2d10e3da0552e907d949e1347a03d33aa26954f8902`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | pass | 16 | 16 | Not verified | 30 | 0 | 0 | 269,908 / 86,144 / 8,534 |
| squeez | pass | 8 | 8 | Not verified | 0 | 0 | 0 | 125,300 / 65,792 / 9,017 |
| Headroom | wrong_answer | 7 | 7 | Not verified | 0 | 0 | 0 | 90,980 / 11,008 / 8,895 |
| LLMLingua-2 | wrong_answer | 7 | 7 | Not verified | 6 | 6 | 6 | 107,090 / 14,848 / 5,890 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc full-overlap allocation | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.608956 | $0.03303984617610772 | Unknown | $0.0000432 | Unknown | 295.145045044 / 310.952497959 |
| squeez | $0.300473 | $0.02469120179957814 | Unknown | $0.0000432 | Unknown | 220.566582409 / 249.650419950 |
| Headroom | $0.336107 | $0.022992938084933492 | Unknown | $0.0000432 | Unknown | 205.395989882 / 218.170899153 |
| LLMLingua-2 | $0.322667 | $0.021279669911000464 | Unknown | $0.0000432 | Unknown | 190.091367537 / 417.760246992 |

| Condition | Candidate-input UTF-8 bytes | Adapter-output UTF-8 bytes | Actually changed candidate input → output | Preserved-source token calculation |
|---|---:|---:|---:|---:|
| none | 5,415 | 5,415 | Unchanged | Not applicable |
| squeez | 0 | 0 | Not applicable | Not applicable |
| Headroom | 0 | 0 | Not applicable | Not applicable |
| LLMLingua-2 | 1,110 | 558 | 1,110 → 558 bytes, 6 occurrences | 288 → 138 tokens, 6 occurrences |

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T080030Z-2dc292c3` | `a11eff4f09a3d6c639c725a051897826445a3409705d42dfeff90fb8d635e745` | `951a97a05647098beb95c4d47153bdfdf1ad412eb239c6d2c93f64e7088bd314` | `1bfe7be9e76b71cad5caf64e5752d8633946f1c5c8a6e258de26ac7f8841f540` |
| squeez | `preliminary-squeez-20260916T081117Z-4ae2d980` | `3b879c98e6e66b5e7cf57472a81f3151dd9fb41317d525b825dd9d574fe19b02` | `83ff8d5690a80f495947af62d1cd265c4cad2ce8c19a54a7bfc89fcaf1e1b48b` | `74daa8c576aad835b9fc71fd9523c8257dbc7a74f2f658e899bb9c98f170518d` |
| Headroom | `preliminary-headroom-20260916T080030Z-0b0a9437` | `452c9d9e1baa85cc990529cd743e0e44c082cb9c4f882b96bb48846e6da8b36f` | `3ece09e9af59d49eb7c3b2869aaebfc14d8a59ad1cc6fc36f7c29019e5e7d321` | `e3b79159fc7a50328f63128f9a677ecf8076f0364adea6ff474ebb720a961fd7` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T081117Z-7372522a` | `4853f4d0bbcceb7c5e772fa802b1d7b84fc8c02272bf6ad7e1df3df03d408e28` | `d2eba611569528711cada56e30807f404ea036f366563ae0eb9c8eaba1e02a9a` | `4c5d8ed4536d406231c2057021fbdd4e07122f8ec630c611a535186aea2cea53` |

## `model-extraction-relu-logits`

The task was selected after a no-compression run in the fixed task list exposed 1 eligible log candidate totaling 148 UTF-8 bytes. All four conditions were `wrong_answer`, with matching remote evidence and restored-workspace regrade verdicts. Actual string changes occurred only in the 3 `LLMLingua-2` occurrences.

- No-compression candidate-screening run: `screening-diagnostic-20260916T080440Z-f2ea2445`
- No-compression candidate-screening attempt: `51f1eeb723ba17afa2e4356f8d245cccceb3845867adc0d91a0bd460f1e9ffa8`
- Comparison ledger: `preliminary-candidate-20260916T080756Z-5d4945d1`
- Comparison manifest file SHA-256: `329a113d9e7cc52cb78342f30fc91257ad5070c03c3a7bc96bb2daf74ec3fea9`
- Comparison manifest content SHA-256: `5e1bead23028e87688ccf67040bc23d122cf657c5bdcd64d238ee860135b50a6`
- Comparison state-file SHA-256: `8daf30559d65351663d427d43775be25db9a95582892b22e28b8cc6ec4a28dcf`
- Image digest: `sha256:52fe1f089f38650f0dc22d7531ee6e01ebd526de1b349aaa2ecb331dca9fabce`
- Task-file tree SHA-256: `d3b11c6406509b5f66dbdabc5242a347f5723c3e3bf93f10d42c9bde7ed058e8`
- Grader source-tree SHA-256: `20812107bc3bfc541728a2d10e3da0552e907d949e1347a03d33aa26954f8902`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | wrong_answer | 5 | 5 | Not verified | 4 | 0 | 0 | 22,061 / 0 / 3,049 |
| squeez | wrong_answer | 6 | 6 | Not verified | 10 | 0 | 0 | 31,808 / 0 / 3,240 |
| Headroom | wrong_answer | 3 | 3 | Not verified | 2 | 0 | 0 | 5,900 / 0 / 884 |
| LLMLingua-2 | wrong_answer | 4 | 4 | Not verified | 3 | 3 | 3 | 17,611 / 2,944 / 2,450 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc full-overlap allocation | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.1008875 | $0.02109810800810655 | Unknown | $0.0000432 | Unknown | 188.469486791 / 221.686100960 |
| squeez | $0.128120 | $0.02192722620195813 | Unknown | $0.0000432 | Unknown | 195.875987361 / 225.164462090 |
| Headroom | $0.028010 | $0.01757345733112759 | Unknown | $0.0000432 | Unknown | 156.983758747 / 183.241025925 |
| LLMLingua-2 | $0.0741535 | $0.02476259337147077 | Unknown | $0.0000432 | Unknown | 221.204331425 / 407.509716034 |

| Condition | Candidate-input UTF-8 bytes | Adapter-output UTF-8 bytes | Actually changed candidate input → output | Preserved-source token calculation |
|---|---:|---:|---:|---:|
| none | 592 | 592 | Unchanged | Not applicable |
| squeez | 820 | 820 | Unchanged | Not applicable |
| Headroom | 296 | 296 | Unchanged | Not applicable |
| LLMLingua-2 | 444 | 195 | 444 → 195 bytes, 3 occurrences | 207 → 102 tokens, 3 occurrences |

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T081117Z-b8b09bc1` | `4ad28ac56a3006e2187f9354ccbd8e39d96b41da90159721a3ff59f6d0b837e5` | `997fa58503118e88a1b6c744eabea26578a305fdbeec2716f8f39048f44292ac` | `5689d4e066f65ae90b00b34b3b97dd6b711994b1e19abcf0894403bd3b6a1878` |
| squeez | `preliminary-squeez-20260916T081117Z-5c3123a1` | `f66ffd97a2c6bd693623ea8a9d74572839430da19e49de73056ff737cbf8c76b` | `5d5da5096baec66e5dc3b206cc01547704a63f210883e5721016458240ffc68f` | `6336bb950649e2577cda835c520f1f65b848e541ca65ed2d6f3ef72bd805d8cd` |
| Headroom | `preliminary-headroom-20260916T081117Z-7e8adbd4` | `d22bdd6eee5cb4c3ec8a6296c89245310d3e9229409b1f9bcb2fc34db63c0ef9` | `63fa5e01bf0b53c6191ca3f2655628a0a00e678ba406a1ed9cbeff69c1ab6f2c` | `d399a12490838976353aae7c768731533ff6a2340f010677289ed9b27cdd4b84` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T081812Z-aaef89b3` | `f73a12880f63f777920317f5325662ad1a3e0bba56fc1e897bd1859de0e85c55` | `ce0827cd23da53ca51ffed4ce04a5c106f709b5b64520f160b1e626d740dcb65` | `cd1e4d17ca28caa90f59e9f9dd150ff4261feaa0fcd563a9dc81dbe28b621744` |

## `openssl-selfsigned-cert`

The task was selected after a no-compression run in the fixed task list exposed 1 eligible log candidate totaling 294 UTF-8 bytes. All four conditions were `pass`, with matching remote evidence and restored-workspace regrade verdicts. In the new runs, only `squeez` processed candidates—2 of them—but changed no strings. The other three conditions had no eligible log candidates.

- No-compression candidate-screening run: `screening-diagnostic-20260916T082003Z-fb3a6223`
- No-compression candidate-screening attempt: `8e0c3b5f7ca49bfc4405dbf9f7c592f1056558461e6e89e1d077125110ae9689`
- Comparison ledger: `preliminary-candidate-20260916T082427Z-b1172dfc`
- Comparison manifest file SHA-256: `53226c26cb1bc38bdf7e1d922da101847851e7e4bab758c34744c9fe8bd2d39d`
- Comparison manifest content SHA-256: `8bcc71b48e6124a4853011f4d2121e3686f7332190c5aa8071aacb7493c38be6`
- Comparison state-file SHA-256: `0135b9b2b32b3bdb116bd639f42f04db7d068afceead14e1710bb6cb9e4c2cea`
- Image digest: `sha256:4c948a4e630af2435ae0a19108fc0814a946ac2fa29a512469e0fc77b38c8c12`
- Task-file tree SHA-256: `19963f5579d1dc78c1586dce9c6eaaf8c1f4ef21b9bd7f2f808d8a7d1b9432ca`
- Grader source-tree SHA-256: `20812107bc3bfc541728a2d10e3da0552e907d949e1347a03d33aa26954f8902`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | pass | 2 | 2 | Not verified | 0 | 0 | 0 | 3,777 / 1,664 / 1,008 |
| squeez | pass | 3 | 3 | Not verified | 2 | 0 | 0 | 6,586 / 1,792 / 1,143 |
| Headroom | pass | 2 | 2 | Not verified | 0 | 0 | 0 | 3,806 / 0 / 1,011 |
| LLMLingua-2 | pass | 2 | 2 | Not verified | 0 | 0 | 0 | 3,850 / 0 / 1,042 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc full-overlap allocation | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.0208185 | $0.026224037148952484 | Unknown | $0.0000432 | Unknown | 234.259407696 / 249.810486794 |
| squeez | $0.029578 | $0.026292314307292303 | Unknown | $0.0000432 | Unknown | 234.869328558 / 251.427695990 |
| Headroom | $0.024680 | $0.026273352709213892 | Unknown | $0.0000432 | Unknown | 234.699947035 / 251.033024788 |
| LLMLingua-2 | $0.025255 | $0.008444560600651635 | Unknown | $0.0000432 | Unknown | 75.435300356 / 252.568834066 |

| Condition | Candidate-input UTF-8 bytes | Adapter-output UTF-8 bytes | Actually changed candidate input → output | Preserved-source token calculation |
|---|---:|---:|---:|---:|
| none | 0 | 0 | Not applicable | Not applicable |
| squeez | 588 | 588 | Unchanged | 2 identical strings |
| Headroom | 0 | 0 | Not applicable | Not applicable |
| LLMLingua-2 | 0 | 0 | Not applicable | Not applicable |

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T082441Z-145c84a1` | `b8d2913a3bd54242d0c3b49fa268139b7beb72111fcfe7739c6e986619a5d51b` | `3154b8997b6e1f1b636b1da8c27ed174c516aab7b94d84e0e6af96d82c72dec7` | `c7c43ca303fdc6f6c32523aede73cca810bfb335df7408cfefc95cc07fcc14e1` |
| squeez | `preliminary-squeez-20260916T082441Z-647d96b2` | `18879dc844a91d8122651ca35e0fb490b125dfd5fd06c57a80126941bcf426c1` | `0cd93ad62289fd56118726ea71b9c3151d345cf80892f14026461479f7b3f0f4` | `6b0939b9737bd3b7c1d6d9f8e9593652fcdf8fa8b9bed09edd8ac81e1db281aa` |
| Headroom | `preliminary-headroom-20260916T082441Z-9c21adff` | `b9ff62beb88dcb4d6b0cf9c5b5ddc63ed3906fb56262e118731950db46fe7d34` | `d90f678412085cd6588683c4c0098e00a582323ba561ae375a58ff0a115d00db` | `aa3787d1b65036000382a122dfa08331bd3e04be2a5d36e3416e541e349589d4` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T082851Z-de9dc1bf` | `64d77240215b2f8ba4951fd9a4361707498ca59652f5f2a3fee11fa08fa854eb` | `0348a17443d2d77413ef5e8cbae4154c6c5db4dc6035ce131dc154561e68b99a` | `b34e6278c974d06b46af4f832edce5352bef23aa4cd9e7d8f7fbba68c6f115e3` |

## `overfull-hbox`

The task was selected after a no-compression run in the fixed task list exposed 2 eligible log candidates totaling 289 UTF-8 bytes. `none`, `squeez`, and `Headroom` were `wrong_answer`; `LLMLingua-2` was `pass`. Remote evidence and restored-workspace regrade verdicts were verified for all four conditions. Actual string changes occurred only in the 10 `LLMLingua-2` occurrences.

- No-compression candidate-screening run: `screening-diagnostic-20260916T082230Z-b00f70b0`
- No-compression candidate-screening attempt: `4c61ce676ba0a5bd2d1eaf3ca14d8a126a29855382dc86e2385e3e0046920334`
- Comparison ledger: `preliminary-candidate-20260916T083131Z-95605fdb`
- Comparison manifest file SHA-256: `bf35f947efa514067d1a736fa713041584aaa77356a3b1a352e91a267a93e1b4`
- Comparison manifest content SHA-256: `65b024dc43d00aec4acc37c774f86994a96ac8e998c57621f8937b544df3a5ea`
- Comparison state-file SHA-256: `abee632105cac2ec33dd8a6870039eabb100166c17e90b52ad984ce4efa12764`
- Image digest: `sha256:7dca952bb6736194a736b5110945f48842eafa8551e24468f1dddeed0daee799`
- Task-file tree SHA-256: `745cfd8cb8a9da6dcb446e42c4aa8485b99713250f51312e8d111f26497a8a07`
- Grader source-tree SHA-256: `20812107bc3bfc541728a2d10e3da0552e907d949e1347a03d33aa26954f8902`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | wrong_answer | 10 | 10 | Not verified | 18 | 0 | 0 | 91,483 / 37,248 / 3,930 |
| squeez | wrong_answer | 7 | 7 | Not verified | 12 | 0 | 0 | 46,603 / 13,824 / 2,772 |
| Headroom | wrong_answer | 10 | 10 | Not verified | 9 | 0 | 0 | 99,624 / 22,016 / 4,268 |
| LLMLingua-2 | pass | 6 | 6 | Not verified | 10 | 10 | 10 | 37,959 / 12,672 / 2,558 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc full-overlap allocation | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.2038495 | $0.03236814796229204 | Unknown | $0.0000432 | Unknown | 289.144764809 / 314.392944098 |
| squeez | $0.1269835 | $0.026706963681909775 | Unknown | $0.0000432 | Unknown | 238.573392062 / 254.438044071 |
| Headroom | $0.263544 | $0.0361150572451618 | Unknown | $0.0000432 | Unknown | 322.615917010 / 348.533388853 |
| LLMLingua-2 | $0.1047555 | $0.028732526318629582 | Unknown | $0.0000432 | Unknown | 256.667747529 / 441.609700918 |

| Condition | Candidate-input UTF-8 bytes | Adapter-output UTF-8 bytes | Actually changed candidate input → output | Preserved-source token calculation |
|---|---:|---:|---:|---:|
| none | 2,601 | 2,601 | Unchanged | Not applicable |
| squeez | 1,734 | 1,734 | Unchanged | Not applicable |
| Headroom | 2,259 | 2,259 | Unchanged | Not applicable |
| LLMLingua-2 | 1,445 | 675 | 1,445 → 675 bytes, 10 occurrences | 660 → 340 tokens, 10 occurrences |

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T083152Z-5c30cd30` | `7778da6f1a5be740fac3d2d8801a34721d3854905f9d5a5c3d82d3107dfd785a` | `d4cf6618d2402a052499e1d21f33e9ff531214d3948d3ce60e648d26cbd3aa94` | `9fbbf6629dc2d63a1828384dcefa4e0ea97d06285a39c71e0c4af9049b639970` |
| squeez | `preliminary-squeez-20260916T083152Z-92d614c9` | `4aa1aea350d72c302c0dc2cf7ddb22806ac5bb1b33f3b915d04fa99ec2799129` | `994fc2a23aa3a22be68fe66c03298b8441ea9e9b3c7551499a2fe9796fc0c90c` | `48acc7df00cf150e95692c70a09ceebd0748939390afef3ae6ca002125f205c2` |
| Headroom | `preliminary-headroom-20260916T083152Z-07971a2d` | `87224dc26c4728001066f4713988f4716893e2880bf678a89bd65e740b631ff6` | `b34395aaffe2a902de5507cb67809f425808c4b98dabe6dde418abaa1eede8a7` | `505633ef6e59d598906143c63665b0d151b8b1328ef3bad19f3e1d3d5d94a77e` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T083607Z-885c6d96` | `c95ea035df9290a4732aa3a03b1af382ec2c0c39ebeabd47d4ee02d07881deb1` | `c328d7c30b91ad8b5f5ab11e52efc3e2064e16f01ebce6bb72bacf0174960922` | `c47a9bc5ec55e2f29810c6107a40810879643e279c63caceefe63fcb06583493` |

## `prove-plus-comm`

The task was selected after a no-compression run in the fixed task list exposed 1 eligible log candidate totaling 149 UTF-8 bytes. All four conditions were `pass`, with matching remote evidence and restored-workspace regrade verdicts. Actual string changes occurred only in the 7 `LLMLingua-2` occurrences.

- No-compression candidate-screening run: `screening-diagnostic-20260916T084456Z-127e47e6`
- No-compression candidate-screening attempt: `e42ec683144a8ba0aedae1c5cde44194472e8e0322c5e6070bc606f808bda8d1`
- Comparison ledger: `preliminary-candidate-20260916T084720Z-18a47b36`
- Comparison manifest file SHA-256: `0f6f95630b8c64785b194e394303be8a5ef4e598733ea5c7436ed341e2d563b9`
- Comparison manifest content SHA-256: `1a3e7e1fdb362aedfb4117eeac07cf54a3f310f775314a2621f0f4a17df0fd10`
- Comparison state-file SHA-256: `6584b2298d3929cdfb4f5f94c7f0900f58e9d76d9796e4cb2e400b12e21c8ac8`
- Image digest: `sha256:e26741d01681a9da1beeff8b7b7b65fe2b921b8b122a306a3707a81ebd051f73`
- Task-file tree SHA-256: `152a5e217300d36df2846c5789c586f1bde76e70677679617a59cea5320d348b`
- Grader source-tree SHA-256: `20812107bc3bfc541728a2d10e3da0552e907d949e1347a03d33aa26954f8902`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | pass | 4 | 4 | 4 | 5 | 0 | 0 | 6,036 / 0 / 782 |
| squeez | pass | 4 | 4 | 4 | 2 | 0 | 0 | 6,474 / 2,048 / 870 |
| Headroom | pass | 4 | 4 | 4 | 5 | 0 | 0 | 6,693 / 1,536 / 838 |
| LLMLingua-2 | pass | 6 | 6 | 6 | 7 | 7 | 7 | 12,298 / 3,968 / 1,418 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc full-overlap allocation | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.026820 | $0.010032553017404345 | Unknown | $0.0000432 | Unknown | 89.620843421 / 102.972784 |
| squeez | $0.024627 | $0.009977054536210166 | Unknown | $0.0000432 | Unknown | 89.125068452 / 101.910930 |
| Headroom | $0.0258465 | $0.010015166027744611 | Unknown | $0.0000432 | Unknown | 89.465524609 / 103.404822 |
| LLMLingua-2 | $0.043087 | $0.018305286519461207 | Unknown | $0.0000432 | Unknown | 163.521187637 / 332.944192 |

| Condition | Candidate-input UTF-8 bytes | Adapter-output UTF-8 bytes | Actually changed candidate input → output | Preserved-source token calculation |
|---|---:|---:|---:|---:|
| none | 1,003 | 1,003 | Unchanged, 5 occurrences | 5 identical strings |
| squeez | 666 | 666 | Unchanged, 2 occurrences | 2 identical strings |
| Headroom | 1,003 | 1,003 | Unchanged, 5 occurrences | 5 identical strings |
| LLMLingua-2 | 963 | 408 | 963 → 408 bytes, 7 occurrences | 446 → 210 tokens, 7 occurrences |

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T084855Z-1517839d` | `44543d95c24c64ce311c23502c3342f029cb229f0ac1353c95c1db63e79d2315` | `8a7d160f8d7b7d1d18acadfe10daf3734affdb032f9b96ba37704e8ce4c12030` | `4bee76dab94edc2a91abb7357f6b8a2b33e3086a3832e34460500046ae025ce0` |
| squeez | `preliminary-squeez-20260916T084855Z-011fb1af` | `548f383fdc613af6831aa18ccfd012bb72c129298bb6d866f484338e4db0a204` | `9cce593acaf37cd2b06aee0925bf2a341bd3bee0f8dc9e5f277cef2704ab52c2` | `88272dd3dfad6cdd468d349fed16dcb36e4e6e29e3e70afa8634114913ffd50c` |
| Headroom | `preliminary-headroom-20260916T084855Z-4658e4d8` | `b4f57bf3b8b6d0e9e5865561df5fd62519ab894abce611234c444a6af2e79617` | `53cc141363870ca29a72418d377d166304a83aeb05f2f341e2e3cb20698c257e` | `dfbc44c523850507c5a85c91715473421ac35e5ffae5e2d864d80014bfe5d41a` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T085037Z-07a7b0b8` | `925d9d7d2b23e6c7b56389d1173eaa35acde2a12c737179e8a70f228f46b31b2` | `e57b80916fcea1094d0a651356e02182922e30e7af4922a0a022d18f2a1b3c1e` | `d6fc8729c4abb25f694ea58eff52283400a08b6b8dc9666a8c595e94e30b89d2` |

## `raman-fitting`

The task was selected after a no-compression run in the fixed task list exposed 2 eligible log candidates totaling 171 UTF-8 bytes. All four conditions were `wrong_answer`, with matching remote evidence and restored-workspace regrade verdicts. Actual string changes occurred only in the 10 `LLMLingua-2` occurrences.

- No-compression candidate-screening run: `screening-diagnostic-20260916T091018Z-069de78b`
- No-compression candidate-screening attempt: `9552232f8866cc6e965e85fe6d8131ca047b98fe1558ba24ba3d1e1bf9ced15d`
- Comparison ledger: `preliminary-candidate-20260916T091335Z-eb9bdcbc`
- Comparison manifest file SHA-256: `c57e2c5d01b175d82b84d845f61103f3a29c53ed50f43b193afe574262f352af`
- Comparison manifest content SHA-256: `76dc284debf0a9cbd18086ee5f4949c4b1e50522e5848b40a83b48c475489a5b`
- Comparison state-file SHA-256: `dbeb43d4f9ed4db84bf34eed8dbc1ffcba4c6b8616429fc464b04c4729fb838d`
- Image digest: `sha256:401fa95d5d491f44a473eda9d2c52930f9565cc889c796eabcb6e20fec26852e`
- Task-file tree SHA-256: `6bdec0431b60319aaa6cb5b61418eddaff8f95581d79077cb3cac09b5076b689`
- Grader source-tree SHA-256: `b166a4838a58891acf1a27cbb58e49910bbd8829210205c21dd3b5aa9dbdd097`

The first launcher ended with a shell error while reading an empty array before any condition started. There were 0 model calls and 0 condition starts; the original log and contemporaneous manifest are preserved separately. The corrected launcher assigned conditions to free slots among 8 shared execution slots in a predetermined order. Results for the four conditions come only from that completed run.

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | wrong_answer | 8 | 8 | 8 | 14 | 0 | 0 | 57,186 / 42,112 / 5,310 |
| squeez | wrong_answer | 6 | 6 | 6 | 0 | 0 | 0 | 42,686 / 2,560 / 5,394 |
| Headroom | wrong_answer | 17 | 17 | 17 | 32 | 0 | 0 | 140,806 / 100,736 / 5,901 |
| LLMLingua-2 | wrong_answer | 6 | 6 | 6 | 10 | 10 | 10 | 33,069 / 25,216 / 4,641 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc full-overlap allocation | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.127863 | $0.024492933973140188 | Unknown | $0.0000432 | Unknown | 218.795459643 / 235.601365089 |
| squeez | $0.181865 | $0.013923516004151768 | Unknown | $0.0000432 | Unknown | 124.378828617 / 137.392342091 |
| Headroom | $0.213874 | $0.021223433381319046 | Unknown | $0.0000432 | Unknown | 189.589004418 / 203.063102007 |
| LLMLingua-2 | $0.0955515 | $0.024939323756429883 | Unknown | $0.0000432 | Unknown | 222.783060002 / 408.335880995 |

| Condition | Candidate-input UTF-8 bytes | Adapter-output UTF-8 bytes | Actually changed candidate input → output | Preserved-source token calculation |
|---|---:|---:|---:|---:|
| none | 1,197 | 1,197 | Unchanged, 14 occurrences | 14 identical strings |
| squeez | 0 | 0 | Not applicable | Not applicable |
| Headroom | 2,736 | 2,736 | Unchanged, 32 occurrences | 32 identical strings |
| LLMLingua-2 | 855 | 395 | 855 → 395 bytes, 10 occurrences | 385 → 195 tokens, 10 occurrences |

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T092543Z-7a52f8c8` | `3d39f0ae901d3a8d5515d1f8b3ee5b8199f487fa98bf87039cbf517180110eb7` | `6c812662c095162c6706bce0d5c532165884ab634644cdf40a61787c2b9a6d1c` | `3aa59370606bab7dc3cf2220dd11a7941fed2043e3c4eec85e89bbe635a5d712` |
| squeez | `preliminary-squeez-20260916T092324Z-16dcd28d` | `2f7fbd80a22058b016dd99905e58d83c48d7c92ce84ef8fe1dee26833bc96376` | `081a9bca773c4e1e08d5a120d76e5d37cc831c212fd97633acdeced5f24ca6d4` | `b24b1260e0df5d9137b58dcd236477fe93a21eace1bcbd6af5e14091d6760a78` |
| Headroom | `preliminary-headroom-20260916T092324Z-bd8d3b9e` | `c4a7f298d9315d6a2e810dc41618f946f2c905d4f07838b0b5ff2d3ea88bd1eb` | `7a843d88b928a9a55ecc116b8715b62fff0ad85f0a49d8e640144d56fdf71d50` | `474af666ba3259046df918e02fb6134f4f06bd6485f021235d3050200ed413d1` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T092647Z-ac85d88e` | `ef0ce9032296ac2e4c186c3ad52d7207fe7fecadebe8d2c398a85683a6e573c6` | `c4799411a92dfaf13972df076d15e1c7b51668c6837a736ffb8fe89c8e7cbab5` | `f3aa636ba3ab8eef614a4d1f1017cda7d9619817d5ea4069804ef585a61b8d7b` |

## `sqlite-with-gcov`

The task was selected after a no-compression run in the fixed task list exposed 1 eligible log candidate totaling 426 UTF-8 bytes. `none`, `squeez`, and `LLMLingua-2` passed; `Headroom` was a wrong answer. Actual string changes occurred only in the 4 `LLMLingua-2` occurrences. Model paths differed between the screening run and the four conditions, so `none`, `squeez`, and `Headroom` also processed 0 eligible log candidates.

- No-compression candidate-screening run: `screening-diagnostic-20260916T094505Z-186bab7f`
- No-compression candidate-screening attempt: `34d589f2e8999ce54deb8526a960968fa4897ca81f1ce6a0c5e9a98cfe137ca3`
- Comparison ledger: `preliminary-candidate-20260916T101833Z-d3e3da8c`
- Comparison manifest file SHA-256: `c27b9ee9530026678f25a7280ee71b88b454fd365b6844f5bec38cff30509c03`
- Comparison manifest content SHA-256: `d89c14ad1cc8786508f66395a0805020eee4e8dd965aae177a9339e103da784c`
- Comparison state-file SHA-256: `3b6c9a29b498e9619778348814b9df89055d8136d6395402dd9b5bbac1c17871`
- Image digest: `sha256:f986820b00c74ce75db7288719d364df313fde7c7917bea6eb6352a08431a89f`
- Task-file tree SHA-256: `2a688d0ee92a02f257d7774545e5f5223fae99362f4b262cf5fe57d33e6a2839`
- Grader source-tree SHA-256: `96915147263b1bcf22b8a7bf60bba700647bdbbdf467363498f8d76a20a5f0d5`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | pass | 11 | 11 | 11 | 0 | 0 | 0 | 134,414 / 65,920 / 2,759 |
| squeez | pass | 7 | 7 | 7 | 0 | 0 | 0 | 57,858 / 29,824 / 2,288 |
| Headroom | wrong_answer | 9 | 9 | 9 | 0 | 0 | 0 | 120,874 / 69,248 / 3,383 |
| LLMLingua-2 | pass | 6 | 6 | 6 | 4 | 4 | 4 | 39,810 / 9,856 / 1,784 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc full-overlap allocation | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.2291 | $0.048823310958743094 | Unknown | $0.0000432 | Unknown | 436.13878270499936 / 475.088877 |
| squeez | $0.111861 | $0.02197245565911134 | Unknown | $0.0000432 | Unknown | 196.28002428800028 / 226.777519 |
| Headroom | $0.19712200000000002 | $0.04450221545947923 | Unknown | $0.0000432 | Unknown | 397.5384287629995 / 436.123563 |
| LLMLingua-2 | $0.104109 | $0.02735732801609569 | Unknown | $0.0000432 | Unknown | 244.3831008369998 / 437.019729 |

| Condition | Candidate-input UTF-8 bytes | Adapter-output UTF-8 bytes | Actually changed candidate input → output | Preserved-source token calculation |
|---|---:|---:|---:|---:|
| none | 0 | 0 | Not applicable | Not applicable |
| squeez | 0 | 0 | Not applicable | Not applicable |
| Headroom | 0 | 0 | Not applicable | Not applicable |
| LLMLingua-2 | 1,112 | 572 | 1,112 → 572 bytes, 4 occurrences | 284 → 140 tokens, 4 occurrences |

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T101836Z-3c16ae68` | `b5a9cd5556f60c094ce58937c5ffb3cdd95f98bf943cc7d31ad405b8b5605add` | `5e9252225a8e5ae483784bbefb95d256a9b9945967dc624c537b39e54c9edab3` | `4479f5178a7d9eb19aea036da83ee9e98d11245b8a8e939bfe624b961407f5f6` |
| squeez | `preliminary-squeez-20260916T101837Z-f2157f79` | `67297b2b7eb48f0e64fe73e3f1bd5b55b50931eb15d65a741f6387541bea592e` | `51ed664a357e4275978b18d0a7ad925b820eb52f23a212ea6e058322a9ed6e34` | `2ebde3811d669e180b7b45e6be424fe072c22f4d461a449d3c1c5bc7fe95ecf4` |
| Headroom | `preliminary-headroom-20260916T101836Z-66430e95` | `387cffb47b88a3aae1ed24582e4c8fd9a23fa7141305bcf0e78e0c0beb81375c` | `adec04ebd807fab0ee3e74ec4002a2c20569daf6ef7f0967f0e6f959fb23b8ae` | `511c22f7bf601d307f0878f74a7719e09d0dd149f879328ac683b71bd1b37632` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T102224Z-e16b4f3c` | `73d068a96efb33cd7a618f00755b2ad11dc8e41f886970988740045e91c4cf5f` | `a676407e2c40cd54144c2b3dbbab5878d96aa7acc96d0ff3f57776b4997c8efc` | `027de9112de7590ec93ebfd9527f2ddb4ce7c78b87870190366faf09d7772a13` |

## `vulnerable-secret`

The task was selected after a no-compression run in the fixed task list exposed 1 eligible log candidate totaling 151 UTF-8 bytes. All four conditions passed, and actual string changes occurred only in the 4 `LLMLingua-2` occurrences.

- No-compression candidate-screening run: `screening-diagnostic-20260916T110330Z-e4ef8521`
- No-compression candidate-screening attempt: `708330028aa98f18af2ca399c8339baee9608d39fd7f0e61fcdd15e86a11c9d2`
- Comparison ledger: `preliminary-candidate-20260916T111044Z-62b31a51`
- Comparison manifest file SHA-256: `c5e4de67a4870a95e0041aa17ccbbc979d995c6092c44f977d8d903ea6edacdb`
- Comparison manifest content SHA-256: `be5fe288c5e2fe2bc3a2dcb18d26bfb637cb04102e8dbb0616d235848ad71738`
- Comparison state-file SHA-256: `1a4973f805809203e1a227bcfffb7fc048bf945beb162a8c5a8637ebd303adb9`
- Image digest: `sha256:61ebb40454dd103aa2f7e71ad6dafd91cf2b301e6bb07e69d5b472412d1ee15b`
- Task-file tree SHA-256: `67969351354e16d01c31a31412d0ea7cc1684d567c965dd191bc2b8a1b73632b`
- Grader source-tree SHA-256: `21609ea7b7fd7877a8e47edbd4a52d92af8ac4bf09c8e2b5f8762172cf17e4af`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | pass | 5 | 5 | 5 | 4 | 0 | 0 | 22,778 / 10,496 / 2,112 |
| squeez | pass | 7 | 7 | 7 | 6 | 0 | 0 | 54,726 / 11,008 / 2,474 |
| Headroom | pass | 5 | 5 | 5 | 4 | 0 | 0 | 22,656 / 7,296 / 2,207 |
| LLMLingua-2 | pass | 5 | 5 | 5 | 4 | 4 | 4 | 30,393 / 20,480 / 2,147 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc full-overlap allocation | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.065009 | $0.014938968207703697 | Unknown | $0.0000432 | Unknown | 133.44985807100056 / 144.877738 |
| squeez | $0.149157 | $0.011259677276213964 | Unknown | $0.0000432 | Unknown | 100.58274033400085 / 112.651740 |
| Headroom | $0.073329 | $0.0092303606888983 | Unknown | $0.0000432 | Unknown | 82.4548526159997 / 93.368442 |
| LLMLingua-2 | $0.062107499999999996 | $0.015744577049745453 | Unknown | $0.0000432 | Unknown | 140.6463607200003 / 285.649953 |

| Condition | Candidate-input UTF-8 bytes | Adapter-output UTF-8 bytes | Actually changed candidate input → output | Preserved-source token calculation |
|---|---:|---:|---:|---:|
| none | 604 | 604 | Unchanged, 4 occurrences | 4 identical strings |
| squeez | 906 | 906 | Unchanged, 6 occurrences | 6 identical strings |
| Headroom | 604 | 604 | Unchanged, 4 occurrences | 4 identical strings |
| LLMLingua-2 | 604 | 248 | 604 → 248 bytes, 4 occurrences | 280 → 128 tokens, 4 occurrences |

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T111047Z-0c17cd54` | `e5c1d98b812b87d3f8ca071fb947b37473b756f9780585ce0c877540bd70f18b` | `faeda23c42e1cfd60a833e89d868c50aa22eb314ace21220e682dc0de7538c9b` | `def23dc3f9b48915d645193ac1a0f413878ea0c7feed271223c7beb40c193ea5` |
| squeez | `preliminary-squeez-20260916T111047Z-27c6bc61` | `1f8f4c5fcdbf140bb11812537a4dcb54338c5ccfde460eb489fe71e4083e1a52` | `94704aacef8bfe51e2a5b2c7b27f6036fd4afe1ff0e53acd91142d1fdee199e2` | `d2165baff657042c56c9b93f40b5acd74bdbee9d3328a06d1f14c8ff5bf8e641` |
| Headroom | `preliminary-headroom-20260916T111242Z-d74fd7a5` | `b8adc0ee7c4ca011ee2391b8778158fc3ed574d697652cb13eb46e575c6dea8a` | `2aeabd0440455f515d3a7a0ec77fc062d1c5d6810ea42b42312c2d555d8ef53a` | `16c84a86f32a1aff0dd7ce23e1964fc2033a03454f0a4e49742c6de7e6fc43da` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T120437Z-ccb720be` | `b502419058b8a7fc4115cd4c706ce0a66e2465401de3da2fbec7e1412b5d2e37` | `3532f7d3140da275c44778f13b0a9da1e3baa1fb8b6877c462ba19f6b8b64728` | `28d6d5351e48072610ca11a7e5102ef6c971e0d027dd0a84932f523be95e7e80` |

## `video-processing`

The task was selected after a no-compression run in the fixed task list exposed 1 eligible log candidate totaling 162 UTF-8 bytes. All four conditions were wrong answers. Actual string changes occurred only in the 6 `LLMLingua-2` occurrences completed in a separate continuation run.

The initially run `none`, `squeez`, and `Headroom` results were linked with the `LLMLingua-2` result from a separate continuation run as the four conditions for one task. The first `LLMLingua-2` attempt ended with HTTP 500 before grading, so it is excluded from quality and token tables; its cost remains separate as technically incomplete cost. Both runs used the same source revision, model, image, task files, and grader.

- No-compression candidate-screening run: `screening-diagnostic-20260916T104820Z-4de9cefd`
- No-compression candidate-screening attempt: `49478240d2e276d76efdbe004d2351da52919e53e4b4c39c283d6342f4fbfb8b`
- Initial comparison ledger: `preliminary-candidate-20260916T105548Z-6709106d`
- `LLMLingua-2` continuation-run ledger: `preliminary-candidate-retry-20260916T121415Z-f958125c`
- Initial comparison manifest file SHA-256: `ce7cabe008a4a3ec8f1910073a99ba102efff2edb9e5051a98d3065cee4240cd`
- Initial comparison manifest content SHA-256: `46296f84262bc631c8dd792e864c1cbb85cfdf9240ba0a87a5cebf8f50f5f192`
- Initial comparison state-file SHA-256: `5a9bd5107470e7f4c045f3338e7a988dcbb996142066cfb0750de1a0f9cee381`
- Continuation-run manifest file SHA-256: `4d6e8f08b24050c251b9d3c0b2f30ab9ae52f77d966b5518ec9726b9919cbabb`
- Continuation-run manifest content SHA-256: `9845ce52e68747c3f2f4f3e6040bf91e2fad37e9090ad9c0d53f944f9e783678`
- Continuation-run state-file SHA-256: `b77bcb963b03d38dea7114780bb99fe1327e74aa32b36fa25c7bbdfe3e7f6b17`
- Image digest: `sha256:a2c0f39e3ab04e67ac6e49cad9167bb0d987babe32511768c01aa0c6905a875f`
- Task-file tree SHA-256: `547d0329d8936eedb4339ec23b3f5194d208703e70eec67804ecf6cfc314f117`
- Effective grader SHA-256: `20812107bc3bfc541728a2d10e3da0552e907d949e1347a03d33aa26954f8902`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | wrong_answer | 8 | 8 | 8 | 7 | 0 | 0 | 89,043 / 66,048 / 5,072 |
| squeez | wrong_answer | 8 | 8 | 8 | 7 | 0 | 0 | 116,954 / 37,248 / 10,708 |
| Headroom | wrong_answer | 6 | 6 | 6 | 5 | 0 | 0 | 64,341 / 1,536 / 7,086 |
| LLMLingua-2 | wrong_answer | 7 | 7 | 7 | 6 | 6 | 6 | 55,444 / 16,512 / 4,742 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc full-overlap allocation | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.1500795 | $0.029925163298183018 | Unknown | $0.0000432 | Unknown | 267.32157338400066 / 278.472242 |
| squeez | $0.369197 | $0.03677584393534396 | Unknown | $0.0000432 | Unknown | 328.5187219489999 / 340.057968 |
| Headroom | $0.2636865 | $0.01978575103925334 | Unknown | $0.0000432 | Unknown | 176.74618143099906 / 187.8667 |
| LLMLingua-2 | $0.172588 | $0.022056547867655756 | Unknown | $0.0000432 | Unknown | 197.03121458699934 / 338.565179 |

| Condition | Candidate-input UTF-8 bytes | Adapter-output UTF-8 bytes | Actually changed candidate input → output | Preserved-source token calculation |
|---|---:|---:|---:|---:|
| none | 1,134 | 1,134 | Unchanged, 7 occurrences | 7 identical strings |
| squeez | 1,134 | 1,134 | Unchanged, 7 occurrences | 7 identical strings |
| Headroom | 810 | 810 | Unchanged, 5 occurrences | 5 identical strings |
| LLMLingua-2 | 972 | 372 | 972 → 372 bytes, 6 occurrences | 438 → 192 tokens, 6 occurrences |

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T105601Z-e9577f5c` | `4720fef0c67120aee643e0349d367dc0c5f3db905e957a547367b7eeaec0fd8d` | `43fff186d0ebcb417919b8a93a53ace6e0368fe4b756be1683d2dcb71506c3ec` | `c724ea979982714ed5a249535c6ea02b15bb4d9bfdef5308b794b22c44df241e` |
| squeez | `preliminary-squeez-20260916T110040Z-6aefac8b` | `430bcbf7e3522f926d2539df1b85a7d9574ebba936df58f2c46ddd4ec8dcbce3` | `83421b184f1094b9c509b5cd982c74095249859cb0e499f20b204b3958e2caee` | `d640d892f673968a5a53972462fa8e5537b1d3f29a125f3107f1486545e56395` |
| Headroom | `preliminary-headroom-20260916T105939Z-1f473a05` | `5197242981dbd8fcfd111afd3ca21576cf961d9d6d2d65fca6b365c72ce9976f` | `a39003b2675e523cb451bad4f604914120b51564706bcca4547deb87d56005c7` | `2e3e3d2716f275362b1305e4c678efa302536c310e8751deb4bf8b3ef33cfdc8` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T122003Z-08e11a1c` | `2ef428d51b74022b171fd59b93f67e067e4f30b468232cafde63b49c9dcaa8b3` | `f33923cb04f9ca761695d1a41e6d7ba4eeb2401547374be8fdfa5b0f24848a0a` | `4bdc902241f82d541c45aed2b8ca1cfe96c9dfa4423dde2fc61d194ad29c4abf` |

## `chess-best-move`

The task was selected after a no-compression run in the fixed task list exposed 1 eligible log candidate totaling 156 UTF-8 bytes. All four conditions were wrong answers, with matching remote evidence and restored-workspace regrade verdicts. Actual string changes occurred only in the 14 `LLMLingua-2` occurrences.

The first `Headroom` attempt received 335 HTTP responses before the virtual-machine interruption but never reached grading. Its verified calculated API cost of `$7.809586` and unknown amount of `$0.1204225` for the final request without a response remain with the separate interrupted attempt. Quality, tokens, and completed cost below use only the `Headroom` attempt completed in a new workspace after the interruption.

- No-compression candidate-screening run: `screening-diagnostic-20260916T122130Z-13352ad3`
- No-compression candidate-screening attempt: `4de8e5e42e4f20e5c681e91d9bf6bf71df10070633fdaa22049fcdb0223d240e`
- Comparison ledger: `preliminary-candidate-20260916T124117Z-305c1855`
- Comparison manifest file SHA-256: `a2f2034a7bab7102134335def106225059c6e3dd2a156585fbc1f877ff63a66a`
- Comparison manifest content SHA-256: `aff3df5610c3445346f9d36d1a0ddeb091b13eb1be55783e532dc37a830ecc3e`
- State-file SHA-256 at interruption: `efd187b3f7dbbff3cae0dd8711cc3ed990d14208b6af14a3559d60f8c986bc03`
- Completed-condition linkage record SHA-256: `d6d647bf6295b16613aa6e566d31c4a853c0f4623335ced65b50c9720c5a4015`
- Image digest: `sha256:bb447f94d9e2a8ed879f85c85a514b213b7418f9fe11fd7b2428a0b0e436e647`
- Task-file tree SHA-256: `9df1744ccb33c983009b9481e113d7a4b13bc5ca09ddf30621edc3783ec5d210`
- Effective grader SHA-256: `20812107bc3bfc541728a2d10e3da0552e907d949e1347a03d33aa26954f8902`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | wrong_answer | 10 | 10 | 10 | 9 | 0 | 0 | 81,844 / 70,912 / 4,473 |
| squeez | wrong_answer | 7 | 7 | 7 | 6 | 0 | 0 | 60,227 / 37,632 / 5,390 |
| Headroom | wrong_answer | 6 | 6 | 6 | 5 | 0 | 0 | 35,629 / 9,344 / 3,396 |
| LLMLingua-2 | wrong_answer | 15 | 15 | 15 | 14 | 14 | 14 | 177,390 / 150,144 / 8,407 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc full-overlap allocation | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.112153 | $0.030907510718901954 | Unknown | $0.0000432 | Unknown | 276.096890930 / 284.944088 |
| squeez | $0.1467455 | $0.03141072978198528 | Unknown | $0.0000432 | Unknown | 280.592143996 / 289.074368 |
| Headroom | $0.1189885 | $0.016585155906478563 | Unknown | $0.0000432 | Unknown | 148.155260834 / 171.056500 |
| LLMLingua-2 | $0.231756 | $0.04919165643155575 | Unknown | $0.0000432 | Unknown | 439.429206252 / 577.394706 |

| Condition | Candidate-input UTF-8 bytes | Adapter-output UTF-8 bytes | Actually changed candidate input → output | Preserved-source token calculation |
|---|---:|---:|---:|---:|
| none | 1,404 | 1,404 | Unchanged, 9 occurrences | 648 → 648 tokens, 9 occurrences |
| squeez | 936 | 936 | Unchanged, 6 occurrences | 432 → 432 tokens, 6 occurrences |
| Headroom | 780 | 780 | Unchanged, 5 occurrences | 360 → 360 tokens, 5 occurrences |
| LLMLingua-2 | 2,184 | 896 | 2,184 → 896 bytes, 14 occurrences | 1,008 → 420 tokens, 14 occurrences |

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T135307Z-0c45648a` | `efe15678abac0b1479314424ed99694dfcf709ee80d0acf6d6b45e77c6e27efd` | `7bbaeae1c3758d7319c826d221829d8275dcd54bf2edf7f12b83118a2643b12d` | `43b1e29b01a7e0f80f4a5c3e594671c13ba73678a980f8bcad44af9a6fb7d80f` |
| squeez | `preliminary-squeez-20260916T134817Z-7516a0c8` | `4040b3a99822d4e787bb632b4afc5215b50b7f6334880e386d46d12c492557bd` | `a95e8c465dacfcc50fb5965013f6e046f78d21701f9e29d5b697c889c230c59f` | `34e03a5ea679ce4670ff49b0427cab7405baca83765ff26afbded42f21c4b354` |
| Headroom | `preliminary-headroom-20260916T171929Z-f8ee6965` | `4495ad85916330a0f6a5d75fb48f0e0a663616f6b21f1468f24559882ae12b3f` | `14b237e66336990615c5d6541e7632700a283e906079ceb1477e794b2e2f5fbb` | `2855cb5da3ebf8b07baf0726ddb927b1b6280efb1bbf0635c80887a8310c42c5` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T135754Z-07c4f9b6` | `32e24325baa11c419c05c750a512bde5262b1abb2e2eb33c7168ae969cb6367c` | `86c038b394c726272b63458b41eea3bc25df6411566af7386461ebb0ab82a2b9` | `2924b628fb40d576d6573134b2e6eac507b87fe085e6ad1a206d03f65839b6bb` |

## `schemelike-metacircular-eval`

The task was selected after eligible log candidates were confirmed in a no-compression run from the fixed task list. All four conditions were wrong answers, with matching remote evidence and restored-workspace regrade verdicts. Actual string changes occurred in 28 `Headroom` occurrences and 25 `LLMLingua-2` occurrences.

The first `none` and `squeez` runs ended before grading with `BrokenPipeError` while returning API responses to Harbor. Their verified calculated API costs of `$2.7775765` and `$2.756729`, respectively, are separated as technically incomplete cost. A subsequent `none` run also ended before grading when the virtual machine stopped; its verified cost of `$3.526499` and unknown amount of `$0.2092325` for the final request without a response are preserved separately. The `none` and `squeez` rows below are newly completed attempts from source that only removed the HTTP response timeout; `Headroom` and `LLMLingua-2` link the existing completed results unchanged. Image, model, task files, and grader were the same, but this source boundary remains part of result interpretation.

- No-compression candidate-screening run: `screening-diagnostic-20260916T094053Z-af0eb5d6`
- No-compression candidate-screening attempt: `1b629b33944e18b62e0996b15ff01b29331c97b880cd7eac2f610a1428889319`
- Initial comparison ledger: `preliminary-candidate-20260916T101943Z-ee8097ae`
- Continuation-run ledger: `preliminary-candidate-retry-20260916T122727Z-a4b9bccc`
- Initial manifest file / content SHA-256: `0680d53c90fd34088ada38dbb741fce90142efe85d3f7489f0a4fc1987e7a404` / `8c51de590e40f29fb46f45f78411a3431d8601984c17fef493cbc763073e4956`
- Initial state-file SHA-256: `8b96294f59b167e030787dbfc286ac9480ecde7386f1139cc26e395d1a63bc2d`
- Continuation-run manifest file / content SHA-256: `d0bcd6d9937bfd0084b2040032d153bb5ef3c7cabec78acaf1aadb2d36c46bb3` / `2012e69bb66f4c039d16802799a7e93648718cff91fbe64f3d75f6328a108d46`
- Continuation-run state-file SHA-256: `5792c5903a15bb10daba477bf49c9968fcf99a506e9ee6d964626d022103eee5`
- Completed-condition linkage record SHA-256: `0eb987fe70503c4f28ca03b2a35546c12d44e69ecd3440819ec78650b3d2e051`
- Image digest: `sha256:b485be38bf80d56c1a4cd9da95bbf7ec129dc03f6786b86c0525518a96f6d1db`
- Task-file tree SHA-256: `cdde59f95154cd2a75e115ab324de2daa7614ffe4fdaea4ae83fa8dfc89be047`
- Effective grader SHA-256: `20812107bc3bfc541728a2d10e3da0552e907d949e1347a03d33aa26954f8902`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | wrong_answer | 21 | 21 | 21 | 0 | 0 | 0 | 267,099 / 115,200 / 10,416 |
| squeez | wrong_answer | 33 | 33 | 33 | 31 | 0 | 0 | 644,441 / 498,176 / 22,887 |
| Headroom | wrong_answer | 31 | 31 | 31 | 28 | 28 | 0 | 634,439 / 410,368 / 18,874 |
| LLMLingua-2 | wrong_answer | 28 | 28 | 28 | 25 | 25 | 25 | 433,856 / 283,392 / 15,484 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc full-overlap allocation | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.5647875 | $0.07469401037699647 | Unknown | $0.0000432 | Unknown | 667.241798585 / 691.962220 |
| squeez | $0.8335115 | $0.13655568108048705 | Unknown | $0.0000432 | Unknown | 1,219.852258293 / 1,230.156086 |
| Headroom | $0.9458795 | $0.18214248023708662 | Unknown | $0.0000432 | Unknown | 1,627.079243924 / 1,639.533327 |
| LLMLingua-2 | $0.679268 | $0.11247991523623467 | Unknown | $0.0000432 | Unknown | 1,004.783379541 / 1,124.735810 |

| Condition | Candidate-input UTF-8 bytes | Adapter-output UTF-8 bytes | Actually changed candidate input → output | Preserved-source token calculation |
|---|---:|---:|---:|---:|
| none | 0 | 0 | Not applicable | Not applicable |
| squeez | 25,141 | 25,141 | Unchanged, 31 occurrences | 8,091 → 8,091 tokens, 31 occurrences |
| Headroom | 24,892 | 18,676 | 24,892 → 18,676 bytes, 28 occurrences | 8,344 → 5,852 tokens, 28 occurrences |
| LLMLingua-2 | 22,225 | 15,900 | 22,225 → 15,900 bytes, 25 occurrences | 7,450 → 4,500 tokens, 25 occurrences |

| Condition | Source revision | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|---|
| none | `00a8ba5903c8407746a984a82465a9e601032146` | `preliminary-none-20260916T171929Z-0021aa5c` | `a0151665545cabb05e871b136e3596a0d4570543b5336568d490be78c3a79080` | `db011207501c94df4a740ec699872761a83751fcb4e047609432ab31602f2930` | `15924921ba6a6ad915cb36eb57b6ef73f5dd94ab3ce0d15f566d26e51f0fe1de` |
| squeez | `00a8ba5903c8407746a984a82465a9e601032146` | `preliminary-squeez-20260916T122758Z-0fcdfd81` | `e043931230d06f937fb72a445ac4b3ebbd2c08b99e4343104ef7560dec669140` | `2f9d4dfd8aaa605253d28a3ecdf8459f3f712e117330ad383121126d3414471c` | `6901b475ce9f31e9356b8da0964fc2e84f926ac5aea266f7112ea2bc43fb8558` |
| Headroom | `5e1f8655950471ea15b1b428632b074070dda020` | `preliminary-headroom-20260916T102636Z-02be9080` | `102f82327e5a7e3133d915d3aa02167de5c367335c7c0328735f1b9362920a2a` | `d024175757cf9a1f55511a58e08e91b149b7d56f7008c744a29e12529619105c` | `f6db6c2b5c63634ec6cb698412e1a6478d48d519dd2c8791a9c8ee3020127613` |
| LLMLingua-2 | `5e1f8655950471ea15b1b428632b074070dda020` | `preliminary-llmlingua2-20260916T105358Z-31e56494` | `56b78b533038c4a3d118a5e0de7f31d02afb54343138db8b1faf7eff3b52cbad` | `e54f1f1318af56b797d5f2601111f582ab2c014befb95aa25c750209fbc49f6b` | `05bead9fa2e6f87c91a6c4760661659387d96592dd466389ab462b01e93c8b3d` |

## `build-pov-ray`

The task was selected after eligible log candidates were confirmed in a no-compression run from the fixed task list. The new `none` condition passed, while the three compression conditions were wrong answers. Remote-data verification and matching restored-workspace regrade verdicts were confirmed for all four. `squeez` processed 49 eligible log candidates but changed no strings; `LLMLingua-2` actually changed 13 occurrences.

The first `squeez` attempt ended before grading because the virtual machine stopped. The original run and comparison state file, which remained marked running, were not overwritten. Quality, tokens, and completed cost below come only from a new post-recovery attempt. Verified cost from the interrupted attempt is recorded separately in the earlier technical-incompleteness section.

- No-compression candidate-screening run: `screening-diagnostic-20260916T121255Z-540a6ade`
- No-compression candidate-screening attempt: `e00daac34e6723792fa31d11a27e0310b4529f7538154e5f971b3d79e3fc7cda`
- Comparison ledger: `preliminary-candidate-20260916T135051Z-9e01ad2b`
- Comparison manifest file / content SHA-256: `79ff957367263972276f04dbb9625a6a34260c0979a6813a91c22db8cad1588f` / `8c21c834389ec7813559c3fbf08cb86686fd8d262978bb3b97627ad3f3455f58`
- Post-interruption preserved state-file SHA-256: `095f6c9b93df2176accd6ad25153243df17316eaa0e021da2fb8c294d3b05e2a`
- Completed-condition linkage record SHA-256: `84362319499994f693bc95092c11d2ff625e70d79918c407695b0cb1efcc5368`
- Image digest: `sha256:874baf49341e2853a15a9184e308c7eb632e97f434359fcff2891c6e5ca1b39b`
- Task-file tree SHA-256: `1c30f244b37c0f1e04c8d8bc36223165f75177796195304841e70afe8a770e49`
- Effective grader SHA-256: `20812107bc3bfc541728a2d10e3da0552e907d949e1347a03d33aa26954f8902`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | pass | 21 | 21 | 21 | 0 | 0 | 0 | 550,029 / 423,168 / 11,823 |
| squeez | wrong_answer | 26 | 26 | 26 | 49 | 0 | 0 | 770,466 / 529,664 / 9,174 |
| Headroom | wrong_answer | 15 | 15 | 15 | 0 | 0 | 0 | 277,159 / 152,192 / 7,030 |
| LLMLingua-2 | wrong_answer | 15 | 15 | 15 | 13 | 13 | 13 | 287,941 / 212,096 / 7,943 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc full-overlap allocation | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.6002895 | $0.15107289233022267 | Unknown | $0.0000432 | Unknown | 1,349.534544784 / 1,382.128169 |
| squeez | $0.872031 | $0.12218473746657371 | Unknown | $0.0000432 | Unknown | 1,091.476584605 / 1,127.090461 |
| Headroom | $0.4559155 | $0.061197731246749563 | Unknown | $0.0000432 | Unknown | 546.679501369 / 579.537318 |
| LLMLingua-2 | $0.3617815 | $0.07686238065858682 | Unknown | $0.0000432 | Unknown | 686.611860219 / 931.859954 |

| Condition | Candidate-input UTF-8 bytes | Adapter-output UTF-8 bytes | Actually changed candidate input → output | Preserved-source token calculation |
|---|---:|---:|---:|---:|
| none | 0 | 0 | Not applicable | Not applicable |
| squeez | 7,197 | 7,197 | Unchanged, 49 occurrences | 1,929 → 1,929 tokens, 49 occurrences |
| Headroom | 0 | 0 | Not applicable | Not applicable |
| LLMLingua-2 | 3,614 | 1,755 | 3,614 → 1,755 bytes, 13 occurrences | 923 → 455 tokens, 13 occurrences |

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T173444Z-b2a4a2af` | `320ca5f28369ffa1a8117235f6fd9e6392df67be601f9ae77c4822ceb35ebaa5` | `f51f1cb1677fbe29d4509cce729bae26a28e941e597157903676bbdb8fbdf192` | `4c9d5d07b1826eec9eefdf5309721855c744aede386e87272aa259e06ef9ea30` |
| squeez | `preliminary-squeez-20260916T171929Z-8233531d` | `4043462b338d5ecb2df67d1cb8e94314708d5f19bda34bc6ff17049e197ee103` | `28c1221c9e2837e74368d0a5b2977f2bc0bca35d5a1e700aea610beedae74c9c` | `af69d1d659ccd2ae98ac3a90db251d5ffd064b1b0fc8939cbfe92768c0cd5e51` |
| Headroom | `preliminary-headroom-20260916T140732Z-71fe9945` | `c319e5aca88776295216a7fb2397f5da993b739e4e9b5fdfeb1b3143b7df40cb` | `4e12ce7ee13b401073acf7810c11a571dc435d758b51e9b6b7da489b34eb4444` | `8bb7bf9cb33989f99a37ce3893f744c3a2d99cd479d870e316bf1822c4406369` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T173445Z-7e0a031a` | `368c26fca9bcddbbfdb3e78ff4fe61647cabef0c9c1f29be65e9823eb5ffa26f` | `6f52ce26289833cdbaecdb53c4498d8f4fa564a02e302a2af81a2d4ed7bc5a69` | `95126de34bb5941924abf54915cd35b272434af26b705d746da8210840315fa0` |

The post-hoc preserved-source calculation record is `build-pov-ray-preserved-pairs.json`. Its file SHA-256 is `4313bb2fbdde7a11a16d930c6790acd5c1af22fa204a549fc6d5762927e5ab1b`, and normalized condition-data SHA-256 is `3cc5f08e79e0762ddd785ad522f28444a84424d1f77a6be079c87f1f2e0ddc22`. The same tokenizer calculated 62 actual occurrences: 13 changed and 49 remained identical. Changed segments were `3,614 → 1,755 UTF-8 bytes` and `923 → 455 tokens`.

## `dna-insert`

The task was selected after no-compression screening in the fixed task list exposed 1 eligible log candidate totaling 153 UTF-8 bytes. All four conditions were wrong answers, with matching remote-data verification and restored-workspace regrade verdicts. In the new runs, `none` processed 27 eligible log candidates and `Headroom` processed 16, but neither changed any strings. `squeez` and `LLMLingua-2` had no eligible log candidates; actual string changes were 0 in all four conditions.

- No-compression candidate-screening run: `screening-diagnostic-20260917T022412Z-bab5ddbb`
- No-compression candidate-screening attempt: `d3bfba665cf58cc1570be83e803c5211af71fb19739164663fc9bb200ced7489`
- Comparison ledger: `preliminary-candidate-20260917T032227Z-f321090f`
- Comparison manifest file / content SHA-256: `7267d775248d632f3c403c0746e28f9ae705b04c5fb01984644dcb164c53b8be` / `43d02174019f9e8f6adcfa0e14ae8df6e6654fdc4b00552eb0b7d01839831068`
- State-file SHA-256: `55fbc4942b37fdbe390e62ad348fb744bb62af3528e89f5fa08a3730e0f325db`
- Completed-condition linkage record SHA-256: `7dc196bb9431fa4159eb24810dec34ab2c8c3a64e8a2b97f1e05939b7d15fe7d`
- Image digest: `sha256:4dd8760694e355de85ecf03605cb487ccdb33322f6afad513d2920829baa33b2`
- Task-file tree SHA-256: `8cafcbe9f8c0d3dad08e0b1600fe1d14fea6ca84aeeba10d8ed82281a81d3855`
- Effective grader SHA-256: `20812107bc3bfc541728a2d10e3da0552e907d949e1347a03d33aa26954f8902`

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | wrong_answer | 12 | 12 | 12 | 27 | 0 | 0 | 139,512 / 42,624 / 6,426 |
| squeez | wrong_answer | 4 | 4 | 4 | 0 | 0 | 0 | 24,556 / 0 / 2,501 |
| Headroom | wrong_answer | 9 | 9 | 9 | 16 | 0 | 0 | 156,543 / 67,456 / 11,321 |
| LLMLingua-2 | wrong_answer | 93 | 93 | 93 | 0 | 0 | 0 | 1,654,248 / 1,415,552 / 12,327 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc full-overlap allocation | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.349266 | $0.026227209318876267 | Unknown | $0.0000432 | Unknown | 234.287742551 / 248.527463 |
| squeez | $0.09890499999999999 | $0.013461495329141617 | Unknown | $0.0000432 | Unknown | 120.251587146 / 134.692310 |
| Headroom | $0.4093965 | $0.053021399239765274 | Unknown | $0.0000432 | Unknown | 473.640309162 / 487.186572 |
| LLMLingua-2 | $1.135533 | $0.17383584123644563 | Unknown | $0.0000432 | Unknown | 1,552.876021527 / 1,726.402952 |

| Condition | Candidate-input UTF-8 bytes | Adapter-output UTF-8 bytes | Actually changed candidate input → output | Preserved-source token calculation |
|---|---:|---:|---:|---:|
| none | 3,304 | 3,304 | Unchanged, 27 occurrences | 1,191 → 1,191 tokens, 27 occurrences |
| squeez | 0 | 0 | Not applicable | Not applicable |
| Headroom | 1,392 | 1,392 | Unchanged, 16 occurrences | 608 → 608 tokens, 16 occurrences |
| LLMLingua-2 | 0 | 0 | Not applicable | Not applicable |

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260917T032244Z-7b74a2ab` | `c5e17e60bcf751720635f77542b1240a506e9e16710856bb745e420a41147e2b` | `0f49d4cf028e8b857bc098cee0c35c5c549c08ee80bda420d91f0cac5f85d504` | `5260c93f2caca9898bed200f59b4b274e1a935fa8a738d9916be566ede727676` |
| squeez | `preliminary-squeez-20260917T032244Z-40378370` | `faa20ac379a8c4298b28c236f2aa63081c8251889f2025780f60758aae30463e` | `1379fc98bb62ecb1aa09fb8a92f155137b4f8264777984add44ac81ebdf8e776` | `c9c09b581668d938572a21ac711b3e2dce925f9596adf62d3ccd1b53fc1640e6` |
| Headroom | `preliminary-headroom-20260917T032244Z-0a4d4dfa` | `85ded66c8bf480a5bc6884b1f4c6d8327eae7958ecaf45b7f4e27cea75bfd98e` | `f9d84c07c250c7e77ccd979b4455181d4d6b8dd3644b3e645f222e3f45d4a30d` | `d1b75a05b99fe012934682c22f71abdd639ba0e1c4b88148facd1fff2f110272` |
| LLMLingua-2 | `preliminary-llmlingua2-20260917T032655Z-3f73c677` | `70f8b68195072001a8ae957eaf812a7833b212ecd0639469946c0d4d0f20f700` | `8690887ace36bbfb11d80799e894aecc1369d3ae032c28bef914d5983714e992` | `94aa9fe86ef782dd6df41c741c97b85586b11639620bf62c3092c06c5764b884` |

The post-hoc preserved-source calculation record is `dna-insert-preserved-pairs.json`. Its file SHA-256 is `a62a798299eba3a1a4f16287e807aac9f942990afb5ce0ced37e0c63e20eb703`, and normalized condition-data SHA-256 is `1f564ec6c0cd56fd7e2d37a931bce81a69d82eb6a342995ce3e9e502296d02e8`. The same tokenizer calculated 43 actual occurrences, all with identical strings. `none` was `3,304 → 3,304 UTF-8 bytes` and `1,191 → 1,191 tokens`; `Headroom` was `1,392 → 1,392 UTF-8 bytes` and `608 → 608 tokens`.

## `feal-differential-cryptanalysis`

The task was selected after no-compression screening through the second request exposed 2 eligible log candidates totaling 158 UTF-8 bytes. Neither quality outcome nor expected savings informed selection. The new `none` condition completed before the virtual-machine interruption and was reused unchanged; the compression conditions continued in separate post-interruption attempts. `none`, `Headroom`, and `LLMLingua-2` passed, while `squeez` was a wrong answer. All four retained the same verdict after restored-workspace regrading, and remote data was reverified.

- No-compression candidate-screening run: `screening-diagnostic-20260917T022829Z-05cb1d35`
- No-compression candidate-screening attempt: `a89303998a4155a3bd56af8fcfc0fcacb0b89272226bbaf4ce690c2f5b6f2ae7`
- Pre-interruption comparison ledger: `preliminary-candidate-20260917T032231Z-9b649cdd`
- Recovery comparison ledger: `preliminary-candidate-continuation-20260917T043809Z-3f007f53`
- Recovery manifest file / content SHA-256: `a35318069f6d8f41365a3a951a0757ebf9fa966983f31ac546acf5be7ec0db52` / `fb0efb15ab832bc1b418df94e3f505cd1bbce9b8642291b11ac786312d6c179b`
- Original state-file SHA-256: `cdaeeb4c6e8557c9792b92ebcb78305f10f90c7f709c277f34933b99550861c7`
- Completed-condition linkage record file / content SHA-256: `1240750fc6656b5a47c959630d06bb638d8581307fc9af1c2d0da19622ae7fe9` / `30c7f0ffe30bbdf6192a30a8b5ded78d7b251d3d207b1c81472c79a10c9c9653`
- Image digest: `sha256:bea93bafe9eab601ca58729f5735a13f8339f52055322d1cf840e3742b54a287`
- Task-file tree SHA-256: `989790834351a911253397de58956651e536286ecb1f561a0f65f9789b158d37`
- Grader source SHA-256: `585780e76d98094ad118d096f8c78f2281352dc9826e3687c4de152659631a3d`

The recovery ledger's `status.json` was not changed retroactively. A separate `completed-condition-link.json` links quality, restored regrading, remote payload, and usage for the pre-interruption completed `none` condition and the three post-recovery completed conditions. Three attempts that ended in Docker preparation immediately after the interruption remain technically incomplete before any provider request and are excluded from the quality denominator. Their costs were neither combined with completed-condition costs nor replaced with zero.

| Condition | Quality | Provider logical requests | HTTP attempts | Harbor stages | Eligible log candidates processed | Actual changes | LLMLingua-2 worker inference | Input / cached-input / output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | pass | 15 | 15 | 15 | 28 | 0 | 0 | 230,832 / 144,896 / 12,866 |
| squeez | wrong_answer | 13 | 13 | 13 | 24 | 0 | 0 | 185,516 / 88,064 / 11,726 |
| Headroom | pass | 8 | 8 | 8 | 14 | 0 | 0 | 76,318 / 15,232 / 6,619 |
| LLMLingua-2 | pass | 5 | 5 | 5 | 8 | 8 | 8 | 24,250 / 6,272 / 3,622 |

| Condition | Calculated provider cost | Ledger virtual-machine cost | Post-hoc full-overlap allocation | Verified Blob and network cost | Post-hoc allocated direct-cost total | Work / total condition time (s) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.444054 | $0.05334873082995415 | Unknown | $0.0000432 | Unknown | 476.5643601720003 / 488.456621 |
| squeez | $0.44153600000000004 | $0.05313859388245477 | Unknown | $0.0000432 | Unknown | 474.68720738700006 / 491.494086 |
| Headroom | $0.255808 | $0.02877416911582152 | Unknown | $0.0000432 | Unknown | 257.039743694 / 273.775364 |
| LLMLingua-2 | $0.100843 | $0.02036001179979907 | Unknown | $0.0000432 | Unknown | 181.87605782200035 / 348.277390 |

Ledger virtual-machine cost is the original value each condition runner calculated for its own work interval. Because these conditions overlapped with other tasks, a final allocation reconciling all overlap intervals under the same formula is not yet fixed.

| Condition | Candidate-input UTF-8 bytes | Transformed-output UTF-8 bytes | Actually changed candidate input → output | Preserved-source token calculation |
|---|---:|---:|---:|---:|
| none | 2,212 | 2,212 | Unchanged, 28 occurrences | 1,064 → 1,064 tokens, 28 occurrences |
| squeez | 3,480 | 3,480 | Unchanged, 24 occurrences | 1,680 → 1,680 tokens, 24 occurrences |
| Headroom | 1,106 | 1,106 | Unchanged, 14 occurrences | 532 → 532 tokens, 14 occurrences |
| LLMLingua-2 | 632 | 292 | 632 → 292 bytes, 8 occurrences | 304 → 156 tokens, 8 occurrences |

| Condition | Condition run ID | Condition-result SHA-256 | Run-summary SHA-256 | Attempt-file SHA-256 | Remote-payload SHA-256 |
|---|---|---|---|---|---|
| none | `preliminary-none-20260917T032249Z-95618ab6` | `f19a0f8eb0e1286447ba3c35701ffb44bacb8e1d093746acde8a826447f26fba` | `7a91747ef25c4516fa1ba0edaf3e74350a8d75f8700fe40866f78f9d1dd833e5` | `67780db279685b404f20b1ebfd385dd51e9ee00abdc6c73a5feb7e2e6c68b07a` | `767a801ebfbc6bde68976ed633d9f6eb439691ed4df4238dfa5caec39d452921` |
| squeez | `preliminary-squeez-20260917T043812Z-0cf0cd47` | `82daf0568f1c58abbc60079f72049471fa21ed17c9d85f883e072b95fa837ed7` | `038b797192738449622b33021f0747222ca01c527b3b03796c6476bd85641b67` | `c542393badbcf9a51908514b97d54e5dd09170f6457045ee409c613513a8db8f` | `baf94b9f5b980443093f342b53a6e120fdc4ddc9dc09403fc6c6e6a03281d341` |
| Headroom | `preliminary-headroom-20260917T043812Z-2bd25353` | `d9a96f4151d30453395ba5114d858f2d47c00f2742c05d085b684f54fc6f218d` | `c914a1400784cf5e0dd5b80e9f96021573b965c1f66416e5323e22292a49c551` | `9960b88badbcfef0c039cc004e3543d4708a22e2dcf2de5405ee724f329dd54e` | `9a1903788b8400159e37604507e7dfd892df3c4e0cde00ae0485e9283e83ce91` |
| LLMLingua-2 | `preliminary-llmlingua2-20260917T045332Z-616b1950` | `830d2ed1636f16dd3a3951a799b43c8477f8159b4dd7980374dcbbdfde751760` | `3ba614eef18b57d2d905236d931a80c96a8e725d0bae54a464f54c7eaa015e56` | `7c1982c02e3a995734dba694d2e6d425a19409c13c9a7a4930608ca98653e081` | `4af9559d2e75914ae215bd77d2929eac421ee97037cdd771fc00d47662df22d5` |

The post-hoc preserved-source calculation record is `preserved-pairs.json`. Its file SHA-256 is `1e94e0acc549ef8cb19581ecdf734253a8430db6be75111dce6f825aa3078ece`, and normalized condition-data SHA-256 is `15ee0988ee4971b4cf3de3eb7947f8ab1a89bd21529acbd87ea3bdac8d450ff0`. The same tokenizer calculated 74 actual occurrences: 8 changed and 66 remained identical. Source strings are not included in public material.

## Preserved-Source Token Calculation Evidence

- Aggregate file: `completed-through-financial-document-processor-all-preserved-pairs-v3.json`
- Aggregate-file SHA-256: `049d9766419401864e89ea3bbd200144be3611099d7fffa1b230cb9cac56b11f`
- Pre-normalization aggregate-content SHA-256: `99c76f123e5c68a73c6fbd56fe0b49fdbf5745021bc8ae21be5f7eddb3098711`
- Tokenizer: `tiktoken 0.14.0`, `o200k_base`
- Token-table SHA-256: `446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d`
- Scope: 28 conditions across 7 tasks, excluding `cancel-async-tasks`. Advance-screening input for `LLMLingua-2` is excluded.
- There were 189 calculable input-output pairs: 58 changed, 131 remained identical, 166 lacked source pairs, and 0 duplicate reads of the same evidence. All 173 actual repeated occurrences with identical content remain included.
- Directly changed segments total `155,504 → 80,906 UTF-8 bytes` and `62,432 → 32,698 tokens`. The unrounded token reduction is `0.47626217324449`.

The separate post-hoc calculation record for `gcode-to-text` is `gcode-to-text-preserved-pairs.json`. Its file SHA-256 is `25e0159f200983ecb7f2b053b76c75563e82fde7f0ca7cf0388a17b607ffebfd`, and pre-normalization content SHA-256 is `359881cc45304a83bb04227a6776412e57ad14acefe79c92588c4bacf158cf19`. The same tokenizer calculated all 7 occurrences, yielding `1,113 → 490 UTF-8 bytes` and `518 → 252 tokens`. Combined with the preceding aggregate, 204 input-output pairs were calculable: 65 changed, 139 remained identical, and 166 lacked source pairs. Directly changed segments total `156,617 → 81,396 UTF-8 bytes` and `62,950 → 32,950 tokens`; the unrounded token reduction is `0.4765687053216839`.

The separate post-hoc calculation record for `log-summary-date-ranges` is `log-summary-date-ranges-preserved-pairs.json`. Its file SHA-256 is `388d79880c5af9b1059178c5565abae342208fa92e36cfac7e292ae28d3c0e53`. The same tokenizer calculated 9 actual occurrences: 6 changed and 3 remained identical. Changed segments were `31,286 → 12,234 UTF-8 bytes` and `13,756 → 5,046 tokens`. Combined with the preceding aggregate, 213 input-output pairs were calculable: 71 changed, 142 remained identical, and 166 lacked source pairs. Directly changed segments total `187,903 → 93,630 UTF-8 bytes` and `76,706 → 37,996 tokens`; the unrounded token reduction is `0.5046541339660522`.

The post-hoc calculation record for the next three tasks is `post-log-summary-preserved-pairs.json`. Its file SHA-256 is `c3902901f58e066f8e82258c0de2ac3269dec20c314c702acae107539cca4cca`, and pre-normalization content SHA-256 is `245c566083dc94464534bbabd9c4394a4c85e47867a83e471d449bff697c8c8b`. The same tokenizer calculated 57 actual occurrences: 9 changed and 48 remained identical. Changed segments were `1,554 → 753 UTF-8 bytes` and `495 → 240 tokens`. Across the aggregate, 270 input-output pairs were calculable: 80 changed, 190 remained identical, and 166 lacked source pairs. Directly changed segments total `189,457 → 94,383 UTF-8 bytes` and `77,201 → 38,236 tokens`.

The separate post-hoc calculation record for `overfull-hbox` is `overfull-hbox-preserved-pairs.json`. Its file SHA-256 is `7db447d30c274737249df2c9c19ae411e8f8d78f783ce47d07b02b3d793b6fda`, and pre-normalization content SHA-256 is `fa5aa29ce1b6b4b40cd5cef351842d40bb9def8ec608b817cdb8b2598c9ed5d2`. The same tokenizer calculated 49 actual occurrences: 10 changed and 39 remained identical. Changed segments were `1,445 → 675 UTF-8 bytes` and `660 → 340 tokens`. Across the aggregate, 319 input-output pairs were calculable: 90 changed, 229 remained identical, and 166 lacked source pairs. Directly changed segments total `190,902 → 95,058 UTF-8 bytes` and `77,861 → 38,576 tokens`.

The original post-hoc calculation record for `prove-plus-comm`, `prove-plus-comm-preserved-pairs.json`, has file SHA-256 `5304e8af2a92fed08f55487c735f8a65dd8662e53afe4f4365942c7daa9078f7` and pre-normalization content SHA-256 `3a056049ef27e60348f10f337485baec74e9c3d1f3a9b08b5dc683ec914b3e26`. Its `token_table_sha256` value, `cb4e6b733f483dee7cb641ac571a312fe41a10ff32091886549e2eeb8c73ffcb`, was misnamed because the generation code hashed the condition-record array rather than the token table. No different vocabulary mapping was used in the calculation; the raw `o200k_base` token-table SHA-256 from `tiktoken 0.14.0` is `446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d`, matching the earlier record. The corrected record `prove-plus-comm-preserved-pairs-v2.json`, created without overwriting the original, has file SHA-256 `4d1484944af3b7022998536b8443b07fbd6454cf12248f86b2b92a8c9d30cc17` and pre-normalization content SHA-256 `a560963ae47f616b6ebfc0efd5eb86afcf89da40d79e5ac600b7744dd08c7b11`. Token counts did not change. Of 19 actual occurrences, 7 changed and 12 remained identical; changed segments were `963 → 408 UTF-8 bytes` and `446 → 210 tokens`.

The separate post-hoc calculation record for `raman-fitting` is `raman-fitting-preserved-pairs.json`. Its file SHA-256 is `2a843acff938870fae8dcb7d10b59b2d1596afffb636da9853d00bd6053e752f`, and pre-normalization content SHA-256 is `d6e3096a53d4fc5525dbc5b8a2034e0e548e7938e549d7378cb2cc13ba00baba`. The same tokenizer calculated 56 actual occurrences: 10 changed and 46 remained identical. Changed segments were `855 → 395 UTF-8 bytes` and `385 → 195 tokens`. Across the aggregate, 394 input-output pairs were calculable: 107 changed, 287 remained identical, and 166 lacked source pairs. Directly changed segments total `192,720 → 95,861 UTF-8 bytes` and `78,692 → 38,981 tokens`.

The separate post-hoc calculation record for `sqlite-with-gcov` is `sqlite-with-gcov-preserved-pairs.json`. Its file SHA-256 is `a7d424ba881c8426c444b5d688d0609891f9af8e4e2197daac53169a097abe15`, and pre-normalization content SHA-256 is `c68c7f8fae95ae051ff68c51d78a4239c18de766f9ed49a65bcea75ef75aebd3`. The same tokenizer calculated 4 actual occurrences, all changed. Changed segments were `1,112 → 572 UTF-8 bytes` and `284 → 140 tokens`. Across the aggregate, 398 input-output pairs were calculable: 111 changed, 287 remained identical, and 166 lacked source pairs. Directly changed segments total `193,832 → 96,433 UTF-8 bytes` and `78,976 → 39,121 tokens`.

The separate post-hoc calculation record for `vulnerable-secret` is `vulnerable-secret-preserved-pairs.json`. Its file SHA-256 is `0bc5da262b2d85e23d85325fd08d0f21c2ba8923f19247bbfc94335f73f483ca`, and pre-normalization content SHA-256 is `8e69f0eb4fe9a07b39ff0c74d82cb33a1b7fd607153415f4a4d52b2d77139fc7`. The same tokenizer calculated 18 actual occurrences: 4 changed and 14 remained identical. Changed segments were `604 → 248 UTF-8 bytes` and `280 → 128 tokens`. Across the aggregate, 416 input-output pairs were calculable: 115 changed, 301 remained identical, and 166 lacked source pairs. Directly changed segments total `194,436 → 96,681 UTF-8 bytes` and `79,256 → 39,249 tokens`.

The separate post-hoc calculation record for `video-processing` is `video-processing-preserved-pairs.json`. Its file SHA-256 is `54bd91c2c76c471c63d288e7da7d31cae4346ac5309073abbded8f32546a407e`, and pre-normalization content SHA-256 is `b8409cff4e837f02be383760e3c676be4d0375cf08e637016d5944ed2bf1693f`. The same tokenizer calculated 25 actual occurrences from the completed attempt: 6 changed and 19 remained identical. Strings from the first `LLMLingua-2` attempt, interrupted before grading, are excluded from the aggregate. Changed segments were `972 → 372 UTF-8 bytes` and `438 → 192 tokens`. Across the aggregate, 441 input-output pairs were calculable: 121 changed, 320 remained identical, and 166 lacked source pairs. Directly changed segments total `195,408 → 97,053 UTF-8 bytes` and `79,694 → 39,441 tokens`.

The separate post-hoc calculation record for `chess-best-move` is `chess-best-move-preserved-pairs.json`. Its file SHA-256 is `fc5243a7a348c6bf2d8b7ee903e1ec1904406583a5f7febb8dac4f5dda7076be`. The same tokenizer calculated 34 actual occurrences from the completed attempt: 14 changed and 20 remained identical. Strings from the first `Headroom` attempt, interrupted before grading, are excluded from the aggregate. Changed segments were `2,184 → 896 UTF-8 bytes` and `1,008 → 420 tokens`. Across the aggregate, 475 input-output pairs were calculable: 135 changed, 340 remained identical, and 166 lacked source pairs. Directly changed segments total `197,592 → 97,949 UTF-8 bytes` and `80,702 → 39,861 tokens`.

The separate post-hoc calculation record for `schemelike-metacircular-eval` is `schemelike-metacircular-eval-preserved-pairs-v2.json`. Its file SHA-256 is `f8ad5cb7f5f657c0fa0994562d3e830a9014979470ca6fb429dfc87cc7c12418`. The same tokenizer calculated 84 actual occurrences across the four completed conditions: 53 changed and 31 remained identical. Strings from three attempts interrupted before grading are excluded from the aggregate. Changed segments were `47,117 → 34,576 UTF-8 bytes` and `15,794 → 10,352 tokens`. Across the aggregate, 559 input-output pairs were calculable: 188 changed, 371 remained identical, and 166 lacked source pairs. Directly changed segments total `244,709 → 132,525 UTF-8 bytes` and `96,496 → 50,213 tokens`.

The separate post-hoc calculation record for `build-pov-ray` is `build-pov-ray-preserved-pairs.json`. Its file SHA-256 is `4313bb2fbdde7a11a16d930c6790acd5c1af22fa204a549fc6d5762927e5ab1b`, and normalized condition-data SHA-256 is `3cc5f08e79e0762ddd785ad522f28444a84424d1f77a6be079c87f1f2e0ddc22`. The same tokenizer calculated 62 actual occurrences across the four completed conditions: 13 changed and 49 remained identical. Strings from the first `squeez` attempt, which ended in a virtual-machine interruption, are excluded from the aggregate. Changed segments were `3,614 → 1,755 UTF-8 bytes` and `923 → 455 tokens`. Across the aggregate, 621 input-output pairs were calculable: 201 changed, 420 remained identical, and 166 lacked source pairs. Directly changed segments total `248,323 → 134,280 UTF-8 bytes` and `97,419 → 50,668 tokens`.

The separate post-hoc calculation record for `dna-insert` is `dna-insert-preserved-pairs.json`. Its file SHA-256 is `a62a798299eba3a1a4f16287e807aac9f942990afb5ce0ced37e0c63e20eb703`, and normalized condition-data SHA-256 is `1f564ec6c0cd56fd7e2d37a931bce81a69d82eb6a342995ce3e9e502296d02e8`. The same tokenizer calculated 43 actual occurrences across the four completed conditions, all with identical strings. Across the aggregate, 664 input-output pairs were calculable: 201 changed, 463 remained identical, and 166 lacked source pairs. Directly changed segments remain `248,323 → 134,280 UTF-8 bytes` and `97,419 → 50,668 tokens`, matching the preceding aggregate.

The separate post-hoc calculation record for `feal-differential-cryptanalysis` is `preserved-pairs.json`. Its file SHA-256 is `1e94e0acc549ef8cb19581ecdf734253a8430db6be75111dce6f825aa3078ece`, and normalized condition-data SHA-256 is `15ee0988ee4971b4cf3de3eb7947f8ab1a89bd21529acbd87ea3bdac8d450ff0`. The same tokenizer calculated 74 actual occurrences across the four completed conditions: 8 changed and 66 remained identical. Across the aggregate, 738 input-output pairs were calculable: 209 changed, 529 remained identical, and 166 lacked source pairs. Directly changed segments total `248,955 → 134,572 UTF-8 bytes` and `97,723 → 50,824 tokens`.

</details>
