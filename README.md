# prompt-compression-billing-bench

## In three seconds

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

## Decide in 30 seconds

The chart is generated from [aggregate bytes and sample counts](data/eda/task-candidate-share.csv),
not from a new compression or billing experiment. The instruction classifications
for the two benchmarks contain no review-only task; current performance on mixed
review-and-fix tasks is unmeasured.

The [two-round EDA review (Korean)](docs/eda/README.md) collects the existing
benchmark/input figures and tables with sample counts, denominators and measurement
labels. Its ten figures use relative paths; tool-behavior experiments are separate.

For KT sharing, start with the [plain-language Korean summary](docs/experiment/kt-sharing-20260917.md),
then use the [one-page Korean briefing](docs/experiment/kt-briefing-20260919.md)
and [plain-language visualization guide](docs/experiment/visualization-guide-20260919.md),
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

Run from a clean committed checkout with Python 3.12+ and `uv`. The YAML names
one real Terminal-Bench 2.1 task. The default command validates the task, current
Git commit, public reference ledger and JSON output contract without calling a model.

```bash
uv sync --locked
uv run --locked python run.py experiment examples/experiment/benchmark.yaml
uv run --locked python run.py experiment \
  --verify-result runs/readme-benchmark-result.json
```

The user-facing fields are the experiment type, endpoint environment-variable
name, benchmark name/revision/task, model, condition and JSON output. The wrapper
selects the committed low-level reference ledger and records its SHA-256, replay
protection and retry settings. It detects the current clean `HEAD`; no
`SOURCE_COMMIT` input is needed. `status=checked` with
`outcome=preflight_passed` means the real task identifier and contracts passed
without a provider call. It is not a quality result.

Actual execution is opt-in only:

```bash
uv sync --locked --extra native
# A deployment operator supplies the named endpoint, approved operational ledger,
# benchmark checkout, inventory, queue, retrieval and tokenizer environment values.
uv run --locked python run.py experiment examples/experiment/benchmark.yaml --execute
```

`--execute` verifies that the approved operational ledger changes only the
runtime approval and evidence fields allowed by the public reference. It then
delegates the selected task to the existing `screening_run --diagnose-task`
path; it does not implement another benchmark engine. The checked path above is
measured in the [repository validation record](data/experiment/readme-benchmark-validation.json).
A provider-backed five-minute
completion is a target, not a verified result: this change made no provider call.
`status=failed` with `outcome=technical_incomplete` is not a wrong answer.

The earlier synthetic static example remains a wiring fixture, not the default
five-minute path. Its YAML and result are available in `examples/experiment/`
for offline contract tests only.

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
cached runs exceeded five minutes. The no-call benchmark check is not a substitute
for measuring provider-backed wall time.
The native path has one real none baseline with verified result retrieval and
host deallocation. A compressor comparison and deployment-wide caller isolation
have not been validated.

| Need | Read |
|---|---|
| KT decision briefing and experiment-design gaps | [One-page KT briefing](docs/experiment/kt-briefing-20260919.md) |
| KT preliminary results in plain Korean | [KT sharing summary](docs/experiment/kt-sharing-20260917.md) |
| User-facing benchmark YAML and JSON contract | [Single-task YAML](examples/experiment/benchmark.yaml) · [Result schema](schemas/experiment-result.schema.json) |
| Offline synthetic contract fixture | [Static YAML](examples/experiment/static.yaml) · [Static JSON](examples/experiment/static-result.json) |
| All EDA and preliminary-result charts | [Plain-language visualization guide](docs/experiment/visualization-guide-20260919.md) |
| Condition-level KT evidence, run identifiers and hashes | [Preliminary comparison evidence](docs/experiment/preliminary-comparison-20260916.md) |
| Exact execution, provenance, adapter and measurement contracts | [Static contract](docs/static-contract.md) |
| Accountless native execution and historical evidence | [Local native runner](docs/local-native.md) |
| Opt-in Foundry path, workload metrics and proposed baseline rule | [Native contract](docs/native-contract.md) |
| Current protocol, baseline, static compressors and open decisions | [Experiment record](docs/experiment/README.md) |
| Unsupported paths and readiness gaps | [Status](STATUS.md) |
| What may be shared and what stays private | [Publication grades](docs/publication.md) |

No raw run, prompt, recovery stash, imported tree or private work note is published automatically.
