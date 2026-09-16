# Publication grades

Eligibility is not publication approval. The repository remains private until an
explicit release decision. No command here pushes code or changes visibility.
The exact machine allowlist is `PUBLIC_FILES` in `evidence.py`; unknown files fail
the audit, including force-added ignored material.

## Public-source candidates in this layout

| Grade | Exact files | Contents |
|---|---|---|
| Source/configuration | `.gitignore`, `.python-version`, `pyproject.toml`, `uv.lock`, `.github/workflows/check.yml` | Ignore boundaries, Python/dependency pins and non-model CI |
| Source/configuration | `run.py`, `accounting.py`, `evidence.py`, `ledger.toml` | Static dispatch; separate legacy native runner, usage accounting and strict evidence audit |
| Source/configuration | `src/__init__.py`, `src/compressors.py`, `src/pipeline.py`, `src/protection.py` | Shared none/squeez/Headroom/LLMLingua adapter interfaces, frozen-observation path and designated-span checks; static schemas still permit only none/squeez |
| Source/configuration | `src/contracts.py`, `src/provenance.py`, `src/measurement.py`, `src/static_run.py`, `src/compare.py` | Local schemas, source snapshots, distinct measurement units, static execution and name-only comparison |
| Source/configuration | `src/eda.py` | Recompute the published candidate-share chart from reviewed aggregates; no private layout dependency |
| Source/configuration | `src/eda_report.py`, `tests/test_eda_report.py` | Offline checks of reviewed EDA table cells, samples, denominators, figure bytes/text, limitations and sensitive-pattern regressions |
| Source/configuration | `src/native_run.py`, `src/native_contract.py`, `src/baseline.py`, `src/native_judge.py`, `src/verifier_revisions.py`, `src/llmlingua_worker.py`, `src/adapter_preflight.py`, `src/blob_retrieval.py`, `ledgers/native.template.toml` | Opt-in four-condition native driver, strict unapproved template, hash-bound nginx verifier revision, eight-process offline LLMLingua pool, model-free all-adapter preflight, predeclared stopping calculations, local-first managed-identity Blob retrieval and native failure-evidence classification |
| Source/configuration | `src/harbor_agent.py`, `src/harbor_no_time_limits.py`, `src/command_trace.py`, `src/task_metrics.py`, `src/live_transport.py`, `src/live_observations.py` | Actual Harbor instrumentation, pinned Harbor phase-limit removal entry point, separate turns/calls/repetitions/compressor timing/units, protected loopback transport and cooperative queue |
| Source/configuration | `src/prompt_intake.py` | Archive untracked root request attachments privately before CLI/audit inventory; not a public wildcard |
| Source/configuration | `tests/native_helpers.py`, `tests/test_baseline.py`, `tests/test_native_contract.py`, `tests/native_test_harbor_preflight.py`, `tests/test_native_compressors.py`, `tests/test_adapter_preflight.py`, `tests/test_blob_retrieval.py`, `tests/test_native_judge.py`, `tests/test_native_run.py`, `tests/test_task_metrics.py`, `tests/test_live_transport.py`, `tests/test_live_observations.py`, `tests/test_harbor_transport.py`, `tests/test_prompt_intake.py` | Synthetic/fake-upstream validation, worker-pool and complete-input checks, native-only Harbor preflight, model-free guarded adapter preflight, local spool/retry/resume checks, real SDK serialization without models, removed-limit regressions, malformed/failure/provenance tests and private prompt intake |
| Source/configuration | `requirements/llmlingua2-cpu.txt`, `fixtures/llmlingua2/path-listing.txt`, `fixtures/llmlingua2/severity-log.txt`, `fixtures/llmlingua2/package-install.txt` | Exact observed LLMLingua CPU environment pins and small public-benchmark-shaped determinism probes; no model weights or private requests |
| Source/configuration | `verifiers/terminal-bench-2.1/nginx-request-logging/revision.json`, `fixtures/verifiers/nginx-request-logging/unbraced.conf`, `fixtures/verifiers/nginx-request-logging/braced.conf`, `fixtures/verifiers/nginx-request-logging/wrong-variable.conf`, `tests/test_verifier_revisions.py` | Public benchmark verifier source/effective hashes and three model-free syntax fixtures; no benchmark responses or private paths |
| Implementation documentation | `docs/native-contract.md` | Fixed native design, units, proposed range rule, known judge/transport limits and execution gates; not an experiment results report |
| Source/configuration | `schemas/frozen-input.schema.json`, `schemas/static-ledger.schema.json`, `schemas/static-result.schema.json` | Frozen input partitions, one selected ledger and typed per-record provenance |
| Source/configuration | `ledgers/demo.toml`, `ledgers/static.toml` | Synthetic and private historical input profiles; no resource address or credential value |
| Source/configuration | `tests/test_accounting.py`, `tests/test_evidence.py`, `tests/test_run.py`, `tests/test_protection.py`, `tests/test_static.py`, `tests/test_compare.py`, `tests/test_eda.py` | Synthetic transport/protection/source fixtures and aggregate contracts; optional real-binary test is explicitly selected |
| Implementation documentation | `README.md`, `STATUS.md`, `docs/static-contract.md`, `docs/publication.md` | Entry points, provenance/units, failure paths and remaining readiness gaps |
| Sanitized public discussion record | `docs/experiment/README.md`, `docs/experiment/protocol.md`, `docs/experiment/decisions.md` | Current state, fixed protocol and decision history; private locations, resource identifiers and internal names removed |
| Sanitized public design | `docs/experiment/screening-protocol.md` | Fixed 89-task screening population, 18-of-20 rule, retry boundary, nginx verifier revision and start conditions; no raw trial content |
| Sanitized public design | `docs/experiment/evaluation-protocol.md` | Fixed four-condition comparison, policy thresholds, repetition formula, bootstrap decision and schedule calculation; no execution result |
| Sanitized public design | `docs/experiment/reproducibility-contract.md` | Required private replay bundle, idempotent accounting, Blob retention and public/private evidence boundary; no identifiers or raw trace |
| Sanitized preliminary measurement | `docs/experiment/preliminary-comparison-20260916.md` | Seven task-level four-condition observations with provider usage, measured transformations, cost scope, evidence hashes and explicit non-generalization limits; no raw requests, responses or operational paths |
| Public implementation | `src/screening_contract.py`, `src/screening_inventory.py`, `src/screening_scheduler.py`, `src/screening_run.py`, `src/screening_cost.py`, `src/replay_environment.py` | Hash-bound screening, retry and replay implementation; runtime locations are supplied only through environment variables |
| Public analysis implementation | `src/evaluation_statistics.py`, `src/evaluation_coverage.py`, `data/experiment/coverage-validation-v1.json`, `data/experiment/terminal-bench-2.1-task-types.json` | Fixed-task paired statistics, preregistered synthetic operating check and reviewed task classification; no model outputs |
| Public execution template | `ledgers/screening.template.toml` | Non-operational values and public rates; execution authorization and private runtime references remain unset, while the no-harness-stop policy and reporting target are explicit |
| Sanitized aggregate measurement | `docs/experiment/baseline.md`, `docs/experiment/compressors.md` | Aggregate baseline measurements and sanitized static before/after excerpts; raw prompts, responses, endpoints and private paths omitted |
| Historical sanitized documentation | `docs/local-native.md` | Existing native measurements and instructions, explicitly separated from this source revision and static work |
| Synthetic source fixture | `examples/static/manifest.json`, `examples/static/requests/0000.json` | Hand-authored fake instruction/code/log input, labeled synthetic; never native or customer evidence |
| Aggregate only | `data/eda/task-candidate-share.csv`, `data/eda/lineage.json` | Five task-level byte/count aggregates for two classification rounds, original table hashes and explicit limitations; no request bodies |
| Aggregate visualization | `figures/task-candidate-share.svg` | Generated two-round candidate byte shares, denominators and sample caveats; not achieved compression |
| Reviewed EDA assembly | `docs/eda/README.md`, `docs/eda/manifest.json` | Existing first/second-round tables and explanations, original table ordinals and cell/figure hashes; no raw requests or new experiment results |
| Reviewed EDA figures | `docs/eda/figures/round1/01-input-size.svg`, `docs/eda/figures/round1/02-input-composition.svg`, `docs/eda/figures/round1/03-compressible-share.svg`, `docs/eda/figures/round1/04-shared-prefix.svg`, `docs/eda/figures/round1/05-corpus-bias.svg`, `docs/eda/figures/round1/06-api-token-calibration.svg` | Five byte-identical SVG copies and one label-only public derivative: instruction sizes, composition, candidates, shared prefixes, corpus bias and API/local calibration. The shared-prefix measurements and 1,024 reference are unchanged; only the work-environment name is removed |
| Reviewed EDA figures | `docs/eda/figures/round2/01-task-types.svg`, `docs/eda/figures/round2/02-candidate-share-by-type.svg`, `docs/eda/figures/round2/03-input-size-by-type.svg`, `docs/eda/figures/round2/04-unknown-decomposition.svg` | Byte-identical SVG copies: task classifications, candidates by type, sizes by type and unknown-span decomposition |
| Historical sanitized measurements | `evidence/local-baseline.json`, `evidence/local-baseline-repeat.json`, `evidence/development-3b-failure.json`, `evidence/development-7b-timeout.json`, `evidence/development-reasoning-timeout.json` | Previously allowlisted local-provider usage, outcomes and artifact hashes, including failures; no prompt/response bodies or deployed endpoints |

The historical native records have no execution commit SHA. They are not assigned
the new root commit and their validity is limited to the sanitized-record checks.
Local-provider tokens are not billed cloud tokens.

## Private or not yet approved

| Grade | Paths | Rule |
|---|---|---|
| Raw, never automatically public | `runs/` | Source/ledger/input snapshots, original requests, transformed output, recovery stashes, raw tool stderr and detailed static records |
| Entire imported tree stays private | `local-imports/` | Original code copies, raw executions, internal documents, meetings, fixtures and downloaded executables; do not import its history |
| Private working material | `_work/` | Migration scan with per-file line numbers, internal inventories/design/kanban, frozen-input preparation, original-source mappings and local history backup |
| Private request attachments | `_work/prompts/` and its `manifest.json`; original root names `prompt_eda_round2.md`, `prompt_eda_round2 (1).md`, `prompt_design_final.md`, `prompt_repo_first_commit.md`, `prompt_before_baseline.md` | User requests, not measurement outputs. Intake preserves original/archive paths, SHA-256 and byte count. Exact legacy root ignores remain as defense; no wildcard public approval |
| Local resource/cache/credentials | `.cache/`, `.venv/`, `.env`, `__pycache__/`, `*.pyc` | Not source or publishable evidence |
| System metadata | `@eaDir/` directories at any depth, `.DS_Store` | Synology/Finder metadata, ignored while untracked and forbidden if force-added |
| Private EDA originals | Original EDA scripts, figures and row-level catalogs under `_work/` | Only the exact reviewed copies listed above are graded. Raw sources, classification records and the standalone review HTML stay private; the aggregate renderer does not reproduce all EDA |
| Unresolved distribution/reuse | Third-party binaries, models and unapproved assets | No vendored squeez executable, Headroom package, LLMLingua model, imported dependency tree or silently assumed redistribution/license grant |

Raw and transformed hashes are retained in private run snapshots. Public aggregate
lineage retains the original table hashes without private host paths. Independent
raw-request classification cannot be reproduced from the aggregate-only release.

## Audit before commit or release

`run.py` entry and `evidence.py audit-files` automatically archive **untracked
root** `prompt_*.md` attachments with conservative filenames under ignored
`_work/prompts/`, with a private inventory. Different contents with the same
name receive a hash suffix, not an overwrite. Tracked attachments, symlinks,
hardlinks, unknown filenames and nested files are not silently moved or approved.
The intake requires Git to exclude the destination and verifies bytes before
removing the root copy. It runs on command entry, not as a background watcher.

```bash
uv run --locked python evidence.py audit-files .
git diff --check
git diff --cached --stat
```

The audit includes tracked and nonignored untracked files. It performs an exact
**file grade** check and, when present, validates the reviewed EDA assembly against
its manifest: table cells, samples/denominators/kinds, required limitations, SVG
bytes and visible text. It scans that assembly for common private-path/account
patterns and rejects active or externally loaded SVG content. The same check runs
with `python -m src.eda_report`; it does not reconstruct private source data.

This is not a general secret scanner or a license/legal review. Inspect staged blobs
for customer identifiers, internal paths, resource addresses, credentials, fixture
specificity and internal commentary separately. A zero-match pattern scan is not
a proof that arbitrary material is safe. Keep licensing and public release as
explicit decisions; a first local commit does not resolve them.
