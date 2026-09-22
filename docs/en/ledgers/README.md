# Execution ledgers

- [`static.toml`](../../../ledgers/static.toml) is the ledger for fixed-input static measurement.
- [`demo.toml`](../../../ledgers/demo.toml) is an example ledger that checks the contract with synthetic data.
- [`native.template.toml`](../../../ledgers/native.template.toml) is the native ledger template that must be
  completed before a live model run. It separates the fixed schema-version-4 safety limits
  from the initially empty cost approval and UTC deadline.
- [`screening.template.toml`](../../../ledgers/screening.template.toml) fixes the Terminal-Bench 2.1
  screening rules and the schema-version-4 termination and cost-record fields.
- [`recovery.template.toml`](../../../ledgers/recovery.template.toml) is a non-operational template that
  fixes local squeez source-recovery, lifetime, and authentication boundaries while
  external exposure is disabled.
- [`accountless-native.json`](../../../ledgers/accountless-native.json) is the cached quickstart ledger. It
  fixes one public GSM8K item, local-only Qwen2.5 0.5B asset and runtime fingerprints,
  generation settings, a 300-second attempt limit, a 120-second no-progress limit, and
  zero retries. It is separate from the existing Ollama ledger and does not authorize a
  model download or package installation.
- [`cache-reuse.template.json`](../../../ledgers/cache-reuse.template.json) is a non-operational template
  that fixes the `{none,squeez} × {0,1,2}` cache-reuse axis for a five-task bundle,
  concurrency 1, the 10→20 stability rule, distinct provider/local/computed/invoice
  units, and 14 runtime gates. It remains `no_go` until every gate and separate leader
  approval are verified.

Templates record environment-variable names, never credential values.
