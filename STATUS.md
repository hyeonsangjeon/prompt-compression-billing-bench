# Draft — first-execution status

The accepted ledger uses Terminal-Bench 2.1 `openssl-selfsigned-cert`, Harbor 0.22.0,
Ollama 0.33.3 and `qwen3.5:4b`. The task commit, task image, server image and model
manifest are pinned. Intervention is `none`, repetitions are `1`, and grading is native.
The tokenizer identity is `unverified`; recorded usage is explicitly local, not billed.

## What actually ran

The first four entries are development attempts, not a model comparison or a repeated-condition study.
Changing the model or fixing transport settings produces a new ledger/source hash.

| Attempt | Measured outcome | Whole command |
|---|---|---|
| `qwen2.5-coder:3b` | Native reward 0, four of six checks passed; 12 real model calls | 446.71 s, cold setup included |
| `qwen2.5-coder:7b` | Agent timeout; three provider responses preserved; not accepted | 383.57 s; images cached, this model downloaded |
| `qwen3.5:4b`, before the settings fix | Native reward 1 but execution timed out; not accepted | 385.87 s; images cached, this model downloaded |
| Current ledger and transport | Execution passed, native reward 1, six of six checks passed; 7 real model calls | 333.82 s, dependencies/images/model cached |
| One requested unchanged repeat | Agent timeout at 300 s, native reward 0, five of six checks passed; 7 real model calls | 371.99 s, dependencies/images/model cached |

The accepted run is `20260909T040048Z-ff7200bb`.
Its input/output counts are 22,733 / 2,175, with HTTP 429 = 0 and retries = 0.
Raw records are in the ignored `runs/` directories. Sanitized records for **all five**
attempts are in `evidence/`.

## Unchanged repeat and timing

The requested second run is `20260909T064145Z-21d76464`, recorded on 2026-09-09.
It used the same VM, task, model manifest, ledger hash, execution-source hashes,
Docker version and Harbor version as the 333.82-second run. No Azure resources,
SKU, disk, network or shutdown settings were created or changed for this repeat.
The existing VM was running when checked after an interrupted start request; no
second start request was sent. It was deallocated after the result archive was copied.

Exactly one additional task execution was attempted. It timed out at the unchanged
300-second agent limit. The recorder retained the late provider response after the
native runner disconnected. Execution status is `error`, not a completed successful run.
The native verifier examined the files left at timeout: five of six checks passed;
`test_verification_file` failed. The seven local provider responses reported
22,820 input tokens and 2,426 output tokens, with no HTTP 429 or retries.

The following breakdown is derived from the original runner timers and native
phase timestamps, not from a new profiling workload.

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

The model-pull timers above are cached-model checks, not full weight downloads.
Agent execution includes local inference, terminal commands and their waits; it
is not pure inference time. The remainder is the whole command minus the named
phases and includes startup, response draining and cleanup. Rounded rows can differ
slightly from the total. VM boot and the caller's SSH connection are outside the command timer.

Both runs started a fresh Ollama container and a fresh task container. Reusing the
same VM and files does not control operating-system memory caches, generated
container identifiers, model timing or every source of nondeterminism. Two runs
cannot estimate a stable runtime distribution. The first already spent 298.62 s
in the agent; the repeat is not evidence that the first-download cost caused it.
Do not change the README to promise a faster second run.

## Why six checks, not seven

| | Earlier reconnaissance | This laboratory and its unchanged repeat |
|---|---|---|
| Dataset | Terminal-Bench 4.0.0 | Terminal-Bench 2.1 |
| Task | `session-window-debug` | `openssl-selfsigned-cert` |
| Work | Repair a Python session-window processor | Generate and inspect a self-signed certificate, key, PEM and verification script |
| Native checks | Seven session/merge/garbage-collection/watermark checks | Six directory/key/certificate/PEM/verification-file/script checks |
| Model | Foundry gpt-5.4 | Local Ollama qwen3.5:4b |

The task changed deliberately to keep the first accountless ledger-to-result
path small and use a real, pinned task with modest resources. No test was removed
from `session-window-debug`: the six checks belong to a different official task.
The choice did not achieve the five-minute target. The two task results do not
measure a quality improvement, and the certificate task is not a proxy for the
earlier debugging task. The native task and grader were unchanged between the
333.82-second run and this repeat.

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
| 1. Real accountless execution within five minutes | **Not met** | The cached passing command took 333.82 s; the unchanged repeat took 371.99 s and timed out. The earlier cold development command took 446.71 s and failed. |
| 2. One execution ledger | **Pass** | Within the implemented local-only path, model/task/version/digests, repetitions, retry/cost/time boundaries and outputs are in `ledger.toml`; actual outgoing settings are checked against it. |
| 3. Records carry provenance | **Pass** | Provider payloads, calculated aggregates, run/call/attempt IDs, HTTP failures and retries are separate. Raw request/response hashes and a source snapshot are retained. |
| 4. Bidirectional drift protection | **Not met** | Record-integrity and headline contracts pass in GitHub Actions, in both directions. However, CI does not rerun the live model, and there is no empirically calibrated token/time/outcome variability gate yet. The live repeat changed outcome. |
| 5. Unsuccessful cases and limits are visible | **Pass** | Failure and timeout records remain alongside success. Local token counts do not establish cloud billing or compression benefit. |
| 6. Layered README | **Pass** | The intentional short draft separates purpose, measured results, the real command and limitations. The five-minute timing requirement remains separately unmet. |
| 7. No repository-specific jargon needed | **Pass** | Uses Terminal-Bench, native reward, provider attempt and repetitions; field meanings are described here. |
| 8. Visible failure paths | **Pass** | README provides preflight/integrity commands, exit-code meanings and dependency/download/HTTP/usage/verifier diagnostics. Recovery/resume is absent but is not required merely to make failures visible. |
| 9. Publication grades | **Pass** | Private raw data is ignored. `evidence.py` exports only allowlisted fields and rejects unclassified files. Commit candidates were also scanned for credentials, deployed endpoints and host-specific absolute paths. |

All nine criteria apply to this repository, so none is marked not applicable.
Passing a criterion here is limited to the current one-task local-model scope.

## Pre-push inspection and backup

The first implementation commit is `1b2fb25ef4a9cc324777511ccf5b6565b4bd9821`.
All 17 candidate files and their staged Git blobs were examined before commit/push.
No credential value, deployed service endpoint, cloud resource identifier,
host-specific internal path or absolute host model path was found. The only prior
commit was the empty initial commit; no history from another repository was imported.

Public GitHub/PyPI URLs and pinned Docker/model identifiers remain intentionally.
Loopback addresses are generated locally. The literal `/root/.ollama` is the
official **container-side** volume destination, not a host-specific model path;
the host cache is derived from the checkout's `.cache/`. The transient proxy key
is generated at runtime and is not an embedded credential.

Raw `runs/`, `.cache/`, `.venv/` and `.env` files did not enter the commit.
The repository remains private. Pattern scanning and manual review reduce exposure
risk but are not a proof that arbitrary future data is safe. New evidence/docs must
be inspected again before the next push.

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
The audited implementation and sanitized evidence are backed up to the private remote.
A private push is not public-release approval. Raw runs remain local and on the retained VM disk.
