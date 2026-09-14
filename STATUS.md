# Repository readiness

This public-source layout includes a measured none baseline, but not a completed
native compression comparison. The baseline stopped inconclusive under its
predeclared rule. Static compressor measurements remain separate from native quality.

## Nine checks

| Check | State | Present contract and remaining gap |
|---|---|---|
| 1. Real five-minute run | **Open** | A real accountless Ollama path exists separately, but historical cached executions exceeded five minutes. Cold installation and downloads are not covered. The synthetic static demo does not satisfy this check. |
| 2. One execution ledger | **Implemented; compressor execution pending** | Static and opt-in native ledgers fix their distinct paths. The native path checks committed source, benchmark files, image/dependency pins, four condition profiles, the eight-worker LLMLingua pool and 5,000-character input cap, wire settings, one persistent cooperative deployment queue and managed-identity result retrieval. The none baseline used an approved ledger; the public template remains deliberately unapproved. External-caller isolation is not automatically verified. |
| 3. Record provenance | **Implemented for static runs and the none baseline** | Each row separates provider usage, local counts, calculated deltas, classification and invoice-unreconciled cost. The measured baseline records source SHA and exact snapshots. Old sanitized native evidence has no source SHA and is not retroactively upgraded. |
| 4. Drift safeguards | **Rule executed; baseline inconclusive** | The five-repetition gate allowed collection to continue, the 10-repetition halves differed, and the total-20 halves still differed. The rule stopped comparison as inconclusive. These operational rules are not proof of statistical stability or equivalence. Private raw measurements cannot be rerun by public CI. |
| 5. Unsupported cases | **Explicit, not solved** | A narrow source-bound live log classifier and Terminal adapter exist. No general benchmark adapter, DeepSWE execution, measured cloud comparison, semantic log-preservation proof, agent-visible recovery tool or recovery-cost result. Native judge subcheck gaps remain disclosed, not regraded away. |
| 6. Layered README | **Implemented** | Scope first, chart/method limits next, synthetic static commands next, native execution and detailed contracts behind links. This does not make the five-minute native path pass. |
| 7. Terminology | **Implemented** | Candidate range, message-content denominator, tool display, local tokenizer and unavailable billing are defined at use. No tool display is named a billed-token result. |
| 8. Failure paths | **Partial** | Missing dependencies/resources, dirty/wrong source, cross-worker fixture drift, malformed partitions, tool exits, deadlines and invalid UTF-8 stop explicitly. LLMLingua suffix loss is retained privately. Blob failures preserve an atomic local payload for retry/resume and block a complete status; collection-host checksum verification and VM cleanup passed for the none baseline but remain external gates for each future run. |
| 9. Publication grades | **Partial** | Exact file allowlist, private attachment/import/work ignores, aggregate-only EDA and sanitized experiment discussion records exist. Every staged file still requires review; licensing and binary redistribution remain separate unresolved decisions. |

## Remaining work

- Establish a genuinely measured five-minute accountless native path, including an explicit setup boundary.
- Decide whether an inconclusive 20-repetition none baseline should block the three compressor conditions or trigger a redesigned baseline. The current runner blocks automatic comparison.
- Repeat the verified baseline host-cleanup and retrieval gates for every comparison, and validate deployment-wide caller isolation. Settings alone do not control external drift.
- Resolve squeez 1.48.4 distribution: the retained executable matches its checksum, but its upstream versioned release/tag is unavailable. No binary is vendored or silently upgraded.
- Execute the fixed squeez, Headroom paths-only and LLMLingua-2 conditions only after resolving the baseline decision; adapter software tests and static reductions are not native quality evidence.
- Run the all-adapter execution-host preflight at every designated SHA; it performs no provider call and does not replace a native comparison.
- Validate tool-specific semantic anchors during the comparison; result retrieval is separate from an agent-visible recovery experiment and has no recovery-token claim.
- Port the remaining EDA/classification pipelines away from private layouts and review their figure/table data. Only the reviewed candidate-share aggregate renderer is in this source layout.
- Decide licensing and reuse terms. A local documentation commit is not a push.

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
