# SWE-Lancer Third-Benchmark Candidate Evaluation

## Conclusion

SWE-Lancer was classified as **deferred** in this review. The process reached the execution gate for one pinned task, but stopped before starting a worker, model, or provider because credential, provider pinning, and isolated-sandbox conditions were not met. There is no actual trace or grader result.

This conclusion is sufficient to close the candidate-evaluation card. It does not mean the candidate was “adopted for a limited third diagnostic.” A separate task must first satisfy the direct conditions below before one real execution is attempted again.

## Fixed Inputs

The selection rule was fixed from the single `ic_swe` example in the official README before task content was viewed.

| Item | Fixed value |
|---|---|
| Task | `28565_1001`, `split=diamond`, `task_type=ic_swe` |
| Upstream | `openai/frontier-evals` commit `51052cede8cc608f95bb00346635e03759013e5a` |
| Solver SHA-256 | `860c8bf2e65d02de9d768ff36fee6d80bb8d3dfa9955e6b83ad983ea49c62012` |
| Catalog SHA-256 | `5c3a6d4570b49be0d9fced98f5b32487420b16f25c98d6658830e31fa03f049a` |
| Selected row | 2,761 UTF-8 bytes, SHA-256 `ff7ea7f9d37739a30adff1d26f51eb3baee87a1cad421d4e1cc17c26adb19702` |
| Image manifest | `sha256:b6ee529bbc589b251d2e287aa28068ea4f7e69b3eac2927b393091ac968e7587` |
| Runtime | Python 3.12.13 |
| Provider/model setting | `openai/gpt-4o` |

The task body, reference answer, and raw catalog row are not published. The task ID in this document refers to the execution example published in the pinned upstream README.

## Execution Performed

A fresh UTC deadline was added to a private ledger linked to the execution approval, and `--execute` was invoked once. The full attempt limit was 4,920 seconds, cleanup reserve was 120 seconds, and calculated-cost limits were USD 20.00 for both the attempt and the run.

The gate ran for 4.417423510 seconds from 2026-09-20T03:28:18.991196619Z through 2026-09-20T03:28:23.409942658Z. It returned exit 2 and `technical_preflight_failure`. Source, catalog, selected row, runtime, and supervisor fingerprints matched, while seven pre-execution conditions remained unmet, so the process failed closed.

The unmet conditions were:

1. `OPENAI_API_KEY` was absent from the execution process
2. Actual access permission was unverified
3. The reported model revision was not pinned
4. Official input and output rates were not pinned
5. The price-source URL and revision or checked-at time were not pinned
6. No task-owned Docker/Alcatraz endpoint was available
7. Per-run network isolation and cleanup evidence was unavailable

An HTTP HEAD request for the selected image's registry manifest returned HTTP 200 and the pinned digest. The image body was not downloaded. This checked image accessibility and was separate from provider requests.

## Observed and Unobserved Values

| Item | Observation |
|---|---:|
| Logical model requests | 0 |
| Provider HTTP attempts | 0 |
| Tool calls / results | 0 / 0 |
| Retries | 0 |
| Trace events | 0 |
| Provider usage records | 0 |
| Grader | Not started |

With no provider request, calculated provider cost was USD 0.00. Rates and a price source were not verified, and no invoice was observed. Host compute cost was also not measured.

A control that reused the same result path was rejected with exit 3 and preserved the original bytes and SHA-256. The existing v4 red, v5 `not_ready`, and candidate-check records were not modified. Private judgment validation passed 18/18 checks, and historical-record preservation reconciliation passed 4/4 checks. These denominators count contract and preservation checks, not model or grader accuracy.

## Interpretation Limits

This record evaluates only the execution-readiness path for one task. It does not measure a SWE-Lancer trace, task quality, representativeness, benchmark pass rate, non-inferiority, population cost, or an invoice. Because no actual trace exists, it also cannot reproduce a request body, model-visible message, tool result, provider usage, or grader outcome.

## Separate Follow-Up Conditions

A separate backlog task must complete the following before execution is retried:

1. Inject a credential into the bounded process without recording its value and verify actual access permission.
2. Pin the model revision and input and output rates from reviewed official evidence.
3. Provide a task-owned Docker/Alcatraz endpoint for the pinned image digest and observe network blocking and cleanup.
4. Issue a new result path and a new absolute deadline for the same task.

The public template [`ledgers/swe-lancer.template.json`](../../ledgers/swe-lancer.template.json) has blank approval and private-evidence pins and is not executable. [`src/swe_lancer_admission.py`](../../src/swe_lancer_admission.py) first reserves the result path exclusively and checks source and evidence fingerprints and the deadline, but it does not start a worker or provider. The presence of configuration does not by itself establish isolation or permission.

### Current source-only carrier boundary

The current repository also defines a sanctioned private-carrier command in [`config/swe-lancer-carrier.json`](../../config/swe-lancer-carrier.json). The command takes no private paths or values as arguments:

```bash
"$SWE_LANCER_RUNTIME_PYTHON" -m src.swe_lancer_carrier
```

The carrier gate verifies its tracked source identity and a fresh runtime-owner attestation before reading the exact private admission ledger and three hash-bound receipts. Those receipts bind the provider, model revision, deployment identity, API version, fixed-price source, paid-outbound review, exact image, and cleanup contract to the same ledger. The gate records environment-name presence, byte counts, SHA-256 identities, and sanitized status only. It then invokes the existing model-free admission check once. Missing, stale, or mismatched evidence stops before that invocation, and the output remains no-clobber and owner-only.

This source boundary does not create, discover, or authorize a private carrier. It does not turn the completed hosted offline smoke into evidence for a current paid carrier, and it does not change this report's historical no-trace conclusion. A runtime owner must still provide the actual sanctioned context, a fresh attestation, the exact private inputs, and current receipts. Provider, model, API, and grader calls remain zero until that separate admission is green.

The machine-readable judgment is in [`data/experiment/swe-lancer-candidate-evaluation.json`](../../data/experiment/swe-lancer-candidate-evaluation.json). It excludes the private task body, raw trace, credentials, endpoint values, container identifiers, and execution paths.
