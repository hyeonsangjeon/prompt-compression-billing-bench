# Static Compressor Measurements

**Evidence status:** Between 2026-09-11 and 2026-09-13 UTC, compressors were applied statically to stored requests for these measurements. There were 0 `gpt-5.4` calls and 0 native grading runs. LLMLingua-2's own local compressor inference is recorded separately.

## Shared Sample and Denominators

| Item | Value | Classification |
| --- | ---: | --- |
| Input | 5 purposively selected tasks, 15 historical runs, 56 stored requests | Fixed sample |
| Identified candidates | 107 occurrences, 27 unique inputs | Classification judgment |
| Protected content | 2,169 spans, 697,187 UTF-8 bytes | Measurement and validation |
| Full message content | 824,301 UTF-8 bytes | Measurement denominator |
| Full local tokens | 242,937 `o200k_base` tokens | tiktoken `0.14.0` calculation denominator |
| `gpt-5.4` and external API calls | 0 | Execution record |
| LLMLingua-2 local inferences | 107 in this measurement | Execution record |

The 127,114 candidate bytes are 15.42% of the full message content. This is the **identified candidate scope, not a validated upper bound**. Code, mixed-code spans, structured data, instructions, and uncertain spans were not added merely to increase the candidate count.

Occurrence counts include retransmitted conversation history. Do not interpret 107 occurrences as 107 independent tasks or inputs. The reductions below are local values counted after serializing the full message content again; they are not provider-billed tokens or quality results.

## Static Size

| Tool and profile | Actual behavior | Total local tokens | Token reduction | Total UTF-8 bytes | Byte reduction | Changed occurrences and unique inputs | Classification |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| squeez `1.48.4` | Discards content after the first 30 content lines | 242,937 → 208,594 | 34,343; 14.1366% | 824,301 → 750,030 | 74,271; 9.0102% | 18/107; 6/27 | Measurement, calculation, and discard classification |
| Headroom `0.36.5` paths-only | Groups common path prefixes | 242,937 → 242,457 | 480; 0.1976% | 824,301 → 823,111 | 1,190; 0.1444% | 10/107; 3/27 | Measurement, calculation, and grouping classification |
| LLMLingua-2 `0.2.2`, `rate=0.5` | Selects and discards tokens within lines | 242,937 → 214,682 | 28,255; 11.6306% | 824,301 → 761,302 | 62,999; 7.6427% | 107/107; 27/27 | Measurement, calculation, and token-selection classification |

These are static input sizes for three interventions with different quality characteristics. Reduction rate alone does not establish tool ranking, billed savings, or native quality.

## squeez Example

**Sample and denominator:** 18 changed occurrences and 6 unique inputs. Ten occurrences are file lists and eight are package-installation output. The discarded suffixes contain 1,362 lines and 78,382 UTF-8 bytes; after added metadata, the net reduction is 74,271 bytes. **Classification:** Measurement, calculation, and transformation classification.

The processed public example below replaces identifiers and locations with placeholders.

```text
# before, excerpt after the 30th content line
Fetched 2316 kB in 0s (26.5 MB/s)
...
Setting up nginx (1.22.1-9+deb12u9) ...
invoke-rc.d: could not determine current runlevel
invoke-rc.d: policy-rc.d denied execution of start.
Processing triggers for libc-bin (2.36-9+deb12u10) ...

# after
[first 30 content lines]
[... 54 lines truncated]
```

The first 30 content lines remain, but later installation diagnostics and completion signals disappear. In one compound command, an earlier listing filled all 30 lines and deleted all 10 lines of a subsequent `find` result. Native quality degradation was not measured in this sample.

## Headroom Example

**Sample and denominator:** 10 occurrences and 3 unique inputs changed among 107 candidate occurrences and 27 unique inputs. Reverse transformation reproduced the original bytes for 107/107 occurrences, and there were 0 reductions in displayed line count. **Classification:** Measurement, validation, and grouping classification.

The processed public example below replaces a private location with `<LOG_DIR>`.

```text
# before
<LOG_DIR>/2025-07-03_api.log
<LOG_DIR>/2025-07-03_app.log
<LOG_DIR>/2025-07-03_auth.log

# after
<LOG_DIR>/
2025-07-03_api.log
2025-07-03_app.log
2025-07-03_auth.log
```

The common prefix appears once while all file entries remain. This result measures only the restricted profile that permits `compact_lossless(text, "paths")`, not the full Headroom product.

### Measurement Scope Versus Product Features

**Classification:** Public-source review and classification judgment. This repository has 0 static measurements and 0 native executions using the settings below.

Within the reviewed Headroom `0.36.5` paths-only configuration, we did not observe location controls that distinguish types of messages or tool results for compression. This finding cannot be generalized to the entire Headroom product.

Headroom `0.37.0`'s [`coding` profile](https://github.com/headroomlabs-ai/headroom/blob/v0.37.0/headroom/agent_savings.py) configures tool search, deduplication across turns, lossy compression after lossless processing, file-read protection, analytical-context protection, and AST-based code compression. [`DEFAULT_EXCLUDE_TOOLS`](https://github.com/headroomlabs-ai/headroom/blob/v0.37.0/headroom/config.py) excludes `Read`, `Glob`, `Grep`, `Write`, `Edit`, web search and fetch, raw-content retrieval, and `view`-family tools. `DEFAULT_VERBATIM_EXCLUDE_TOOLS` in the same source separately leaves web search and fetch, raw-content retrieval, and `view`-family tools byte-for-byte unchanged. File-read protection also identifies reads through bash-family commands. Analytical-context protection skips code compression when the latest user request indicates analysis, review, audit, security, bug, debugging, correction, or error intent. The AST path uses tree-sitter to parse code, retain structure, and reduce function bodies. The size, preservation, and quality effects of this configuration on the repository's 56 stored requests have not been measured.

## LLMLingua-2 Example

**Sample and denominator:** All 107 candidate occurrences and 27 unique inputs changed. Of 2,375 nonempty source lines, 0 remained byte-identical. **Classification:** Measurement and token-selection classification.

```text
# before
2025-07-03 09:24:57 [ERROR] Unhandled exception: FileNotFoundError
2025-07-03 01:56:02 [WARNING] Disk space low: 1924 remaining
Setting up nginx (1.22.1-9+deb12u9) ...
invoke-rc.d: policy-rc.d denied execution of start.

# after
 09:24:57 Unhandled exception FileNotFoundError
 01:56:02 Disk space low 1924 remaining
. 22. 1-9+deb12u9...
.. execution.
```

Line counts stayed unchanged in all 107 occurrences, but `[ERROR]` and `[WARNING]` disappeared, and `1.22.1` split into `. 22. 1`. In `policy-rc.d denied execution`, `denied` disappeared, so the refusal state is not preserved and can be read in the opposite sense. Preserved line boundaries do not imply preserved fields, identifiers, or states.

LLMLingua-2 was measured on a system without a GPU running Linux kernel `3.10.102`, 8 CPUs, and 31 GiB RAM. It used Python `3.10.12`, llmlingua `0.2.2`, torch `2.13.0+cpu`, and model revision `ebaba9b0e874dadd3003ffcff828e4397e568089`. Compression time for one candidate span had a minimum of 2.20 seconds, mean of 4.13 seconds, and maximum of 15.60 seconds, with a denominator of 107.

For 25 input hashes and 105 occurrences within the same process, each input hash produced one output hash. Re-transforming three representative inputs in two separate processes also produced the same output SHA-256. This observation does not guarantee byte equality on another CPU or package version.

## Tool-Review Scope

**Classification judgment:** Among the eight reviewed tools, we did not find a currently reproducible summarization path that accepts arbitrary logs or command output, preserves required meaning, and offers controllable loss. Some products provide separate rule-based or generative summarization paths, but the three profiles fixed for the preliminary study perform discarding, grouping, and token selection, respectively.

This classification applies only to summarization paths. It does not mean that features such as tool-level exclusions or file-read protection are absent.
