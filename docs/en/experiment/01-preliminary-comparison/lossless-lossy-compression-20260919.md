# Lossy and Lossless Compression: What Is the Difference?

This guide distinguishes `none`, `squeez`, `Headroom`, and `LLMLingua-2` so they are
not mistaken for the same kind of compression. Here, **lossless compression** means that
a specified restoration procedure can reproduce the exact source bytes. **Lossy
compression** discards or changes information and therefore cannot guarantee restoration
to the same bytes.

## 30-Second Summary

- `none` does not mean no work; it is the **reference condition without additional
  compression**.
- In this repository, Headroom `0.36.5` uses a restricted paths-only configuration and
  checks byte-for-byte restoration on every transformation. It is called lossless only
  within that scope.
- squeez `1.48.4` discards output after the first 30 content lines. LLMLingua-2 `0.2.2`
  selects which tokens—units used to divide and count text—to retain. Both are lossy and
  do not guarantee source restoration.
- Transport compression reduces bytes transmitted over a network, while caching reuses
  previously processed content. Both differ from shortening the prompt instructions and
  context sent to the model.
- Greater compression does not automatically imply safety, quality, lower total API
  usage, or lower cost. Each requires separate measurement.

> **Scope for citation**
>
> “Lossless” applies only to the restricted Headroom `0.36.5` configuration that combines
> `compact_lossless(text, "paths")` with `path_unheading`. The descriptions of squeez
> and LLMLingua-2 apply only to the versions and settings validated in this repository.
> Do not extend this classification to whole-product safety or ranking.

## Three Distinct Layers

“Compression” can refer to different layers. Unless the reduced layer is stated, bytes,
tokens, cache, and cost can be misread as one outcome.

| Category | What changes | Source content | Measurement in this repository |
|---|---|---|---|
| Transport compression | Bytes transferred over a network | May be identical after decompression | Not separately tested |
| Cache | Reuses earlier computation or input spans | Input string usually unchanged | Observed but not controlled |
| Prompt-content reduction | Representation of instructions and context sent to the model | May be identical or different | Target of the four-condition comparison |

`gzip` is a common transport-compression example. The code below is a small synthetic
illustration, not a repository measurement.

```python
import gzip

source = b"alpha beta gamma\n"
packed = gzip.compress(source, compresslevel=9, mtime=0)
assert gzip.decompress(packed) == source
```

Even when transmitted bytes decrease, model input tokens may remain unchanged if the
service decompresses the bytes and supplies the same prompt. A cost change from cache
usage does not imply a shorter prompt string. Cache was uncontrolled in the preliminary
comparison, so cache differences are not attributed to compression.

## What the Four Conditions Actually Do

### `none`: Reference Without Additional Compression

`none` returns the input string unchanged. `NoOpCompressor` records the input,
transformer input, and output as the same string. It is a reference for the other three
conditions, not a compression method.

- **Validated:** Code contract and synthetic tests showing that the adapter leaves strings unchanged
- **Not validated:** A guarantee that the model always gives the same answer to the same question
- **Classification:** No compression

Even `temperature=0` does not guarantee deterministic model responses. Two `none` runs
can differ, and an equal result under another condition does not establish that compression
had no effect.

### `squeez`: Lossy Compression That Discards the Suffix

This repository used squeez `1.48.4` with `wrap "cat input.txt"`. In the reviewed sample,
it retained the first 30 content lines and discarded the rest. Completion signals or later
diagnostic messages can disappear, so exact source restoration is impossible.

- **Validated:** Executable SHA-256 and version, isolated execution environment, and before-and-after byte counts and content fingerprints
- **Static measurement scope:** 18 of 107 candidate occurrences and 6 of 27 unique inputs changed
- **Preliminary native-task observation:** 2 spans in 1 of 26 conditions actually changed
- **Classification:** Lossy compression

The source remains in private evidence, but the model receives no source-restoration tool.
Any guidance text inserted by squeez is not evidence that the model can recover the source.

### `Headroom`: Restricted Lossless Paths-Only Configuration

This repository used only `compact_lossless(text, "paths")`, not all Headroom `0.36.5`
features. It displays a repeated directory prefix once and lists file names beneath it.

```text
# synthetic source
/example/logs/first.log
/example/logs/second.log

# synthetic transformed text
/example/logs/
first.log
second.log
```

On every call, the adapter reverses the transformed text with `path_unheading` and checks
that its UTF-8 bytes equal the source. It retains the source if the transformed text is not
smaller and stops with an error if the displayed line count falls.

- **Validated:** Synthetic preflight, per-call byte-for-byte round trip, and helper-file SHA-256
- **Static measurement scope:** Restoration matched for all 107 candidate occurrences; 10 occurrences and 3 unique inputs actually changed
- **Preliminary native-task observation:** 53 spans in 4 of 26 conditions actually changed
- **Classification:** Lossless compression within a restricted paths-only configuration

Byte restoration establishes that information remains algorithmically recoverable. It
does not establish that the model interprets grouped paths exactly like the source or that
task quality remains unchanged. The result does not evaluate other Headroom profiles or
the whole product.

### `LLMLingua-2`: Lossy Selection of Tokens to Retain

This repository used LLMLingua-2 `0.2.2`, the trained MeetingBank checkpoint, a fixed
revision, and `rate=0.5`. It does not write a new generative summary; it selects source
tokens to retain. Unselected tokens disappear, so byte-for-byte restoration is impossible.

- **Validated:** Model and tokenizer file SHA-256 values, fixed settings, output agreement across worker processes for small synthetic fixtures, and before-and-after content fingerprints and sizes
- **Static measurement scope:** All 107 candidate occurrences and 27 unique inputs changed
- **Preliminary native-task observation:** 154 spans in 18 of 26 conditions actually changed
- **Classification:** Lossy compression

In the static sample, `[ERROR]`, `[WARNING]`, parts of version strings, and a word
indicating refusal disappeared. Equal line count does not establish preserved fields or
meaning. Matching output hashes in one fixed environment do not guarantee byte equality
on another CPU or package version.

## Validation Scope

Static measurement and the preliminary native task comparison have different purposes and
denominators. Static measurement checked size and restoration on stored requests without
measuring model quality or provider billing. The native comparison solved and graded tasks
but ran each condition once.

### Static Measurement Conditions

| Item | Fixed scope | Unit measured | Missing |
|---|---|---|---|
| Sample | 5 purposively selected tasks, 15 historical runs, 56 stored requests | 107 candidate occurrences and 27 unique inputs | Representativeness of customer data |
| Model calls | 0 `gpt-5.4` and external API calls | Local transformations only | Native quality |
| Size | UTF-8 bytes and `o200k_base` local tokens | Before and after | Provider-billed tokens |
| Restoration | 107/107 Headroom candidate occurrences | Matching UTF-8 bytes | Model semantic understanding |

### Preliminary Native-Task Comparison Conditions

| Item | Fixed scope | Observation | Limitation |
|---|---|---|---|
| Sample | 26 tasks × 4 conditions = 104 conditions | Quality, requests, usage, and transformations by condition | Not 104 independent tasks |
| Repetitions | One per condition | `pass` or `wrong_answer` | Cannot decide non-inferiority or ranking |
| String changes | 209 spans in 23 conditions | 2 squeez, 53 Headroom, 154 LLMLingua-2 spans | Changed spans, not full requests |
| Execution controls | Same pinned tasks and settings | Per-run evidence and restoration regrading | Cache, request count, path, and concurrency uncontrolled |

**Observation.** Strings were unchanged in all 26 `none` conditions. Actual changes
appeared in 1 squeez condition, 4 Headroom conditions, and 18 LLMLingua-2 conditions.
Previously published preliminary evidence includes different quality judgments where the
actual string-change count was zero.

**Possible explanation.** Model request count, execution path, and cache usage differed by
condition. Whether an input contained a candidate and whether that candidate matched a
tool's rules can also affect change count.

**Limitation.** Each condition ran only once, without first measuring same-condition model
variability in the comparison. A known verifier false-failure case also existed. Quality
and cost differences are therefore not established as effects caused by compression.

## Restorability and Quality Are Different Questions

Losslessness asks whether source bytes can be restored. Quality asks whether the model
produced a correct task result. Neither question substitutes for the other.

| Situation | Restorability | Quality requirement |
|---|---|---|
| Transport compression | Source must match after decompression | Even with identical model input, response variability is assessed separately |
| Headroom paths-only | Bytes must match after the specified inverse | Grade whether the model used the grouped paths correctly |
| `squeez` | Discarded suffix cannot be recovered from the transformed text alone | Grade whether omitted information was needed |
| `LLMLingua-2` | Discarded tokens cannot be recovered from the transformed text alone | Validate critical fields, states, instructions, and final answer |

Lossy compression can still `pass` some tasks, while a model can misinterpret a lossless
representation and produce `wrong_answer`. Conversely, `wrong_answer` is not direct
evidence that compression deleted information. Task difficulty, response variability,
execution path, and grader errors may be mixed in.

## Keeping Units Separate

Before translating a size reduction into cost savings, identify the measured unit.

| Value | What it counts | Source | What it does not directly establish |
|---|---|---|---|
| Transport bytes | Bytes before and after network compression | Transport instrumentation | Reduced model input tokens |
| Local tokens in changed spans | Tokens recounted only in strings that actually changed | Local `o200k_base` calculation | Reduced total API usage |
| Full API usage | Input, cached-input, and output tokens across all requests | Provider response | Actual billed amount |
| Calculated cost | USD from API usage multiplied by a fixed price table | Local calculation | Completed invoice reconciliation |
| Actual invoice | Amount billed separately by the provider | Billing record | Causal effect of one transformation |
| Quality | Pass status from a built-in task grader | Verifier | Losslessness |

Even when local changed-span tokens fall, conversation history, retries, and added requests
can increase total API usage. A lower calculated cost is not called an actual billed amount
without price-table and invoice reconciliation. Provider-reported cached tokens are part
of full API usage, not the same as tokens deleted by compression.

## Safe Decision Sequence

1. **Choose the boundary.** Separate reducing transport bytes, changing prompt content, and using cache.
2. **Define restoration.** A method called lossless must reproduce the exact source bytes after its specified inverse.
3. **Define protection scope.** Exclude instructions, code, structured data, and identifiers that must not change.
4. **Measure quality separately.** Actual task grading and verifier validation are required regardless of lossiness.
5. **Measure usage and cost separately.** Record local tokens, provider usage, calculated cost, and invoices independently.
6. **Decide after repetition.** Do not rank safety or compressors by differences smaller than same-condition variability.

Current public evidence cannot decide product adoption, compressor ranking, quality
non-inferiority, or population cost savings. Before lossy compression is applied to
customer data, define critical-field preservation, repeated evaluation, verifier
validation, and stopping criteria.

## Ten Questions Remaining Before Further Validation

This table identifies design gaps in current evidence; it is not approval for a new
experiment.

| No. | Question | Current answer | Gap |
|---:|---|---|---|
| 1 | What decision would the result support? | Could inform whether lossy compression is acceptable | Adoption criterion remains undefined |
| 2 | What would falsify the hypothesis? | One restoration mismatch rejects a lossless claim | Quality-rejection rule for lossy compression remains undefined |
| 3 | How many axes moved? | Request count, path, cache, and concurrency differed alongside compression | Compression axis not isolated |
| 4 | Was variability measured first? | Preliminary comparison ran once per condition | Same-condition repetition needed |
| 5 | Who validates the judge? | Built-in verifier and restoration regrade were used | Known false-failure effect needs review |
| 6 | Was configuration actually controlled? | `temperature=0` was recorded | Determinism not guaranteed |
| 7 | What does the tool measure? | Bytes, local tokens, usage, cost, and quality are separate | Invoice reconciliation is separate |
| 8 | Does input favor one side? | Conservatively identified log candidates from a public benchmark | Customer-input representativeness unknown |
| 9 | When does it stop? | Historical execution protocol is recorded | New customer-validation stopping rules need prior agreement |
| 10 | Is it tied to a customer environment? | Public Terminal-Bench 2.1 observation | Cannot generalize to customer data |

## Public Evidence

- [Static compressor measurements](../compressors.md): static transformation scope, examples, and units for three tools
- [Technical preliminary-comparison evidence](preliminary-comparison-20260916.md): quality, actual changes, usage, and cost scope for 26 tasks and 104 conditions
- [Public preliminary-comparison aggregate JSON](../../../../data/experiment/preliminary-comparison-summary.json): changed-condition and span counts by condition
- [Native execution contract](../../../native-contract.md): fixed profiles and protection, restoration, and instrumentation boundaries
- [Compressor implementations](../../../../src/compressors.py): `NoOpCompressor`, `SqueezCompressor`, `HeadroomPathsCompressor`, and `LLMLingua2Compressor`
- [Synthetic compressor tests](../../../../tests/test_native_compressors.py): Headroom round-trip restoration and LLMLingua worker validation

Examples use only public material and small synthetic strings. They exclude customer
source, service endpoints, credentials, internal addresses, and personal paths.
