# EDA publication boundaries

Eligibility is not publication approval. Repository visibility remains a separate
decision. No audit command pushes code or changes visibility. The exact machine
allowlist is `PUBLIC_FILES` in `evidence.py`; unknown files fail the audit.

## Reviewed EDA additions

| Grade | Exact files | Contents |
|---|---|---|
| Entry point and audit integration | `README.md`, `evidence.py`, `docs/publication.md` | Link the EDA review and extend the existing file-grade audit without changing native execution |
| Offline validation | `src/eda_report.py`, `tests/test_eda_report.py` | Check reviewed EDA table cells, samples, denominators, figure bytes/text, limitations and sensitive-pattern regressions; uses the existing SHA-256 helper in `accounting.py` |
| Reviewed EDA assembly | `docs/eda/README.md`, `docs/eda/manifest.json` | Existing first/second-round tables and explanations, original table ordinals and cell/figure hashes; no raw requests or new experiment results |
| Aggregate only | `data/eda/task-candidate-share.csv`, `data/eda/lineage.json` | Five task-level byte/count aggregates for two classification rounds, original table hashes and explicit limitations; no request bodies |
| Reviewed EDA figures | `docs/eda/figures/round1/01-input-size.svg`, `docs/eda/figures/round1/02-input-composition.svg`, `docs/eda/figures/round1/03-compressible-share.svg`, `docs/eda/figures/round1/04-shared-prefix.svg`, `docs/eda/figures/round1/05-corpus-bias.svg`, `docs/eda/figures/round1/06-api-token-calibration.svg` | Byte-identical SVG copies: instruction sizes, composition, candidates, shared prefixes, corpus bias and API/local calibration |
| Reviewed EDA figures | `docs/eda/figures/round2/01-task-types.svg`, `docs/eda/figures/round2/02-candidate-share-by-type.svg`, `docs/eda/figures/round2/03-input-size-by-type.svg`, `docs/eda/figures/round2/04-unknown-decomposition.svg` | Byte-identical SVG copies: task classifications, candidates by type, sizes by type and unknown-span decomposition |

The original EDA scripts, row-level catalogs, raw requests, standalone review HTML
and tool-behavior materials are not part of this addition. Independent raw-request
classification cannot be reproduced from the aggregate-only release. Copying the
reviewed figures does not reproduce the private source-data analysis.

## Audit

```bash
python -m src.eda_report
python -m unittest discover -s tests -v
python evidence.py audit-files .
```

The audit includes tracked and nonignored untracked files. It performs an exact
file-grade check and validates the reviewed EDA assembly against its manifest:
table cells, samples/denominators/kinds, required limitations, SVG bytes and visible
text. It scans that assembly for common private-path/account patterns and rejects
active or externally loaded SVG content. It does not reconstruct private source data.

This is not a general secret scanner or a license/legal review. Inspect staged blobs
for customer identifiers, internal paths, resource addresses and credentials
separately. A zero-match pattern scan does not prove arbitrary material safe.
