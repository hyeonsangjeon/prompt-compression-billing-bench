# Draft — first-execution status

The accepted ledger uses Terminal-Bench 2.1 `openssl-selfsigned-cert`, Harbor 0.22.0,
Ollama 0.33.3 and `qwen3.5:4b`. The task commit, task image, server image and model
manifest are pinned. Intervention is `none`, repetitions are `1`, and grading is native.
The tokenizer identity is `unverified`; recorded usage is explicitly local, not billed.

## What actually ran

These are development attempts, not a model comparison or a repeated-condition study.
Changing the model or fixing transport settings produces a new ledger/source hash.

| Attempt | Measured outcome | Whole command |
|---|---|---|
| `qwen2.5-coder:3b` | Native reward 0, four of six checks passed; 12 real model calls | 446.71 s, cold setup included |
| `qwen2.5-coder:7b` | Agent timeout; three provider responses preserved; not accepted | 383.57 s; images cached, this model downloaded |
| `qwen3.5:4b`, before the settings fix | Native reward 1 but execution timed out; not accepted | 385.87 s; images cached, this model downloaded |
| Current ledger and transport | Execution passed, native reward 1, six of six checks passed; 7 real model calls | 333.82 s, dependencies/images/model cached |

The accepted run is `20260909T040048Z-ff7200bb`.
Its input/output counts are 22,733 / 2,175, with HTTP 429 = 0 and retries = 0.
Raw records are in the ignored `runs/` directories. Sanitized records for **all four**
attempts are in `evidence/`.

Two failures shaped the minimum implementation:

- A CLI spelling of reasoning effort `none` did not reach the model as intended.
  It now travels as a JSON field, and the proxy refuses a request whose model,
  output limit, temperature or reasoning setting differs from the ledger.
- A native timeout can disconnect while the local model is still finishing.
  The proxy now drains bounded in-flight requests before aggregation and records
  downstream disconnects. Late provider usage is not silently discarded.

HTTP attempts have distinct `run_id`, `repetition`, `call_id`, `attempt_id`,
`attempt_number`, `http_status` and `is_retry`. Provider attempts use `kind: measured`
and `source: ollama_response`; aggregate totals use `kind: calculated`.
Only unique successful attempts with valid provider usage enter token totals.
Failed attempts retain their raw response and usage, if present, without entering
successful-token totals. Retries cannot acquire a fresh budget from an outer SDK retry.

## repo-readiness

| Item | Current status | Evidence or remaining boundary |
|---|---|---|
| 1. Real accountless execution within five minutes | **Not met** | Real local model and native grading work, but the cached successful command took 333.82 s. The first cold command took 446.71 s and failed. No cold five-minute claim. |
| 2. One execution ledger | **Pass for current scope** | Model/task/version/digests, repetitions, retry/cost/time boundaries and outputs are in `ledger.toml`; each run preserves a copy and hash. |
| 3. Records carry provenance | **Pass** | Provider payloads, calculated aggregates, run/call/attempt IDs, HTTP failures and retries are separate. Raw request/response hashes and a source snapshot are retained. |
| 4. Bidirectional drift protection | **Partial** | Tests reject both inflated and reduced counters, altered rewards, duplicate attempts and changed raw hashes. README numbers must match the evidence-derived text. Remote CI has not run, and empirical variability bounds require the later repeated experiment. |
| 5. Unsuccessful cases and limits are visible | **Pass** | Failure and timeout records remain alongside success. Local token counts do not establish cloud billing or compression benefit. |
| 6. Layered README | **Minimal draft** | Purpose, one measured result, real command and boundaries exist. No finished framework documentation, badges or performance promises. |
| 7. No repository-specific jargon needed | **Pass for current scope** | Uses Terminal-Bench, native reward, provider attempt and repetitions; field meanings are described here. |
| 8. Visible failure paths | **Partial** | Dependency, model-pin, HTTP/usage, budget, native-verifier and integrity failures have records/exit codes. A dedicated interrupt/resume workflow is not implemented. |
| 9. Publication grades | **Pass for current files** | Private raw data is ignored. `evidence.py` exports only allowlisted fields and rejects unclassified tracked or untracked files. No raw prompts, generated keys or endpoints are in the public evidence. |

## Data grades

| Grade | Paths | Rule |
|---|---|---|
| Source/configuration | `run.py`, `accounting.py`, `evidence.py`, `ledger.toml`, dependency lock, tests, workflow and draft docs | Eligible source files are enumerated in `evidence.py`; credentials have no values in the ledger. |
| Sanitized measured evidence | The explicitly listed `evidence/*.json` files | Allowlisted numeric records and identifiers, provider usage, native test status, original artifact hashes. No request/response bodies or local endpoints. |
| Private raw | `runs/` | Ledger/source snapshots, raw prompts/responses, native logs and possible generated private keys. Never publish automatically. |
| Private/local cache | `.cache/`, `.venv/`, `.env` | Third-party task checkout, downloaded weights, environments and any local credentials; ignored. |

```bash
python -m unittest discover -s tests -v
python evidence.py check evidence/local-baseline.json
python evidence.py audit-files .
```

The test suite's synthetic HTTP fixtures test transport accounting only.
They are not selectable model providers, benchmark results, or the accountless path.
Public evidence checks establish internal consistency, not a signed provider invoice.

## Deliberately absent

No second benchmark, compressor, cross-benchmark abstraction, paid-provider integration,
automatic publication, experiment scheduler, or finished README.
The implementation is still local; a successful recorded run is not publication approval.
