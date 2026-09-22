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
task/input/tool/schema hashes, same-task request-prefix hash, cycle-isolation evidence, and
request width must stay equal. Temperature zero and effort none are recorded
settings, not evidence of determinism. Cache mode does not add a completion-token
cap that the native transport does not enforce.

The current private runtime facts must also carry a versioned structural
eligibility decision. It binds two zero-call captures for request ordinals one
and two for every fixed task. Each row stores only the stable serialized-prefix
byte boundary, capture hashes, and local content-token diagnostics. The provider
threshold is 1,024 tokens. The fixed screening counts are 1,050 for
`log-summary-date-ranges`, 1,155 for `multi-source-data-merger`, and 1,134 for
`nginx-request-logging`; these three tasks form the primary eligible stratum.
The counts are 828 for `cancel-async-tasks` and 1,016 for
`openssl-selfsigned-cert`; their cache result is `not_applicable`.

All five tasks remain in every execution bundle. Provider usage, calculated
total cost, native quality, and negative-control reporting use the complete
five-task bundle. Cache-effect contrasts use only the three eligible tasks.
The eligibility decision was made after local structural screening and before
provider inference, so it favors cache-capable inputs and limits external
validity. Local screening-token counts are not billed provider usage and do not
show that a provider cache hit occurred.

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

### Sanctioned runtime context

`config/cache-runtime-context.json` defines the project-owned doctor launcher.
Its command uses only the inherited `CACHE_RUNTIME_PYTHON` executable and the
fixed `src.cache_runtime_context` module. Ledger, runtime-fact, native-ledger,
attestation, and output locations are supplied through the named environment
inputs `CACHE_REUSE_LEDGER`, `CACHE_RUNTIME_FACTS`, `NATIVE_CACHE_LEDGER`,
`CACHE_RUNTIME_CONTEXT_ATTESTATION`, and `CACHE_REUSE_DOCTOR`; none is accepted
as an inline command argument.

```bash
"$CACHE_RUNTIME_PYTHON" -m src.cache_runtime_context
```

The launcher checks its tracked regular-file SHA-256 against the public
definition, then requires a fresh runtime-owner attestation that repeats the
five `SANCTIONED_PROJECT_RUNTIME_CONTEXT_*` bindings and the definition hash.
Only then does it read the three private admission inputs and invoke the
existing doctor once. Its no-clobber result is mode `0600` and contains only
environment names, presence booleans, UTC times, byte counts, SHA-256 values,
and the doctor's sanitized result. The committed attestation fixture is
deliberately expired and cannot open the gate.

The [runtime-owner handoff guide](runtime-owner-handoff.md) lists every
canonical input name and the exact attestation field contract. It is a source
contract, not evidence that any current runtime input is present or valid.

This launcher does not create, discover, or authorize a runtime. Adding it to
source closes the reusable command-and-identity gap only. A runtime owner must
still deploy the command inside the actual sanctioned process and provide a
fresh private attestation and current evidence. A verified launcher does not by
itself establish managed-identity permission, model/API access, retention,
cache-field support, prices, namespace isolation, or any live provider result.

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
| `3`, context `missing`, `stale`, or `wrong_source` | The sanctioned launcher identity or current runtime-owner attestation is absent or invalid | Supply a fresh matching private attestation in the actual project runtime; do not copy environment values into arguments |
| `3`, doctor `no_go` | At least one required fact is not currently verified | Inspect `doctor.json`; do not inspect or print credential values |
| `2`, `Cache-reuse preflight failed` | Ledger, source, prefix, namespace, or no-clobber contract failed | Re-run `--plan` and `--doctor` against the exact private inputs |
| `failure.json`, `invalid_preserved` | A started cycle had missing usage, prefix/request-width drift, native failure, or another integrity stop | Preserve it and use a new cycle ID only after the cause is resolved |

## Units and claim limit

For the three-task eligible stratum, the primary cache metric is summed
provider-native cached input divided by summed provider-native input per useful
bundle. Input cost is calculated from those fields and fixed ledger prices. A
separate five-task descriptive record carries provider usage, calculated total
cost, and quality without treating it as a five-task cache-effect estimate.
Provider usage, local tokenizer counts, calculated prices, and invoices remain
separate. Absent, null, or malformed cached-input values are missing; only
numeric zero is zero. Reuse zero has no eligible predecessor opportunity. The
two structurally ineligible tasks also have no cache opportunity or result;
both cases are `not_applicable`, not cache misses or numeric zeros.

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
