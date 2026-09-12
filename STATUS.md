# Repository readiness

This first public-source layout is not release approval or a claim that native
compression experiments are ready. Static results are stored as machine records,
not presented here as a new experiment report.

## Nine checks

| Check | State | Present contract and remaining gap |
|---|---|---|
| 1. Real five-minute run | **Open** | A real accountless Ollama path exists separately, but historical cached executions exceeded five minutes. Cold installation and downloads are not covered. The synthetic static demo does not satisfy this check. |
| 2. One execution ledger | **Implemented; live execution pending** | Static and opt-in native ledgers fix their distinct paths. The native path checks committed source, benchmark files, image/dependency pins, wire settings and one persistent cooperative deployment queue. Its unapproved template cannot call a model. External-caller isolation is not automatically verified. |
| 3. Record provenance | **Implemented for static runs** | Each row separates tool displays, local counts, calculated deltas, classification and unavailable billing. Source SHA and exact snapshots are mandatory. Old sanitized native evidence has no source SHA and is not retroactively upgraded. |
| 4. Drift safeguards | **Implemented proposal; approval/measurement pending** | Native 10→total20 observed-range calculation, comparison/floor rules and artifact-to-decision verification have model-free tests. This operational rule is not proof of statistical stability or equivalence. Private corpus measurements cannot be rerun by public CI. |
| 5. Unsupported cases | **Explicit, not solved** | A narrow source-bound live log classifier and Terminal adapter exist. No general benchmark adapter, DeepSWE execution, measured cloud comparison, semantic log-preservation proof, persistent squeez/retrieval tool or recovery-cost result. Native judge subcheck gaps remain disclosed, not regraded away. |
| 6. Layered README | **Implemented** | Scope first, chart/method limits next, synthetic static commands next, native execution and detailed contracts behind links. This does not make the five-minute native path pass. |
| 7. Terminology | **Implemented** | Candidate range, message-content denominator, tool display, local tokenizer and unavailable billing are defined at use. No tool display is named a billed-token result. |
| 8. Failure paths | **Partial** | Missing dependencies/resources, dirty/wrong source, hash/version mismatch, malformed partitions, tool exits, deadlines and invalid UTF-8 stop explicitly. Partial results fail verification. Resume/recovery is not implemented. |
| 9. Publication grades | **Partial** | Exact file allowlist, private attachment/import/work ignores and aggregate-only EDA exist. Every staged file still requires review; public release, licensing and binary redistribution are separate unresolved decisions. |

## Remaining work

- Establish a genuinely measured five-minute accountless native path, including an explicit setup boundary.
- Approve the proposed baseline rule and execution, supply current quota/rate/budget/deadline records, and commit reviewed changes before obtaining an execution SHA. No model calls are authorized by the template.
- Validate actual execution-host cleanup and deployment-wide isolation before comparison; loopback/process tests do not establish those external conditions. Settings alone do not control drift.
- Resolve squeez 1.48.4 distribution: the retained executable matches its checksum, but its upstream versioned release/tag is unavailable. No binary is vendored or silently upgraded.
- Validate tool-specific semantic anchors and actual retrieval, including its calls, tokens, latency and state lifecycle.
- Port the remaining EDA/classification pipelines away from private layouts and review their figure/table data. Only the reviewed candidate-share aggregate renderer is in this source layout.
- Decide public licensing/reuse and release approval. A local root commit is not a push or a visibility change.

## Checks without model calls

Prepare the pinned tokenizer cache once, as in the [README](README.md#try-it-in-five-minutes).

```bash
uv run --locked python -m unittest discover -s tests -v
uv run --locked python -m src.eda --check
uv run --locked python evidence.py audit-files .
for file in evidence/*.json; do uv run --locked python evidence.py check "$file"; done
```

The optional real-squeez integration test uses `TEST_SQUEEZ_BINARY` and verifies
the ledger's binary SHA/version. CI without that binary skips only that test;
it does not claim to have rerun the real compressor or the private historical corpus.

The separate native-contract CI job installs the locked `native` extra and
exercises actual Harbor/SDK code with fake responses and dummy processes only.
See [Native contract](docs/native-contract.md) for units, fail-closed behavior,
judge gaps and model-free validation. No real native comparison is a CI fixture.

## Data grades

See the exact inventory and raw/sanitized/aggregate boundaries in
[Publication grades](docs/publication.md). Internal work inventories and raw
static runs are ignored, not automatically made safe by their filename.
