# prompt-compression-billing-bench

Measure **candidate share**—code-excluded identified candidate bytes divided by
each task's request-content UTF-8 bytes—without confusing it with achieved
compression, tool estimates, local token counts or provider usage.

![Historical candidate byte shares across five purpose-selected tasks; two classification rounds, not achieved compression.](figures/task-candidate-share.svg)

| Observed minimum | Observed maximum | Observed sample |
|:---:|:---:|:---:|
| **0.48%** | **35.29%** | **5 purpose-selected tasks** |

These are Terminal-Bench 2.1 purpose-selected tasks, not a representative sample.
Each task aggregates its existing three runs, including retransmitted message history.
Code-reading and mixed-code spans are excluded. This is an **identified candidate
range, not a validated upper bound**. Actual compression rate, quality and billed
savings were not measured.

## Results and limits

The chart is generated from [aggregate bytes and sample counts](data/eda/task-candidate-share.csv),
not from a new compression or billing experiment. The instruction classifications
for the two benchmarks contain no review-only task; current performance on mixed
review-and-fix tasks is unmeasured.

The [two-round EDA review (Korean)](docs/eda/README.md) collects the existing
benchmark/input figures and tables with sample counts, denominators and measurement
labels. Its ten figures use relative paths; tool-behavior experiments are separate.

For KT sharing, start with the [one-page Korean briefing](docs/experiment/kt-briefing-20260919.md),
continue to the [plain-language Korean summary](docs/experiment/kt-sharing-20260917.md),
then use the [technical evidence report](docs/experiment/preliminary-comparison-20260916.md)
for condition-level figures, run identifiers and hashes. The broader
[experiment record (Korean)](docs/experiment/README.md) separates the fixed protocol,
the measured none baseline, static compressor measurements, preliminary comparison
and open decisions. The none baseline completed 20 repetitions but stopped
inconclusive under its predeclared rule; the preliminary comparison is one run per
condition, not the preregistered repeated evaluation.

Static token reductions do not establish native quality, prompt-cache behavior,
recovery overhead or cost savings. Setting temperature to zero or reasoning effort
to none does not make a model deterministic or undo the native harness's existing
output elision.

## Try it in five minutes

Run from a clean committed checkout on Linux with Python 3.12+ and `uv`.
This small input is explicitly **synthetic**: it demonstrates the actual adapter
and record path, not benchmark quality or a five-minute native-model result.
Dependency installation and tokenizer preparation need internet; measurement does not fetch inputs.

```bash
uv sync --locked
export TIKTOKEN_CACHE_DIR="$PWD/.cache/tiktoken"
uv run --locked python run.py static --prepare-tokenizer "$TIKTOKEN_CACHE_DIR"
export SOURCE_COMMIT=$(git rev-parse HEAD)
uv run --locked python run.py experiment examples/experiment/static.yaml
uv run --locked python run.py experiment examples/experiment/static.yaml --execute
uv run --locked python run.py experiment \
  --verify-result examples/experiment/static-result.json
```

The YAML names the low-level TOML ledger and its SHA-256. The first command is
the default check; `status=checked` and `outcome=preflight_passed` mean the
inputs and adapter passed without a provider call. `--execute` delegates to the
existing static runner and writes `runs/<run_id>/experiment-result.json`.
The result directory also keeps the exact `experiment-request.yaml`, its SHA-256,
and the verified lower-level `summary.json` hash.
`status=failed` with `outcome=technical_incomplete` is not a wrong answer.
The synthetic fixture checks wiring and the JSON contract only; it does not
establish native-model quality or reproduce the benchmark result.

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

## Implementation

- Two static conditions and four native conditions, one frozen-observation pipeline, pinned execution ledgers and result schemas.
- A user-facing YAML request binds to one hash-pinned low-level TOML ledger. `run.py experiment` checks by default and delegates execution to the existing runner; it does not implement a second execution path.
- Separate `tool_reported`, `measured_local` and `measured_billed` fields. No API calls means billing is **not measured**, not a measured zero.
- A reproducible aggregate EDA chart; raw historical requests are not distributed.
- An optional [local-model native runner](docs/local-native.md), not yet connected to the compressor pipeline.
- An opt-in [Harbor/Foundry candidate-compression runner](docs/native-contract.md) for none, squeez, a Headroom paths-only profile and LLMLingua-2, with a shared protected transport, per-task workload metrics, a five-repetition continuation gate and local-first Blob result retrieval. A none baseline is measured; a preliminary native comparison for 26 tasks × four conditions is complete with one run per condition, but the preregistered repeated evaluation remains unexecuted.

## Protection

The offline path applies either **no added compression** (`none`) or **squeez**
to the same hash-bound log spans. Code, mixed-code output, instructions, message
roles and request settings remain protected. The shared pipeline stops on a
protection failure; it does not silently switch to a different baseline path.

The protected-span check is structural, not proof that every log is safe to lose.
The frozen classification and conservative live Harbor policy are separate.

## Reproduce and compare

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

## Contracts and next steps

The real accountless Ollama path remains available separately, but its historical
cached runs exceeded five minutes. The synthetic demo is not a substitute for that gap.
The native path has one real none baseline with verified result retrieval and
host deallocation. A compressor comparison and deployment-wide caller isolation
have not been validated.

| Need | Read |
|---|---|
| KT decision briefing and experiment-design gaps | [One-page KT briefing](docs/experiment/kt-briefing-20260919.md) |
| KT preliminary results in plain Korean | [KT sharing summary](docs/experiment/kt-sharing-20260917.md) |
| User-facing YAML and common JSON examples | [Static YAML](examples/experiment/static.yaml) · [Static JSON](examples/experiment/static-result.json) |
| Condition-level KT evidence, run identifiers and hashes | [Preliminary comparison evidence](docs/experiment/preliminary-comparison-20260916.md) |
| Exact execution, provenance, adapter and measurement contracts | [Static contract](docs/static-contract.md) |
| Accountless native execution and historical evidence | [Local native runner](docs/local-native.md) |
| Opt-in Foundry path, workload metrics and proposed baseline rule | [Native contract](docs/native-contract.md) |
| Current protocol, baseline, static compressors and open decisions | [Experiment record](docs/experiment/README.md) |
| Unsupported paths and readiness gaps | [Status](STATUS.md) |
| What may be shared and what stays private | [Publication grades](docs/publication.md) |

No raw run, prompt, recovery stash, imported tree or private work note is published automatically.
