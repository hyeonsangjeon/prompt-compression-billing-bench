# Runtime-owner handoff for zero-call admission

This guide maps the repository contracts to the material a runtime owner must
provide. It does not attest that a runtime, credential, endpoint, permission,
price, or private input currently exists. The canonical names and fixed values
come from [`config/cache-runtime-context.json`](../config/cache-runtime-context.json),
[`config/swe-lancer-carrier.json`](../config/swe-lancer-carrier.json), and their
validators. Older handoff aliases are not accepted in place of these names.

The two commands below perform admission only. They make no provider, model,
API, network, or grader call. A successful result means that current evidence
passed the applicable zero-call gate; it is not a runtime measurement or an
authorization to start a paid run.

## Evidence layers

| Layer | What it establishes | What it does not establish |
|---|---|---|
| Tracked source | The command, source file, owner role, canonical environment names, and validator behavior at this revision | That the command is deployed or usable in a runtime |
| Runtime-owner attestation and receipts | Time-bounded claims bound to the tracked definition and, for SWE-Lancer, the exact private input bytes | That a name-only environment entry is nonempty, authentic, or permitted unless the receipt records separate current evidence |
| Admission result | The validator's current `go`/`no_go` or `ready`/`not_ready` decision and sanitized side-effect accounting | Provider availability, model quality, grader outcome, usage, cost, invoice, or permission beyond the evidence checked |

A matching source or definition SHA-256 proves byte identity only. It does not
prove managed-identity permission, credential validity, endpoint reachability,
paid outbound access, retention, cache support, or carrier readiness. Keep
actual paths, endpoint values, credential values, task bodies, solver content,
catalog content, and review bodies in the private runtime.

## Cache runtime inputs

The project command identity is the `CACHE_RUNTIME_PYTHON` executable followed
by the fixed arguments `-m src.cache_runtime_context`. The identity kind is
`repository_regular_file`, the source is `src/cache_runtime_context.py`, and the
owner role is `runtime_owner`.

### Cache handoff environment

| Environment name | Runtime-owner material | Read behavior |
|---|---|---|
| `CACHE_RUNTIME_PYTHON` | Python 3.12-or-newer executable for the sanctioned process | Used only as the executable in the command |
| `CACHE_RUNTIME_CONTEXT_ATTESTATION` | Path to one fresh private cache attestation | Read as a regular JSON file before the other private inputs |
| `CACHE_REUSE_LEDGER` | Path to the current approved private cache ledger derived from [`ledgers/cache-reuse.template.json`](../ledgers/cache-reuse.template.json) | Read as a regular JSON file after attestation succeeds |
| `CACHE_RUNTIME_FACTS` | Path to the current 14-row runtime-facts record | Read as a regular JSON file; missing, partial, and unverified rows remain non-green |
| `NATIVE_CACHE_LEDGER` | Path to the exact native ledger used by the proposed cache run | Read and checked against the cache ledger |
| `CACHE_REUSE_DOCTOR` | Fresh private result path | Reserved without clobbering and written with mode `0600` |

### Cache doctor-observed environment

The cache doctor also records name-only presence for the seven environment
names pinned by the current cache and native ledgers. It does not record their
values.

| Environment name | Current role |
|---|---|
| `FOUNDRY_ENDPOINT` | Provider endpoint named by the cache and native ledgers |
| `TERMINAL_BENCH_ROOT` | Native benchmark root |
| `TIKTOKEN_CACHE_DIR` | Pinned tokenizer cache |
| `FOUNDRY_QUEUE_STATE` | Shared queue-state file |
| `NATIVE_BLOB_ACCOUNT_URL` | Native result-retrieval account address |
| `NATIVE_BLOB_SPOOL_ROOT` | Native result-retrieval spool root |
| `SQUEEZ_BINARY` | Pinned squeez executable |

Membership alone does not prove a nonempty value or working access. In
particular, `FOUNDRY_ENDPOINT` presence does not prove authentication,
managed-identity permission, deployment access, or API compatibility.

### Cache runtime attestation fields

The attestation must contain exactly these fields. A UTC timestamp is an
ISO-8601 string with a UTC offset. The interval must satisfy
`observed_at_utc <= current time <= valid_through_utc`, and
`valid_through_utc` must be later than `observed_at_utc`.

| Field | Type | Contract |
|---|---|---|
| `schema_version` | integer | Exactly `1` |
| `kind` | string | Exactly `cache_reuse_runtime_context_attestation` |
| `observed_at_utc` | UTC timestamp | Observation time for this owner statement |
| `valid_through_utc` | UTC timestamp | Expiry for this owner statement |
| `definition_sha256` | string | Lowercase SHA-256 of the raw `config/cache-runtime-context.json` bytes |
| `SANCTIONED_PROJECT_RUNTIME_CONTEXT_COMMAND` | object | Exactly repeats the command object in the tracked definition |
| `SANCTIONED_PROJECT_RUNTIME_CONTEXT_IDENTITY_KIND` | string | Exactly repeats `repository_regular_file` from the definition |
| `SANCTIONED_PROJECT_RUNTIME_CONTEXT_IDENTITY_SOURCE` | string | Exactly repeats `src/cache_runtime_context.py` from the definition |
| `SANCTIONED_PROJECT_RUNTIME_CONTEXT_IDENTITY_SHA256` | string | Exactly repeats the tracked source-file SHA-256 from the definition |
| `SANCTIONED_PROJECT_RUNTIME_CONTEXT_OWNER` | string | Exactly repeats `runtime_owner` from the definition |

The cache attestation binds the definition and launcher identity. It does not
contain fingerprints for the three doctor inputs. After attestation succeeds,
the launcher separately records the byte count and lowercase SHA-256 of the
cache ledger, runtime facts, and native ledger in its private sanitized result.
The committed
[`runtime-context-attestation.template.json`](../fixtures/cache-reuse/runtime-context-attestation.template.json)
is deliberately expired and is not operational evidence.

### Cache structural eligibility decision

`CACHE_RUNTIME_FACTS` must include `eligibility_contract` before
`R02_SERIALIZED_PREFIX_CONTRACT` can be verified. The object is a private,
versioned decision overlay; it does not change
[`ledgers/cache-reuse.template.json`](../ledgers/cache-reuse.template.json). Its
top-level fields are `schema_version`, `kind`, `decision_version`,
`decided_at_utc`, `screening_source_commit`, `screening_evidence_sha256`,
`screening_launches`, `provider_cache_threshold_tokens`,
`screening_token_unit`, `selection_timing`, `primary_estimand`,
`ineligible_cache_result`, `full_bundle_estimand`,
`external_validity_limit`, `task_denominators`, `raw_content_stored`,
`provider_model_api_calls`, `rows`, and `decision_sha256`.

Decision version 2 contains exactly ten rows: the five fixed tasks crossed with request
ordinals one and two. Each row contains `task_id`, `request_ordinal`,
`local_screening_prefix_tokens`, `stable_serialized_prefix_bytes`,
`capture_serialized_prefix_sha256`, `capture_request_sha256`,
`cache_eligibility`, `execution_bundle_included`, and
`primary_cache_estimand_included`. Both captures must have the same serialized
prefix hash within a task and ordinal. `local_screening_prefix_tokens` counts
only the common message-content prefix before the first launch-specific
terminal-state divergence, not the full dynamic message. Raw request content,
endpoint values, credentials, and private paths are not allowed.

The threshold is 1,024 local content tokens. The decision fixes two tasks in
the primary eligible stratum and three as `not_applicable`; all five remain in the
execution bundle. The decision SHA-256 is calculated over the canonical object
without its `decision_sha256` field, and the R02 evidence hash must equal that
value. These diagnostics are not provider-billed token usage or evidence of a
cache hit. Because the stratification follows zero-call structural screening,
the primary result cannot be generalized to the full five-task bundle or other
workloads.

## SWE-Lancer carrier inputs

The project command identity is the `SWE_LANCER_RUNTIME_PYTHON` executable
followed by the fixed arguments `-m src.swe_lancer_carrier`. The identity kind
is `repository_regular_file`, the source is `src/swe_lancer_carrier.py`, and the
owner role is `runtime_owner`.

### SWE-Lancer handoff environment

| Environment name | Runtime-owner material | Read behavior |
|---|---|---|
| `SWE_LANCER_RUNTIME_PYTHON` | Python executable for the sanctioned carrier process | Used only as the executable in the command |
| `SWE_LANCER_CARRIER_ATTESTATION` | Path to one fresh private carrier attestation | Read as a regular JSON file before the ledger and receipts |
| `SWE_LANCER_ADMISSION_LEDGER` | Path to the exact private admission ledger derived from [`ledgers/swe-lancer.template.json`](../ledgers/swe-lancer.template.json) | Fingerprinted, parsed, and passed once to the model-free admission check |
| `SWE_LANCER_PROVIDER_CONTRACT_RECEIPT` | Path to the fresh provider-contract receipt | Fingerprinted and validated against the ledger |
| `SWE_LANCER_PRICE_RECEIPT` | Path to the fresh fixed-price receipt | Fingerprinted and validated against the ledger |
| `SWE_LANCER_OUTBOUND_RECEIPT` | Path to the fresh outbound-and-cleanup receipt | Fingerprinted and validated against the ledger and fixed image |
| `SWE_LANCER_DEADLINE_UTC` | Absolute UTC deadline within the ledger's wall-time and cleanup limits | Passed to the admission check; it is not a path |
| `SWE_LANCER_ADMISSION_RESULT` | Fresh private result path | Reserved without clobbering and written with mode `0600` |
| `OPENAI_API_KEY` | Inherited provider credential | Carrier admission checks name presence only; it does not read or store the value |
| `SWE_LANCER_DOCKER_HOST` | Inherited task-sandbox endpoint | Carrier admission checks name presence only; it does not read or store the value |
| `SWE_LANCER_SOLVER_PATH` | Path to the fixed private solver bytes | Read only after the ledger pin name and environment-name binding are validated |
| `SWE_LANCER_CATALOG_PATH` | Path to the fixed private catalog bytes | Read only after the ledger pin name and environment-name binding are validated |
| `SWE_LANCER_CREDENTIAL_REVIEW_PATH` | Path to current private credential-permission evidence | Fingerprinted against the corresponding ledger pin |
| `SWE_LANCER_NETWORK_REVIEW_PATH` | Path to current private network-isolation evidence | Fingerprinted against the corresponding ledger pin |
| `SWE_LANCER_CLEANUP_REVIEW_PATH` | Path to current private cleanup evidence | Fingerprinted against the corresponding ledger pin |

Presence of `OPENAI_API_KEY` or `SWE_LANCER_DOCKER_HOST` does not establish a
nonempty value, authentication, authorization, reachability, or a usable
carrier. The receipts and private admission evidence must independently support
the claim. The carrier never copies these values into its result.

### SWE carrier attestation fields

The SWE-Lancer attestation must contain exactly these fields and use the same
UTC interval rule as the cache attestation.

| Field | Type | Contract |
|---|---|---|
| `schema_version` | integer | Exactly `1` |
| `kind` | string | Exactly `swe_lancer_private_carrier_attestation` |
| `observed_at_utc` | UTC timestamp | Observation time for this owner statement |
| `valid_through_utc` | UTC timestamp | Expiry for this owner statement |
| `definition_sha256` | string | Lowercase SHA-256 of the raw `config/swe-lancer-carrier.json` bytes |
| `input_fingerprints` | object | Exactly the four entries described below |
| `SANCTIONED_SWE_LANCER_CARRIER_COMMAND` | object | Exactly repeats the command object in the tracked definition |
| `SANCTIONED_SWE_LANCER_CARRIER_IDENTITY_KIND` | string | Exactly repeats `repository_regular_file` from the definition |
| `SANCTIONED_SWE_LANCER_CARRIER_IDENTITY_SOURCE` | string | Exactly repeats `src/swe_lancer_carrier.py` from the definition |
| `SANCTIONED_SWE_LANCER_CARRIER_IDENTITY_SHA256` | string | Exactly repeats the tracked source-file SHA-256 from the definition |
| `SANCTIONED_SWE_LANCER_CARRIER_OWNER` | string | Exactly repeats `runtime_owner` from the definition |

`input_fingerprints` must have exactly `ledger`,
`provider_contract_receipt`, `price_receipt`, and `outbound_receipt`. Each value
must be exactly `{"bytes": <positive integer>, "sha256": <lowercase 64-hex
string>}` for the corresponding raw file bytes. The carrier reads each file as
a regular file and rejects any byte-count or SHA-256 difference as
`wrong_source`. The committed
[`carrier-attestation.template.json`](../fixtures/swe-lancer/carrier-attestation.template.json)
is deliberately expired and its one-byte fingerprints are non-operational.

## SWE-Lancer receipt contracts

All three receipts are private JSON objects with exact field sets. Their
observation and expiry fields follow the same UTC interval rule. The
`ledger_sha256` field is the lowercase SHA-256 of the exact raw admission-ledger
bytes supplied to the carrier.

A *bounded identifier* below is a string of 1 to 128 characters that starts
with an ASCII letter or digit and then contains only ASCII letters, digits,
periods, underscores, or hyphens. URLs, paths, whitespace, control characters,
and query strings do not satisfy that rule. A *positive decimal string* must
parse as a finite value greater than zero.

### SWE provider-contract receipt fields

| Field | Type | Contract |
|---|---|---|
| `schema_version` | integer | Exactly `1` |
| `kind` | string | Exactly `swe_lancer_provider_contract_receipt` |
| `observed_at_utc` | UTC timestamp | Receipt observation time |
| `valid_through_utc` | UTC timestamp | Receipt expiry |
| `ledger_sha256` | string | Exact raw admission-ledger SHA-256 |
| `provider_name` | string | Exactly `openai` and equal to `provider.name` in the ledger |
| `model_setting` | string | Exactly `openai/gpt-4o` and equal to `provider.model_setting` in the ledger |
| `deployment_identity_sha256` | string | Lowercase 64-hex identity for the actual deployment; no deployment value is stored |
| `api_version` | bounded identifier | Current API-version identity; URL- and path-shaped values are rejected |
| `reported_model_revision` | bounded identifier | Current reported revision and exact match to the ledger |
| `credential_environment_name` | string | Exactly `OPENAI_API_KEY` and exact match to the ledger |
| `endpoint_environment_name` | string | Exactly `SWE_LANCER_DOCKER_HOST` and exact match to the ledger |
| `credential_permission_verified` | boolean | Exactly `true`, but only after the runtime owner has current evidence |
| `credential_value_recorded` | boolean | Exactly `false` |
| `endpoint_value_recorded` | boolean | Exactly `false` |
| `provider_model_api_calls` | integer | Exactly `0` |

The validator cannot create permission evidence. Do not set
`credential_permission_verified` to `true` merely because this guide or a
source definition exists.

### SWE price receipt fields

| Field | Type | Contract |
|---|---|---|
| `schema_version` | integer | Exactly `1` |
| `kind` | string | Exactly `swe_lancer_fixed_price_receipt` |
| `observed_at_utc` | UTC timestamp | Receipt observation time |
| `valid_through_utc` | UTC timestamp | Receipt expiry |
| `ledger_sha256` | string | Exact raw admission-ledger SHA-256 |
| `currency` | string | Exactly `USD` |
| `input_usd_per_million_tokens` | positive decimal string | Exact match to the ledger input rate |
| `output_usd_per_million_tokens` | positive decimal string | Exact match to the ledger output rate |
| `price_source_url` | nonempty string | Exact match to the private ledger; kept out of the sanitized result |
| `price_source_revision_or_retrieved_at` | nonempty string | Exact match to the private ledger; kept out of the sanitized result |
| `provider_model_api_calls` | integer | Exactly `0` |

The receipt fixes inputs for later calculated cost. It is not provider-reported
cost and is not an invoice.

### SWE outbound receipt fields

| Field | Type | Contract |
|---|---|---|
| `schema_version` | integer | Exactly `1` |
| `kind` | string | Exactly `swe_lancer_outbound_cleanup_receipt` |
| `observed_at_utc` | UTC timestamp | Receipt observation time |
| `valid_through_utc` | UTC timestamp | Receipt expiry |
| `ledger_sha256` | string | Exact raw admission-ledger SHA-256 |
| `carrier_instance_identity_sha256` | string | Lowercase 64-hex identity for the actual carrier instance |
| `runtime_kind` | bounded identifier | Sanitized runtime type; URLs and paths are rejected |
| `platform` | string | Exactly `linux/amd64` |
| `image_manifest_digest` | string | Exactly `sha256:b6ee529bbc589b251d2e287aa28068ea4f7e69b3eac2927b393091ac968e7587` |
| `image_config_digest` | string | Exactly `sha256:3ac386d8f793eb2c3fdef76766b551bb2c04da8b7dd9703a01b561c293b82400` |
| `paid_provider_outbound_verified` | boolean | Exactly `true`, but only after current carrier evidence supports it |
| `cleanup_contract_verified` | boolean | Exactly `true`, but only after current cleanup evidence supports it |
| `credential_value_recorded` | boolean | Exactly `false` |
| `endpoint_value_recorded` | boolean | Exactly `false` |
| `provider_model_api_grader_calls` | integer | Exactly `0` |
| `network_calls` | integer | Exactly `0` |
| `survivor_count` | integer | Exactly `0` |

The fixed image identity is necessary but not sufficient. It does not prove
that the current carrier can start the image, reach the approved provider, or
clean up a future paid execution.

## Assembly and one-time checks

For the cache handoff:

1. Pin the clean source revision and use the tracked cache definition without
   changing its names or identity fields.
2. Obtain a current runtime-owner attestation that binds the raw definition
   bytes and repeats the five canonical `SANCTIONED_PROJECT_RUNTIME_CONTEXT_*`
   fields. This repository intentionally provides no command that manufactures
   a fresh ready attestation.
3. Provide the exact cache ledger, 14-row runtime facts with the hash-bound
   structural eligibility decision, and native ledger through the named
   environment entries. Keep actual values and paths private.
4. Choose a new output path that does not exist, then invoke the zero-call gate
   once:

   ```bash
   "$CACHE_RUNTIME_PYTHON" -m src.cache_runtime_context
   ```

For the SWE-Lancer handoff:

1. Pin the clean source revision and exact admission ledger. Complete private
   approvals and evidence pins only from current owner evidence; leave missing
   claims missing.
2. Bind each receipt to the raw ledger SHA-256 and satisfy its own current UTC
   interval. Do not put credential or endpoint values in a receipt.
3. Fingerprint the exact ledger and three final receipt byte sequences. Put
   those four positive byte counts and SHA-256 values in the fresh carrier
   attestation, then bind that attestation to the raw carrier definition and
   its five canonical `SANCTIONED_SWE_LANCER_CARRIER_*` fields. This repository
   intentionally provides no command that manufactures a fresh ready
   attestation or receipt.
4. Provide the fixed private solver, catalog, review evidence, absolute
   deadline, inherited credential and endpoint environment entries, and a new
   output path.
   Invoke the zero-call gate once:

   ```bash
   "$SWE_LANCER_RUNTIME_PYTHON" -m src.swe_lancer_carrier
   ```

Both launchers reject an existing output instead of overwriting it. Keep the
result in a private task-owned location. The result contains names, presence
booleans, UTC times, byte counts, hashes, bounded identifiers, contract flags,
and sanitized admission output—not credential values, endpoint values, or raw
private inputs.

## Decisions and failures

| Exit | Cache result | SWE-Lancer result | Meaning |
|---|---|---|---|
| `0` | `decision: go` | `status: ready`, `ready: true` | Current zero-call admission passed only |
| `3` | `decision: no_go` | `status: not_ready`, `ready: false` | Required evidence is missing, stale, invalid, not verified, or bound to different bytes |
| `2` | Source-integrity or no-clobber failure | Source-integrity or no-clobber failure | Stop; do not repair the record by weakening a validator or reusing the output path |

`missing` means a required name, file, field, or current claim was not supplied.
`stale` means the current UTC time is outside an evidence interval.
`wrong_source` means a definition, identity, ledger, receipt, or fingerprint is
bound to different bytes. These states are not zero and must not be promoted to
verified. Correct the minimum owner-controlled input and issue a new private
output path.

Even an exit `0` does not measure provider usage, local token counts, calculated
cost, invoice cost, model quality, grader quality, or live cleanup. Any later
provider-backed execution remains subject to its separate current approval,
all-green admission, fixed budget, deadline, retry, no-progress, concurrency,
and cleanup contracts.
