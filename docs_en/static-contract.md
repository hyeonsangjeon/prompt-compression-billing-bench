# Static execution contract

This is an implementation contract, not an experimental results report.
`python run.py static` reads stored text requests and invokes no model or native judge.

## One selected ledger per run

`ledgers/static.toml` selects the frozen historical sample by manifest hash.
`ledgers/demo.toml` is a separate, clearly synthetic input profile. Do not merge
the demo's numbers with historical observations. Environment variables supply
only local resource locations; the ledger pins their contents and expected counts.

The historical input contract fixes five purpose-selected tasks, fifteen past
runs and fifty-six successful HTTP request occurrences. It includes retransmitted
conversation history, not fifty-six independent tasks. Source request bytes,
complete ordered partitions and all request settings are hash-bound. The original
historical model is not invoked, nor is its native judge rerun.

Each ledger declares one static pass, concurrency one, no model calls, no API
spending, an input-byte limit, a compressor timeout and a measurement-phase wall
limit. The wall timer covers compressor initialization, transformation and result
writing after input/tokenizer preflight. Git commands have separate timeouts;
installation, initial tokenizer download and input preparation are outside this timer.
Model-call spending zero is an execution restriction, not a measured provider invoice.

The older root `ledger.toml` belongs exclusively to the optional native Ollama
runner. It does not override the static ledger and cannot enable a paid provider.
That runner needs `uv sync --locked --extra native`; it is not a third compressor condition.

## Compressor selection

`compress(text) -> CompressionResult(text, tool_reported, telemetry)` is the common
boundary in `src/compressors.py`. The static ledger schema permits only `none` and
`squeez`; native-only adapters cannot be selected by a static ledger. Unsupported
static names fail before a run and get no success-shaped placeholders.
A history-aware API may require more context than a stateless text adapter; that
must be designed explicitly rather than concealed behind an empty implementation.

`compressor.name` selects a specification under `compressor.tools`. Versions and
options for both tools already exist in the same ledger, so changing the name
does not also require changing a version field. Each result resolves the selected
specification into `compressor.name`, `version`, `target`, `options` and binary hash.
`unavailable` means **no independent tool version exists** for the built-in no-op;
the source commit identifies its implementation. It does not mean
an unknown squeez version was accepted.

The squeez adapter uses the checked Linux x86-64 1.48.4 executable and
`squeez wrap "cat input.txt"`. The earlier tool guide describes 1.48.0; its findings
are not silently attributed to 1.48.4. A fixed, neutral filename and `cat` hint
avoid executing original benchmark commands or treating their text as shell code.
The adapter absorbs the file-backed wrap interface; callers still pass and receive text.

Each span gets a fresh HOME and working directory. The environment is an explicit
allowlist without provider credentials. Sessions, stdout, stderr and any recovery
stash stay under the private run directory. Across-call redundancy is deliberately
not reused; this is not a measurement of a persistent squeez session. This is
not an OS-level network sandbox or an implementation of live recovery calls.

The full stdout is the replacement, including metadata and retrieval markers.
There is no extra byte-savings gate or header stripping in the measurement path.
An exit failure, timeout, changed binary, invalid UTF-8 or protection violation
stops the run. A failed compression is not relabeled as no-op.

## Tool-neutral protection, tool-specific limits

`src/protection.py` verifies the complete ordered character partition, UTF-8 sizes,
span hashes and source request hash. Only explicitly classified `log` spans in
noninitial `user` observation messages may change. It does not assume every user
message is tool output. Code, code-containing mixed spans, structured output and
other protected categories cannot be selected merely to increase savings.

Every adapter, including no-op, traverses `src/pipeline.py`. The same reconstruction
and full-payload check protects roles, message count, settings and all designated
noncandidate text. No-op preserves parsed payload values and message-content
bytes; saved transformed JSON uses canonical serialization, not the original
HTTP JSON whitespace. Violations latch the pipeline and prevent later forwarding.

These checks are tool-neutral because they surround, rather than trust, the
adapter. They prove preservation of **designated** protected spans, not correct
classification or preserved meaning inside compressed logs. Tool-specific tests
must still cover prefix removal, anchor retention, rewriting, refusals and actual
retrieval. The callback boundary is reusable but is not wired into a live Harbor
transport or an automatic runtime observation classifier yet.

## Source commit and snapshots

Keep `--source-commit` on the CLI. Putting the commit's own SHA into a committed
ledger would create a self-reference. A full SHA must name the clean checkout's
HEAD. Source files and local schemas are compared byte-for-byte with that commit;
replacement objects and implicit lazy fetching are disabled. Each record carries
`source_commit`, source inventory hash, ledger hash, input manifest hash and run ID.

Tracked ledgers are compared with the same commit. An external or ignored ledger
is allowed for controlled name-only swaps, but is explicitly recorded as
`ledger_origin=external_snapshot`, never falsely called committed. Its exact bytes
and hash are saved beside the source and manifest snapshots. The chosen input
files are copied by content into the run so later verification does not depend
on their original host paths. An input hash mismatch stops preflight.

Verification compares snapshots with the **recorded commit**, not today's HEAD,
then reconstructs all span edits and recomputes both local token counts and totals.
That commit must be available locally. No network fetch, source checkout change,
model call or squeez rerun occurs during verification. Historical sanitized native
evidence without a SHA remains historical; it must never be backfilled from a new commit.

## Record units and missing values

| Section | Provenance and unit | What it does not establish |
|---|---|---|
| `tool_reported` | Original headers and separately labeled tool-defined input/output estimates | API usage, invoices, or commensurate input/output estimators |
| `measured_local` | UTF-8 bytes and pinned `o200k_base` tokens, before/after | Role/tool framing, provider tokenization, cache billing or native quality |
| `reductions` | Calculated before-minus-after, with each original denominator retained | Achievable savings in a live trajectory |
| `deletion_reference` | Hypothetical candidate deletion followed by whole-message retokenization | A validated attainable or end-to-end cost upper bound |
| `patterns` | Regex counts and exact line-multiset comparison, labeled classification | The compressor's internal algorithm or semantic safety |
| `measured_billed` | `not_measured`; all usage and cost fields are null | A measured zero bill |
| `judge` | `not_run`; score is null | Native success, failure or quality equivalence |

Whole-message token deltas are computed by retokenizing each full message after
replacement, never by subtracting isolated span-token counts. Standalone candidate
token counts are also retained but have a different boundary. Summed occurrences
include retransmissions and use a summed byte/token denominator, not a mean of task percentages.
Pattern diagnostics exclude squeez metadata lines; byte/token measurements do not.

`not_applicable` is used for a no-op tool display, `not_reported` when squeez has
no header, and `not_measured` for unavailable provider usage. Every JSONL row has
its provenance; synthetic input is labeled `input_kind=synthetic_fixture` even
when a real executable processes it. Raw text stays in separate private artifacts.

Temperature zero and reasoning effort none are settings to preserve, not proof
of determinism or lossless observations. Native output may already have been
elided before the historical request was saved. Squeez metadata includes elapsed
time and session-dependent content; do not promise bitwise-stable tool stdout.

## Failure and verification commands

| Failure | Action |
|---|---|
| Missing/wrong commit or dirty source | Select the intended full SHA and use its clean checkout; do not invent provenance |
| Missing tokenizer/input/binary or wrong hash/version | Prepare the named local resource, then run `--check`; no automatic tool/version substitution |
| Protection, timeout, UTF-8 or subprocess failure | Inspect private `failure.json`, per-span `stderr.txt` and snapshots; do not consume partial results |

`run.py static` returns 0 on successful completion/verification and 2 on a
preflight, integrity or execution failure. A directory without a completion record
or with `failure.json` is invalid. Native-runner exit codes are documented separately.
Interrupt recovery/resume is not implemented. Private original/replacement text
and recovery stores must not be force-added to Git.

```bash
uv run --locked python run.py static --check --source-commit "$SOURCE_COMMIT" ledgers/static.toml
uv run --locked python run.py static --verify runs/<run-id>
uv run --locked python -m src.compare runs/<none-run-id> runs/<squeez-run-id> \
  --source-commit "$SOURCE_COMMIT" --output _work/static-comparison
```

The historical input root is private. The public aggregate chart can be regenerated
without it, but that does not independently reproduce classification from the raw requests.
