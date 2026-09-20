# Cache reuse count execution contract

This path isolates cache reuse count from compression. It does not replace the
existing native comparison and does not change that path's template concurrency
of eight. A private cache-reuse native ledger must explicitly set concurrency to
one; any other value stops before provider dispatch.

## Fixed design

One useful bundle is the fixed five-task native execution and grading unit. Each
cache cycle contains six cells: `{none, squeez} × {0, 1, 2}`. Within a condition,
reuse runs in `0 → 1 → 2` order. Odd cycles run `none → squeez`; even cycles run
`squeez → none`. Reuse contrasts hold the condition fixed, and compression
contrasts hold reuse fixed. Diagonal contrasts are rejected.

All three bundles are useful trials; there is no discarded warm-up. A warm
bundle is admissible only when its successful eligible predecessor count equals
its declared reuse level. The source/model/deployment/revision, generation,
task/input/tool/schema hashes, request-prefix hash, namespace evidence, and
request width must stay equal. Temperature zero and effort none are recorded
settings, not evidence of determinism. Cache mode does not add a completion-token
cap that the native transport does not enforce.

## Zero-network planning and doctor

The committed templates are intentionally `no_go` and contain environment names
and booleans, not endpoint or credential values.

```bash
python run.py cache-reuse --plan --cycles 10 \
  --output "$CACHE_REUSE_PLAN"

python run.py cache-reuse \
  --runtime-facts "$CACHE_RUNTIME_FACTS" \
  --native-ledger "$NATIVE_CACHE_LEDGER" \
  --doctor --output "$CACHE_REUSE_DOCTOR"
```

Planning performs zero network calls. The doctor checks dependencies first and
reports only variable names and presence booleans. Exit `0` means every offline
and runtime fact is verified, `3` means a valid `no_go`, and `2` means malformed
input or an integrity failure. A missing `FOUNDRY_ENDPOINT` in one process is
only a process-local fact, not proof that no deployment access exists elsewhere.
The cache and native ledgers must also agree on model revision, endpoint variable,
generation settings, and the hash-bound fixed price schedule. Both ledgers must
carry their own current execution approval.

The 14 required facts cover endpoint presence, managed-identity permission,
deployment/model/API access, effective retention, native cache fields,
namespace/isolation, matching external traffic, queue/RPM/TPM facts, the exact
serialized-prefix contract, fixed prices, task and squeez assets, no-progress
binding, concurrency one, and a separate current leader approval. Evidence is
bound by hashes; values and private paths are not stored in this public template.

## Later live cycle

Only after the doctor returns `go` and a leader separately approves that sealed
record may a runtime owner execute one no-clobber cycle:

```bash
python run.py cache-reuse "$CACHE_REUSE_LEDGER" \
  --runtime-facts "$CACHE_RUNTIME_FACTS" \
  --native-ledger "$NATIVE_CACHE_LEDGER" \
  --source-commit "$SOURCE_COMMIT" \
  --run-id "$NEW_RUN_ID" \
  --execute-cycle 1
```

The command verifies the clean source commit, reserves a new output root, runs
the six cells serially, preserves every useful native verdict, and records task,
run, request, and cache-cycle denominators. Invalid bundles and their technical
attempt costs remain red. The execution cycle ID includes the run ID hash, so a
replacement under a new run ID cannot reuse the failed cycle ID. Output is
derived as `runs/cache-reuse/<run-id>/<cycle-id>`; a caller-supplied path is
accepted only when it is exactly that path. The exact admitted cache ledger,
runtime facts, and native ledger bytes are preserved under the run and their
hashes travel with every observation. HTTP 429 and
transport errors are not cache misses, and the existing bounded transport retry
contract is the only retry path.

Common failures:

| Exit or record | Meaning | Check |
|---|---|---|
| `3`, doctor `no_go` | At least one required fact is not currently verified | Inspect `doctor.json`; do not inspect or print credential values |
| `2`, `Cache-reuse preflight failed` | Ledger, source, prefix, namespace, or no-clobber contract failed | Re-run `--plan` and `--doctor` against the exact private inputs |
| `failure.json`, `invalid_preserved` | A started cycle had missing usage, prefix/request-width drift, native failure, or another integrity stop | Preserve it and use a new cycle ID only after the cause is resolved |

## Units and claim limit

The primary cache metric is summed provider-native cached input divided by
summed provider-native input per useful bundle. Input cost is calculated from
those fields and fixed ledger prices. Provider usage, local tokenizer counts,
calculated prices, and invoices remain separate. Absent, null, or malformed
cached-input values are missing; only numeric zero is zero. Reuse zero has no
eligible predecessor opportunity, which is `not_applicable`, not a cache miss.

Ten valid cycles are split 1–5 and 6–10. Each paired cache-share and input-cost
series is stable only when the two observed ranges overlap and median signs
match. Otherwise the predeclared rule extends once to 20 valid cycles and compares
1–10 with 11–20. Continued width stops as `same_condition_width_excess`.
Native quality still uses its separate D3 rule. Aggregation rejects duplicate or
out-of-order cycle/run IDs, mixed source or ledger hashes, and mixed
model/deployment/isolation pins. A 20-cycle verdict is invalid unless the first
10-cycle boundary required the declared extension.

The fixture and unit tests use synthetic requests and fake responses with zero
network calls. They prove ordering, fail-closed parsing, provenance, and verdict
logic. They do **not** prove a provider cache hit, current access, a price, an
invoice saving, model quality, determinism, or a general provider effect.
