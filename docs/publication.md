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
| Source/configuration | `src/__init__.py`, `src/compressors.py`, `src/pipeline.py`, `src/protection.py` | Only none/squeez, shared frozen-observation path and designated-span checks |
| Source/configuration | `src/contracts.py`, `src/provenance.py`, `src/measurement.py`, `src/static_run.py`, `src/compare.py` | Local schemas, source snapshots, distinct measurement units, static execution and name-only comparison |
| Source/configuration | `src/eda.py` | Recompute the published candidate-share chart from reviewed aggregates; no private layout dependency |
| Source/configuration | `schemas/frozen-input.schema.json`, `schemas/static-ledger.schema.json`, `schemas/static-result.schema.json` | Frozen input partitions, one selected ledger and typed per-record provenance |
| Source/configuration | `ledgers/demo.toml`, `ledgers/static.toml` | Synthetic and private historical input profiles; no resource address or credential value |
| Source/configuration | `tests/test_accounting.py`, `tests/test_evidence.py`, `tests/test_run.py`, `tests/test_protection.py`, `tests/test_static.py`, `tests/test_compare.py`, `tests/test_eda.py` | Synthetic transport/protection/source fixtures and aggregate contracts; optional real-binary test is explicitly selected |
| Implementation documentation | `README.md`, `STATUS.md`, `docs/static-contract.md`, `docs/publication.md` | Entry points, provenance/units, failure paths and remaining readiness gaps |
| Historical sanitized documentation | `docs/local-native.md` | Existing native measurements and instructions, explicitly separated from this source revision and static work |
| Synthetic source fixture | `examples/static/manifest.json`, `examples/static/requests/0000.json` | Hand-authored fake instruction/code/log input, labeled synthetic; never native or customer evidence |
| Aggregate only | `data/eda/task-candidate-share.csv`, `data/eda/lineage.json` | Five task-level byte/count aggregates for two classification rounds, original table hashes and explicit limitations; no request bodies |
| Aggregate visualization | `figures/task-candidate-share.svg` | Generated two-round candidate byte shares, denominators and sample caveats; not achieved compression |
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
| Private request attachments, retained in place | Root `prompt_eda_round2.md`, `prompt_eda_round2 (1).md`, `prompt_design_final.md`, `prompt_repo_first_commit.md` | Only these exact filenames are ignored; the first two are identical request copies. No wildcard approval for future attachments |
| Local resource/cache/credentials | `.cache/`, `.venv/`, `.env`, `__pycache__/`, `*.pyc` | Not source or publishable evidence |
| System metadata | `@eaDir/` directories at any depth, `.DS_Store` | Synology/Finder metadata, ignored while untracked and forbidden if force-added |
| Deferred EDA candidates | Remaining original EDA scripts, first/second-round figures and row-level catalogs under `_work/` | Private path/fixture coupling, classification context and each figure's source data need a separate port/review; the aggregate renderer is not claimed to reproduce all EDA |
| Unresolved distribution/reuse | Third-party binaries and unapproved assets | No vendored squeez executable, imported dependency tree or silently assumed redistribution/license grant |

Raw and transformed hashes are retained in private run snapshots. Public aggregate
lineage retains the original table hashes without private host paths. Independent
raw-request classification cannot be reproduced from the aggregate-only release.

## Audit before commit or release

```bash
uv run --locked python evidence.py audit-files .
git diff --check
git diff --cached --stat
```

The audit includes tracked and nonignored untracked files. It is an exact **file
grade** check, not a secret scanner or a license/legal review. Inspect staged blobs
for customer identifiers, internal paths, resource addresses, credentials, fixture
specificity and internal commentary separately. A zero-match pattern scan is not
a proof that arbitrary material is safe. Keep licensing and public release as
explicit decisions; a first local commit does not resolve them.
