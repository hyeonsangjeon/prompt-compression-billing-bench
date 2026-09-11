# Optional native local-model runner

> Historical native evidence and the separate accountless execution path. This is not the static compressor comparison.

The recorded measurements below predate the current root commit and the static
adapters. Their sanitized records lack `source_commit`; do not attribute them to
the new code or backfill a SHA. No new native execution is claimed here.

Run one pinned Terminal-Bench task from one ledger, retaining every model attempt,
HTTP status, retry, provider-reported token count, and native verdict.
The current path uses real local Ollama inference. **Its token counts are not billable tokens.**

## First result

Task: Terminal-Bench 2.1 `openssl-selfsigned-cert`.

<!-- measured-result -->
Recorded 2026-09-09: `qwen3.5:4b`, 1 repetition, no added compression.
Native checks: **6/6**; execution: **passed**.
Local provider tokens: **22,733 input / 2,175 output**; responses: **7**.
HTTP 429: **0**; retries: **0**.
Whole command: **333.82 seconds**.
<!-- /measured-result -->

[Machine-readable evidence](../evidence/local-baseline.json) is the source of these values.

<!-- repeat-result -->
One unchanged repeat took **371.99 seconds** and ended with **AgentTimeoutError**
(execution `error`, native checks **5/6**).
<!-- /repeat-result -->

Both measurements used cached images, model and dependencies on the same Linux
8-vCPU / 32-GiB VM. The ledger, execution source, model manifest and runtime versions
matched. **This is not a slow first download followed by a fast run.**
The five-minute target is **not met**. [Timing breakdown](#unchanged-repeat-timing)
and [repeat evidence](../evidence/local-baseline-repeat.json) retain the unsuccessful result.
Earlier development failures are also preserved, not replaced with an oracle or mock response.

## Quickstart: real local model, no cloud account

Prerequisites: Linux x86_64, a working Docker daemon, `git`, and `uv`.
The measured host had 8 vCPUs and 32 GiB RAM; this is not a verified minimum.
Docker and uv installation are not included. The command installs the locked Python
dependencies, fetches only the selected task, starts Ollama, downloads the pinned
model if missing, runs the task, grades it, and stops its model container.
First setup needs internet access to GitHub, package repositories and image/model registries.
In a clone containing the reviewed execution commit, replace the placeholder with its full SHA:

```bash
SOURCE_COMMIT='<full-40-character-execution-approved-SHA>'
git checkout --detach "$SOURCE_COMMIT"
uv run --locked --extra native python run.py --source-commit "$SOURCE_COMMIT" ledger.toml
```

Change `repetitions` in `ledger.toml` for a later repeated experiment. There is no
second settings file to override it. Commit code and ledger changes, then select a
new execution SHA before running; do not modify the execution checkout.
Model, versions, retry policy, API-cost ceiling,
time limits, native reward bounds and output directory are all in that ledger.
The credential-name list is empty because this first path needs no credentials.
Paid endpoints are rejected rather than silently using the zero-cost local setting.

## Results and boundaries

Each invocation writes a new `runs/<run-id>/`: the ledger and source snapshots,
`repetition-*/attempts.jsonl`, paired raw requests/responses, `summary.json`,
and Harbor's `native/` results, trajectory and verifier logs.
The native `reward` and execution `status` are separate: a timeout is not a successful run
even if its partially completed work passes the tests.

```bash
uv run --locked --extra native python run.py --check --source-commit "$SOURCE_COMMIT" ledger.toml
uv run --locked --extra native python run.py --verify runs/<run-id>
```

`--source-commit` is mandatory for execution and `--check`: the full SHA must match
checkout HEAD, with no staged/unstaged changes or non-ignored untracked files. Before Docker preflight,
the runner compares its four source files (including `uv.lock`) and the selected
ledger with Git blobs at that commit. The ledger must be committed inside the same
checkout. Ignored run/cache files are allowed; execution inputs must still match the
commit byte for byte.

`summary.json` records `source_commit`, the repository-relative `ledger_source_path`,
and hashes of the captured bytes. Verification checks the complete source snapshot,
aggregate hash and ledger against the **recorded commit**, not today's HEAD. That
commit and its blobs must be available in the verifying clone; verification does not
run `fetch` or change the checkout. Add `--source-commit "$SOURCE_COMMIT"` to
`--verify` to also check an independently designated SHA. This verifies local source
identity, not approval or presence on GitHub; those remain deployment checks.

New sanitized evidence exports retain `source_commit`. Historical evidence without
it remains readable by `evidence.py check`, which checks the sanitized records, not
Git provenance. Raw runs without a recorded SHA cannot pass the new `--verify` or be
re-exported as commit-verified runs. Do not backfill their SHA from current HEAD.

Exit codes: `0` meets the ledger's native reward contract; `1` is a completed task
outside that contract; `2` is a preflight/integrity failure; `3` is an execution error.
For a missing Docker dependency, use `--check`; for download/model-pin failures,
read `summary.json` and its phase log; for HTTP/usage errors, read `attempts.jsonl`.
Interrupted-command recovery and resume are not implemented.

This demonstrates that a ledger-to-native-verdict run can pass, not that it always passes.
It **does not prove** cloud billing, compression savings, repeated-run stability,
or broader benchmark performance.
This native path has no compression integration, second benchmark, or general benchmark adapter.
The static adapters are deliberately not presented as live Harbor integration.
The zero API-spending figure excludes hardware, electricity and VM charges.
Raw runs may contain generated private keys and full prompts: do not publish them.
Only allowlisted measurements in `evidence/` are intended for sharing; see [data grades](publication.md).

## Unchanged repeat timing

This table preserves the existing historical measurements, not a new execution.

<!-- measured-timing -->
| Phase (seconds) | Earlier accepted run | One unchanged repeat |
|---|---:|---:|
| Image availability checks / cached pulls | 1.18 | 1.23 |
| Ollama container start | 0.57 | 0.77 |
| Model pull / cached-model check | 0.29 | 0.78 |
| Task environment start | 1.38 | 1.55 |
| Agent setup | 9.95 | 11.10 |
| Agent execution | 298.62 | 300.00 |
| Native verifier | 5.77 | 6.93 |
| Other startup, response drain and cleanup (remainder) | 16.06 | 49.64 |
| **Whole command** | **333.82** | **371.99** |
<!-- /measured-timing -->
