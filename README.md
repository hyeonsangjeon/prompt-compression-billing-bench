# prompt-compression-billing-bench

Measure identified log compression without confusing tool estimates, local tokens, and provider usage.

The offline path applies either **no added compression** (`none`) or **squeez**
to the same hash-bound log spans. Code, mixed-code output, instructions, message
roles and request settings remain protected. The shared pipeline stops on a
protection failure; it does not silently switch to a different baseline path.

## What is available

- Two adapters, one frozen-observation pipeline, pinned execution ledgers and result schemas.
- Separate `tool_reported`, `measured_local` and `measured_billed` fields. No API calls means billing is **not measured**, not a measured zero.
- A reproducible aggregate EDA chart; raw historical requests are not distributed.
- An optional [local-model native runner](docs/local-native.md), not yet connected to the compressor pipeline.

![Historical candidate byte shares across five purpose-selected tasks; two classification rounds, not achieved compression.](figures/task-candidate-share.svg)

The chart describes an **identified candidate range, not a validated upper bound**.
It is generated from [aggregate bytes and sample counts](data/eda/task-candidate-share.csv),
not from a new compression or billing experiment.

## Try the static path

Run from a clean committed checkout on Linux with Python 3.12+ and `uv`.
This small input is explicitly **synthetic**: it demonstrates the actual adapter
and record path, not benchmark quality or a five-minute native-model result.
Dependency installation and tokenizer preparation need internet; measurement does not fetch inputs.

```bash
uv sync --locked
export TIKTOKEN_CACHE_DIR="$PWD/.cache/tiktoken"
uv run --locked python run.py static --prepare-tokenizer "$TIKTOKEN_CACHE_DIR"
export FROZEN_INPUT_ROOT="$PWD/examples/static"
SOURCE_COMMIT=$(git rev-parse HEAD)
uv run --locked python run.py static --source-commit "$SOURCE_COMMIT" ledgers/demo.toml
```

The command prints its new `runs/static-*/` directory. Inspect `summary.json`;
`measured_local` counts complete message content, excluding API framing.
The model and native judge are never called by `run.py static`.

For squeez, supply the executable matching the version and SHA-256 in the ledger
through `SQUEEZ_BINARY`. Change **only** `compressor.name` in a ledger copy:

```bash
mkdir -p _work
sed 's/^name = "none"$/name = "squeez"/' ledgers/demo.toml > _work/demo-squeez.toml
uv run --locked python run.py static --source-commit "$SOURCE_COMMIT" _work/demo-squeez.toml
```

The pinned Linux x86-64 binary is version 1.48.4. Its upstream release/tag was
unavailable at inspection; there is no automatic download or fallback to a newer
version. Binary distribution is an [open readiness item](STATUS.md).

## Verify or compare

Replace the directory placeholders with the paths printed by completed runs.

```bash
uv run --locked python run.py static --verify runs/<run-id>
uv run --locked python -m src.compare runs/<none-run-id> runs/<squeez-run-id> \
  --source-commit "$SOURCE_COMMIT" --output _work/static-comparison
uv run --locked python -m src.eda --check
uv run --locked python -m unittest discover -s tests -v
uv run --locked python evidence.py audit-files .
```

Comparison refuses differences beyond `compressor.name`. It emits JSON/CSV,
including a swap proof, task aggregates, local span counts and separate tool diagnostics.
Full stdout, including squeez headers and retrieval markers, counts toward size;
an expanding result is recorded as an expansion rather than hidden.

## Boundaries and next steps

The protected-span check is structural, not proof that every log is safe to lose.
The stored classification is not a live Harbor classifier. Static token reductions
do not establish native quality, prompt-cache behavior, recovery overhead or cost savings.
Setting temperature to zero or reasoning effort to none does not make a model
deterministic or undo the native harness's existing output elision.

The real accountless Ollama path remains available separately, but its historical
cached runs exceeded five minutes. The synthetic demo is not a substitute for that gap.
Neither native compressor integration nor a cloud comparison is claimed here.

| Need | Read |
|---|---|
| Exact execution, provenance, adapter and measurement contracts | [Static contract](docs/static-contract.md) |
| Accountless native execution and historical evidence | [Local native runner](docs/local-native.md) |
| Unsupported paths and readiness gaps | [Status](STATUS.md) |
| What may be shared and what stays private | [Publication grades](docs/publication.md) |

No raw run, prompt, recovery stash, imported tree or private work note is published automatically.
