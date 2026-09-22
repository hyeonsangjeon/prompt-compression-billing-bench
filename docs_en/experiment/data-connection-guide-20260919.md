# Live-Data Connection Guide

Follow this sequence when KT runs one real task in its own environment without placing
source data in the public repository. A **no-call preflight** checks configuration and file
connections without calling an external model provider. The **result JSON** stores
execution state, usage, judgment, and file fingerprints in machine-readable form. A
**JSON Schema** defines required fields and value formats.

## 30-Second Summary

1. Do not move source data, endpoints, credentials, or internal paths outside the customer environment.
2. Public execution YAML contains only environment-variable names, a fixed benchmark task ID, and a JSON output name under `runs/`.
3. Run the default no-call preflight first. `status=checked` means the connection contract was checked, not that quality passed.
4. Add `--execute` only after an approved operator has prepared environment variables and a private execution ledger.
5. After execution, validate the JSON against the result schema and read technical completion separately from quality. `technical_incomplete` is not a wrong answer.

This documentation work made no model or provider call. It describes only the public
[one-task YAML](../../examples/experiment/benchmark.yaml), existing
[connection code](../../src/benchmark_run.py), existing
[single-task runner](../../src/screening_run.py), and
[result schema](../../schemas/experiment-result.schema.json).

## Supported Scope

The current public path is not a generic runner for arbitrary customer-data formats. It
runs one task from the public index at a pinned Terminal-Bench 2.1 revision using a
KT-managed private benchmark checkout and execution environment.

- **Supported:** Connect a supported benchmark checkout, private execution inventory and
  file hashes, and provider settings inside the customer environment without copying them
  into the public repository.
- **Unsupported:** Run a customer-specific document or new task merely by naming it in
  YAML. A task absent from the public index is rejected during no-call preflight.
- **Requires separate review:** Connecting customer-specific data as a new task first
  requires design and validation of an input adapter, judge, and ledger contract. This
  guide does not assume those capabilities exist.

The first connection succeeds when one pinned real benchmark task runs under the contract
inside the customer environment and its result JSON validates. One result does not decide
product adoption, a compression effect, or general quality.

## Values KT Supplies and Values the Repository Fixes

### Values Supplied Only in the Customer Environment

The table lists environment-variable names, not values. Actual addresses, access-granting
credentials, organizational tenant values, and personal paths remain in a secret manager
or execution environment. Do not paste them into documentation, YAML, issues, or result
descriptions.

| Environment-variable name | Role | Publication |
| --- | --- | --- |
| `FOUNDRY_ENDPOINT` | KT-approved model endpoint | Value remains private |
| `SCREENING_OPERATIONAL_LEDGER` | Path to private execution ledger containing approvals | File and path remain private |
| `TERMINAL_BENCH_ROOT` | Benchmark checkout at the pinned revision | Source and path remain private |
| `SCREENING_INVENTORY` | Path to hash-calculated execution inventory | Source and path remain private |
| `FOUNDRY_QUEUE_STATE` | Queue-state path coordinating use of the same deployment | Value remains private |
| `PROVIDER_RPM_LIMIT`, `PROVIDER_TPM_LIMIT` | Provider-permitted throughput | Values remain private |
| `TIKTOKEN_CACHE_DIR` | Data path for the pinned tokenizer | Value remains private |
| `NATIVE_BLOB_ACCOUNT_URL`, `NATIVE_BLOB_SPOOL_ROOT` | Storage and retrieval locations for private execution evidence | Values remain private |

Authentication is supplied through a KT-approved platform identity or secret-management
procedure. Do not store keys or tokens in YAML or execution ledgers.

In public YAML, KT may select a task ID from the public index and a result JSON name under
`runs/`. YAML selecting another task must also be committed in a KT private fork or
approved source branch and run from a clean `HEAD`.

### Values Fixed and Validated by the Repository

| Item | Fixed content | Where to check |
| --- | --- | --- |
| Benchmark | Terminal-Bench 2.1 name, revision, and public task index | [Public reference ledger](../../ledgers/screening.template.toml) |
| Model settings | `gpt-5.4`, reported revision, `temperature=0`, reasoning setting | Public reference ledger |
| Condition | `none`, the reference without additional compression | Public reference ledger and YAML |
| Execution path | `src.screening_run --diagnose-task` | `resolved_contract.runner` in result JSON |
| Protection contract | Replay bundle, complete evidence retention, and retry settings | Public reference ledger and result JSON |
| Safety limits | Call, cost, time, request, and output boundaries and unknown-quality stop classification | [Safety policy](execution-safety-policy.md) |
| Result shape | State, usage, cost, quality, completion, and artifact hashes | [Result schema](../../schemas/experiment-result.schema.json) |

The wrapper compares the private execution ledger with the public reference ledger. Only
inventory-file fingerprints, provider-limit and deployment-isolation evidence, approval
fields, per-attempt and full-run cost limits, and the UTC deadline may differ in the
private ledger. Changing the model, condition, runner, judgment rules, fixed call, time,
or size boundaries, or retry behavior is rejected before execution.

## 1. Prepare Source Data Outside the Repository

A **file fingerprint (SHA-256 hash)** is a 64-character value used to compare file
contents. It can verify that the same file was used without publishing the source, but the
hash itself remains private until customer review.

1. Place the benchmark checkout at the pinned revision and its inventory in a private location outside the repository.
2. Calculate the inventory file's SHA-256.
3. Copy the public reference ledger outside the repository as a private execution ledger.
4. Fill only the permitted fields below and retain hash records for the source inventory and execution ledger.

```bash
sha256sum '<private-inventory-file>'
cp ledgers/screening.template.toml '<private-directory>/screening.operational.toml'
sha256sum '<private-directory>/screening.operational.toml'
```

Only these private-ledger fields are filled:

| section.field | Content |
| --- | --- |
| `benchmark.inventory_sha256` | Inventory SHA-256 calculated above |
| `queue.limits_source_reference` | Private evidence reference for provider limits |
| `queue.deployment_isolation_reference` | Private evidence reference for shared-deployment coordination |
| `approval.preregistered` | Whether the plan was approved before execution |
| `approval.execution_authorized` | Whether actual paid execution is approved |
| `approval.cost_limits_approved` | Whether the cost limits and deadline below are approved |
| `approval.reference` | Approval-record reference |
| `limits.max_api_cost_usd_per_attempt` | Calculated API cost allowed for one actual task attempt |
| `limits.max_api_cost_usd_per_run` | Calculated API cost allowed across this new run |
| `limits.run_deadline_utc` | Future UTC execution deadline |

Do not place raw input, prompts, endpoint values, credentials, tenant values, or internal
paths in this file either. Inject the values corresponding to the environment-variable
names above at execution time.

## 2. Review the One-Task YAML

The [public example](../../examples/experiment/benchmark.yaml) points to one real task in
the pinned benchmark; it is not synthetic input.

```yaml
schema_version: 2
experiment: native
endpoint_env: FOUNDRY_ENDPOINT
benchmark:
  name: terminal-bench-2.1
  revision: 7131e4375048a0e408a8fb404b5f499d726b695b
  task: cancel-async-tasks
model: gpt-5.4
condition: none
output: runs/readme-benchmark-result.json
```

The YAML contains only the endpoint's **environment-variable name**, not its address. It
also contains no source-data path. Start with this file unchanged. To select another
supported task, change only `benchmark.task` and a nonconflicting `runs/` JSON name,
then commit the YAML in KT's private fork or approved source branch. The runner confirms
that the source checkout is clean, including untracked files.

## 3. Check Without Calling a Model

Run in a clean committed checkout with Python 3.12 or later and `uv`.

```bash
uv sync --locked
uv run --locked python run.py experiment examples/experiment/benchmark.yaml
uv run --locked python run.py experiment \
  --verify-result runs/readme-benchmark-result.json
```

The first command checks YAML, the current Git commit, public reference ledger, task index,
and result contract. Without `--execute`, it makes no provider call. The second command
checks the generated JSON against the [result schema](../../schemas/experiment-result.schema.json).

A successful no-call preflight produces:

```text
status = checked
outcome = preflight_passed
labels.measured = false
provider_usage.status = not_measured
quality.status = not_measured
completion.technical_status = not_run
```

`checked` means pre-execution connections satisfy the contract. No model answer, quality,
or cost has been measured. Passing the schema checks JSON shape, not truthfulness or
billing.

The current clean-checkout validation scope for the no-call path is recorded in
[validation evidence](../../data/experiment/readme-benchmark-validation-20260920.json).
That record also excludes actual provider execution.

## 4. Execute Only After Approval

Before execution, the operator checks:

- Environment-variable values and platform identity are injected only into the execution session.
- The private execution ledger changes only the permitted fields above.
- Inventory SHA-256 matches the actual file.
- Provider throughput limits, shared-deployment coordination, and paid-execution approval are recorded.
- Per-attempt and full-run calculated API cost limits and a future UTC deadline are approved.
- Source and execution artifacts remain within the customer-managed boundary.

The public reference ledger fixes schema version 4 call, time, request, and output
boundaries, while intentionally leaving the cost limits and UTC deadline blank. Provider
execution fails before a call unless all three values and
`cost_limits_approved=true` appear together in the private ledger. Exact values and stop
classifications follow the [safety policy](execution-safety-policy.md).

Only when all values and approvals are ready, run:

```bash
uv sync --locked --extra native
uv run --locked python run.py experiment \
  examples/experiment/benchmark.yaml --execute
```

`--execute` revalidates the private execution ledger, then passes one task to the existing
`screening_run --diagnose-task`. It does not create a new runner or bypass. This
documentation work did not run that command.

## 5. Validate Result JSON and Read the Judgment

Use the same validation command whether execution finishes or stops technically:

```bash
uv run --locked python run.py experiment \
  --verify-result runs/readme-benchmark-result.json
```

| State combination | Plain meaning | Counts as quality? |
| --- | --- | --- |
| `checked` + `preflight_passed` | No-call preflight only | No |
| `completed` + `measurement_completed` + `quality.status=pass` | Technical execution and grading completed and passed | Yes, only for this one run |
| `completed` + `measurement_completed` + `quality.status=wrong_answer` | Technical execution and grading completed; answer was wrong | Yes, one wrong answer |
| `completed` + `measurement_completed` + `quality.status=wrong_format` | Technical execution and grading completed; format was wrong | Yes, one format failure |
| `failed` + `technical_incomplete` | Execution or evidence collection did not finish | No; do not convert to a wrong answer |

`quality.status=unknown` and `not_measured` also indicate unknown quality. Do not convert
technical incompletion to a wrong answer or unobserved usage to zero.
`completion.operator_status=stopped` records an operator stop and is independent of a
quality judgment.

One `pass` or `wrong_answer` describes only that task and execution.
`temperature=0` does not guarantee identical answers, and one run cannot establish
cross-condition ranking or non-inferiority.

## 6. Preserve the Required Hashes

| Record | Bound content | Location |
| --- | --- | --- |
| `lineage.source_commit` | Public source commit executed | Result JSON |
| `lineage.config_sha256` | Actual one-task YAML | Result JSON |
| `lineage.ledger_sha256` | Public reference ledger | Result JSON |
| `resolved_contract.execution_ledger_sha256` | Approved private execution ledger | Result JSON |
| `lineage.source_sha256` | Input source retained in evidence | Result JSON when available |
| SHA-256 values under `artifacts` | Summary, attempt, provenance, and other outputs | Result JSON |
| Inventory, source, and final-JSON SHA-256 | Customer-retained private files | Customer's private hash record |

Hash the final JSON separately:

```bash
sha256sum runs/readme-benchmark-result.json
```

When transferring a file, compare both byte count and SHA-256. A matching hash proves only
that the file is identical; it does not mean quality passed.

## 7. Keep Four Kinds of Numbers Separate

| Value | What it measures | Boundary |
| --- | --- | --- |
| Local token measurement | Input, output, or actually changed spans counted locally with a fixed tokenizer | Not provider-billed tokens |
| Full API usage | Input, cached-input, and output tokens reported by the provider across all model requests | Not only changed spans |
| Calculated cost | USD calculated from complete API usage and ledger rates | Not an actual invoice |
| Actual invoice | Amount separately billed by the provider | Must be reconciled outside the result JSON |

The public one-task YAML uses `condition=none`, so it has no changed-span reduction from
additional compression. If a compression condition is later compared separately,
**actually changed-span tokens** remain local values for changed strings only, while
`provider_usage` covers every model request in one execution.

Even when `cost.calculated_usd` exists, do not call it a billed amount if
`cost.invoice_reconciled=false`. If `provider_usage.status=requires_review` or a value is
`null`, leave it unresolved.

## 8. Separate Public and Private Outputs

| Material | Default classification | Handling |
| --- | --- | --- |
| Customer source, benchmark checkout, and inventory | Private source | Never place in repository, issue, PR, or public attachment |
| Endpoint, credential, tenant values, and internal paths | Private operating information | Keep within environment and secret-management tools |
| Private execution ledger, queue, and raw evidence | Private execution material | Access-restrict under customer retention policy |
| Results and hash records under `runs/` | Private pending review | Covered by `.gitignore`; never publish automatically |
| Reviewed aggregates and processed documents | Publishable after approval | Remove raw rows and operating values and pass the public allowlist check |

Follow the [publication-scope contract](../publication.md) for classifications and forbidden
paths. Passing the result schema does not grant publication approval. The prohibition on
customer-data egress takes precedence over execution success.

## Common Blockers

| Observed result | First check | Interpretation |
| --- | --- | --- |
| `preflight_error` with dirty-checkout message | Whether execution uses a committed checkout with no modified or untracked files | Stopped before provider call |
| `technical_incomplete` with endpoint-environment-variable message | Whether `FOUNDRY_ENDPOINT` is present in the execution session | Not a quality failure |
| Execution-ledger mismatch | Whether anything outside the six permitted fields changed | Fixed-contract protection stopped execution |
| `provider_usage.status=requires_review` | Unknown-usage attempt and raw evidence | Do not replace with zero |
| `wrong_answer` | Terminal-Bench judgment evidence and verifier revision | Technical execution completed; quality was wrong |
| Result JSON schema failure | Missing field, wrong type, or unknown field | Must be corrected before publication or aggregation |

Do not automatically resend the same error. In particular, if it is unclear whether the
provider processed a request, preserve the raw request identifier, final response, and
usage uncertainty before an operator decides whether to rerun.

## Supported and Unsupported Conclusions

**Observable**

- Which source, YAML, and ledger hashes were used for one pinned task
- Whether provider usage completed and the technical and quality states
- Whether calculated cost exists and whether it was invoice-reconciled

**Possible explanations**

- Differences in usage or cost may reflect request count, cache, model path, and provider behavior together.
- Differences in quality may also reflect model nondeterminism, execution environment, or judging.

**Not established by this procedure alone**

- A causal claim that compression produced a difference
- Generalization to other models, tasks, or customer-specific data
- Compressor ranking, quality non-inferiority, population savings, or actual billed savings

The current path is appropriate for one-run connection validation. A comparative
conclusion first requires a separately fixed experimental design covering adapter and
judge validation, changed axes, repetition count, stopping rules, and invoice
reconciliation.

## Final Pre-Execution Checklist

- [ ] Source data and every operating value remain outside the public repository.
- [ ] Execution source is committed and `git status --porcelain` is empty.
- [ ] The YAML task is in the public index and output is `runs/*.json`.
- [ ] The no-call result validates as `checked` + `preflight_passed`.
- [ ] The private execution ledger fills only the six permitted fields.
- [ ] Provider limits, shared-deployment coordination, and paid-execution approval exist.
- [ ] After `--execute`, validate schema, state, usage, quality, and hashes independently.
- [ ] Before publication, pass the [publication-scope contract](../publication.md) and file allowlist checks.

Related evidence is in the [reproducibility contract](reproducibility-contract.md),
[one-task request schema](../../schemas/benchmark-request.schema.json),
[result schema](../../schemas/experiment-result.schema.json),
[public reference ledger](../../ledgers/screening.template.toml), and
[existing runner](../../src/benchmark_run.py).
