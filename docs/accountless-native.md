# Accountless native quickstart

This path runs one real local-model invocation and applies the benchmark's
exact-answer judge. It does not use a cloud provider, API key, VM, container,
mock response, or synthetic task.

## Measured result

The bounded proof used one preselected GSM8K test record and the cached
`Qwen/Qwen2.5-0.5B-Instruct` revision
`7ae557604adf67be50417f59c2c2f167def9a775` on CPU. The corrected integrated
attempt completed in **7.761 seconds** and returned exit **1** with native verdict
`wrong_format`. Exit 1 is a completed non-passing benchmark verdict, not a
transport or harness failure.

| Attempt | Actual model invocation | Runtime import | Model load | Inference | Judge | End to end | Outcome |
|---|---:|---:|---:|---:|---:|---:|---|
| Preserved red | 1 | 4.998 s | 1.384 s | 1.992 s | not persisted | not persisted | Recorder finalization failed after inference; a model-free read of the preserved raw bytes produced `wrong_format` |
| Corrected integrated run | 1 | 3.913 s | 0.934 s | 1.360 s | 0.000188 s | **7.761 s** | Completed, exit 1, `wrong_format` |

Both invocations produced the same private-output SHA-256, but two observations
do not establish determinism. The first run remains a red result: the recorder
omitted `input_tokens` from its final event, then raised `KeyError` while writing
the result. The fix made that field required and added a model-free regression
test. It did not change the task, model, generation settings, or judge.

The sanitized record is
[`data/experiment/accountless-native-quickstart.json`](../data/experiment/accountless-native-quickstart.json).
Raw model output and host-specific paths are not published.

## What the five minutes include

| Stage | Cached proof |
|---|---|
| Repository clone and dependency installation | Excluded; not timed |
| Model download | Excluded; the exact snapshot already existed |
| Asset and runtime preflight | Included in the 7.761-second end-to-end clock |
| Fresh Python process and runtime import | Included |
| Fresh-process model load | Included |
| Local model generation | Included |
| Native exact-answer judge and result write | Included |
| Service startup | None; no service was used |

The bounded execution performed **0 model/runtime/package downloads**, **0
package installs**, and used **0 credentials**. The separate provenance review
read the pinned official GSM8K source and license over HTTPS. The execution
establishes that this cached accountless path can finish one
real model invocation and native verdict within the fixed 300-second attempt
limit. It does not establish cold setup time, model quality, representative
GSM8K performance, rank, non-inferiority, cost savings, or determinism.

## Fixed task and rights

The selection rule was fixed before reading any task record: use the first
record in the pinned official test source and do not switch after seeing the
model output or verdict.

- Official repository: https://github.com/openai/grade-school-math
- Revision: `3101c7d5072418e28b9008a6636bde82a006892c`
- Test source SHA-256: `3730d312f6e3440559ace48831e51066acaca737f6eabec99bccb9e4b3c39d14`
- Selected line SHA-256: `0eab733099856c87989785764a3523592926fb6c14d4eddd17308c4078515b6a`
- Judge source SHA-256: `c22b81bccaaebfd1123be296e8b3c3dca3ddc704c46b70bf4a50603bb627e197`
- License: MIT at the same revision; see
  [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) and
  [`third_party/licenses/gsm8k-MIT.txt`](../third_party/licenses/gsm8k-MIT.txt)

The fixture contains that existing public benchmark record. It was not written
or selected to favor this model. The judge follows the pinned GSM8K rule: find
the first `#### <number>` marker, remove commas, and compare the resulting
string exactly. Planted correct, wrong, missing-marker, comma, first-marker,
and invalid-reference controls run without a model.

## Prerequisites

Use the exact package versions in
[`requirements/accountless-native.txt`](../requirements/accountless-native.txt).
The measured environment used Python 3.10.12, Transformers 5.14.1, Torch
2.13.0, Tokenizers 0.22.2, Safetensors 0.8.0, Hugging Face Hub 1.23.0, and
NumPy 2.2.6. Installing them is outside the cached five-minute measurement.

Set `ACCOUNTLESS_MODEL_ROOT` to a local
`Qwen/Qwen2.5-0.5B-Instruct` snapshot at the ledger's exact revision. The
preflight verifies all seven required asset byte counts and SHA-256 values. It
does not download a missing or changed model file. Model weights are not distributed
by this repository.

## Run

Choose a new output root and run ID. Existing run directories fail closed before
model preflight.

```bash
export ACCOUNTLESS_MODEL_ROOT=/path/to/the/pinned/local/snapshot
export ACCOUNTLESS_NATIVE_OUTPUT_ROOT="$PWD/_work/accountless-native-runs"

python3 -B -m src.accountless_native check ledgers/accountless-native.json
python3 -B -m src.accountless_native run ledgers/accountless-native.json \
  --run-id accountless-native-001
python3 -B -m src.accountless_native verify \
  "$ACCOUNTLESS_NATIVE_OUTPUT_ROOT/accountless-native-001"
```

The worker sets the Hugging Face offline flags, passes `local_files_only=True`,
disables remote code, and blocks socket connection attempts. Generation uses
`max_new_tokens=128`, greedy decoding, seed 0, retry 0, a 300-second attempt
limit, and a 120-second no-progress limit. Recording a seed and greedy decoding
does not make the result deterministic.

## Exit codes and diagnostics

| Exit | Meaning | First file to inspect |
|---:|---|---|
| 0 | Completed native `pass` | `<run>/result.json` |
| 1 | Completed `wrong_answer` or `wrong_format` | `<run>/result.json` |
| 2 | Ledger, fixture, runtime, or model-asset preflight failed | `<run>/diagnostic.json`, when a run directory was reserved |
| 3 | Worker protocol, timeout, no-progress, import, load, or inference failure | `<run>/diagnostic.json` |
| 4 | Run ID already exists | Choose a new run ID; the existing bytes are unchanged |

`result.json` labels the record `measured=true`, `synthetic=false`, and
`projected=false`. Local tokenizer counts are not provider usage, and this
accountless execution has no provider-reported usage or calculated API cost.
The earlier static demonstration remains a separate synthetic contract fixture.
