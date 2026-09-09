# prompt-compression-billing-bench

> Draft. A first-execution laboratory, not a finished compression framework.

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

[Machine-readable evidence](evidence/local-baseline.json) is the source of these values.

<!-- repeat-result -->
One unchanged repeat took **371.99 seconds** and ended with **AgentTimeoutError**
(execution `error`, native checks **5/6**).
<!-- /repeat-result -->

Both measurements used cached images, model and dependencies on the same Linux
8-vCPU / 32-GiB VM. The ledger, execution source, model manifest and runtime versions
matched. **This is not a slow first download followed by a fast run.**
The five-minute target is **not met**. [Timing breakdown and task choice](STATUS.md#unchanged-repeat-and-timing)
and [repeat evidence](evidence/local-baseline-repeat.json) retain the unsuccessful result.
Earlier development failures are also preserved, not replaced with an oracle or mock response.

## Quickstart: real local model, no cloud account

Prerequisites: Linux x86_64, a working Docker daemon, `git`, and `uv`.
The measured host had 8 vCPUs and 32 GiB RAM; this is not a verified minimum.
Docker and uv installation are not included. The command installs the locked Python
dependencies, fetches only the selected task, starts Ollama, downloads the pinned
model if missing, runs the task, grades it, and stops its model container.
First setup needs internet access to GitHub, package repositories and image/model registries.

```bash
uv run --locked python run.py ledger.toml
```

Change `repetitions` in `ledger.toml` for a later repeated experiment. There is no
second settings file to override it. Model, versions, retry policy, API-cost ceiling,
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
uv run --locked python run.py --check ledger.toml
uv run --locked python run.py --verify runs/<run-id>
```

Exit codes: `0` meets the ledger's native reward contract; `1` is a completed task
outside that contract; `2` is a preflight/integrity failure; `3` is an execution error.
For a missing Docker dependency, use `--check`; for download/model-pin failures,
read `summary.json` and its phase log; for HTTP/usage errors, read `attempts.jsonl`.
Interrupted-command recovery and resume are not implemented.

This demonstrates that a ledger-to-native-verdict run can pass, not that it always passes.
It **does not prove** cloud billing, compression savings, repeated-run stability,
or broader benchmark performance.
There is no compression implementation, second benchmark, or general benchmark adapter.
The zero API-spending figure excludes hardware, electricity and VM charges.
Raw runs may contain generated private keys and full prompts: do not publish them.
Only allowlisted measurements in `evidence/` are intended for sharing; see [data grades](STATUS.md#data-grades).
