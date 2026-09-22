# Screening and Evaluation Reproducibility Contract

**Status:** The latest continuation run on 2026-09-15 UTC linked 16 prior formal `attempt` records read-only and executed 8 new attempts. The cumulative record contains 12 quality results and 11 completed technical exclusions; one record remains incomplete and stopped further scheduling. A separate single-task diagnostic, excluded from the formal denominator, completed save, restore, regrading, and remote Blob hash verification. A run missing evidence required by this contract is not included in the quality denominator.

## Units of Record

A `run` shares one task list, execution source commit, ledger, and execution manifest. A `trial` is the logical evaluation unit for one task, repetition, and condition. An `attempt` is an execution that actually starts within a trial. Within an attempt, each provider request has a unique request position and provider request ID.

Planned trial count and actual attempt count are not interchangeable. A preparation retry adds one attempt but does not add to the quality denominator or planned trials. Retries inside provider transport are also recorded as separate HTTP attempts and remain distinct from logical requests.

## Values Fixed Before Execution

- Full execution source commit SHA
- Raw ledger and its SHA-256
- Normalized task list and its SHA-256
- Model name, provider-reported revision, and request settings
- Agent, runner, task, and container-image SHA values
- Verifier source, command, direct dependencies, and revision SHA
- Compressor name, version, profile, application location, and artifact SHA
- Condition-order seed, generation method, every `trial` ID, and planned order
- Price-table currency, units, effective time, and source hash
- Reporting target, harness stopping policy, concurrency, and deployment TPM and RPM

Before execution, the source commit must match a committed, clean worktree. Execution stops if source or ledger changes during the run.

## `trial` and Request Evidence

The following is retained for every trial and attempt:

- Task ID, repetition number, condition, and planned and actual start order
- `trial` ID, `attempt` ID, and retry number
- Immutable artifact-manifest hash
- Execution identifiers for a fresh container and fresh workspace
- Start and finish times, process ID, exit code, and evidence of an actual timeout
- Provider request ID, HTTP attempt and status, and request and response SHA-256
- Full tool trace and assistant output
- Provider input, cached-input, and output tokens; local tokens; and calculated cost
- Per-command stdout, stderr, exit code, duration, and repeated-identical-command count
- Turns per task and total model calls
- Verifier stdout, stderr, exit code, per-test results, and native reward
- A replay bundle for the final workspace and container state read by the verifier
- Blob payload and manifest sizes, SHA-256 values, upload status, and verified-read status

A required value that is unavailable remains `null` or explicitly missing. Missing values are not converted to zero or a pass.

## Preparation Retry

Exactly one retry with the same artifact is allowed only when image or environment preparation fails before any provider call.

- Use a new `attempt` ID under the same `trial` ID.
- Use the same immutable artifact and hash as the first attempt.
- Do not reuse the failed container or workspace.
- Do not retry a quality failure, error after a provider call, timeout, verifier error, or evidence omission.
- Retain the time, cost, and errors of both attempts.
- If the second attempt is valid, include its quality result only once in the trial denominator.

Recovery that changes an artifact or setting is a new revision, not a retry. Stop the current run and begin with a new source commit and manifest.

## Interruption, Resumption, and Duplicate Prevention

The state database permits one trial for each `(task, repetition, condition)` and makes `(trial, attempt number)` and `(attempt, logical request, HTTP attempt)` unique.

An attempt in progress at interruption remains `paused`; it is not run again automatically. Resolve its state only after preserved evidence establishes provider-call status, result, and cost statically. Do not schedule the same trial under a new ID and double-count its denominator or cost.

Plans not started after the third quality failure are retained as `cancelled_by_futility`. Every attempt that actually started remains in cost accounting regardless of its result.

After a source-commit change, do not rewrite the SHA, state, or summary of prior state to fit the new code. The new run links the prior source commit, ledger hash, execution-manifest hash, task-image digest, trial and attempt IDs, judgment or technical exclusion, and Blob hash as read-only records. Link only evidence-complete results that did not cross the code-change boundary, and do not reschedule the same task and repetition in the new run. Accumulate all prior attempt costs, but count each completed trial only once in the quality denominator.

If an explicit provider rejection ends an attempt before the first grading, record unexecuted grading, restore, and regrading durations as `null` with a not-applicable reason. A completed technical exclusion requires the raw error, stage-level state, raw material that could be preserved, remote hash, confirmed cost, and unresolved-cost state. This exception does not permit unexplained missing evidence or a restore mismatch.

The decision at 2026-09-15 22:40 KST to remove limits remains only as a historical record for that run. Future paid execution follows the [schema version 4 safety policy](execution-safety-policy.md): 60 provider HTTP attempts per attempt, 2,048 output tokens, 8,000,000 request bytes, 2,400 seconds elapsed, and preapproved per-attempt and full-run calculated API cost limits and a UTC deadline. A limit stop is `technical_incomplete` with `unknown` quality. It is recorded as `budget_stopped` or `censored`, not changed to `wrong_answer`.

An accepted explicit `exit` command in a pre-fix run may also have ended the terminal session and caused the next command in the same response to be rejected before initial grading. Record this case separately. Only an existing attempt for which the raw RuntimeError, sent, accepted, and rejected command-trace states, native-result and trace SHA-256 values, completed state save, remote hash, and cost are all confirmed may be linked as a technical exclusion. Post-fix runs grade the current workspace after session termination, so this exception does not lower their quality-evidence requirements.

## Final Workspace and Verifier Rerun

Preserve the following state immediately before verification. Beginning with state-replay bundle revision 2, changed paths in the container writable layer are stored in one tar file with NUL-delimited boundaries, and mounts are ordered by target path.

- Relative paths, kinds, modes, uid and gid values, symlink targets, sizes, and SHA-256 values for workspace and mounted files
- Container-image SHA and changed or deleted paths and content hashes in the writable layer
- Service, process, container state, and logs read by the verifier
- Inspect records in which sensitive environment-variable values and host paths are replaced by SHA-256

Restore the saved state under the same image and verifier revision, then rerun the verifier once without a model call. The second run occurs after the first verifier completes and before the same container is removed. Harbor has no separate internal verifier-stage timer, but the outer supervisor's 2,400-second attempt limit and full-run deadline remain in force. Replay passes only when the restorable file-state hash, verifier source, command and dependency hashes, per-test pass or fail results, exit code, and reward all match.

Running-process memory is not reconstructed from a file archive. If the process list differs between the point before the first judgment and the point before file restoration, or if the socket lists omitted by the archive differ, do not rerun; classify the result as a state-restore failure. Matching lists still do not establish byte-for-byte equality of process memory.

A different judgment under the same state is classified as verifier variability. If state restoration is incomplete, model-run variability cannot be separated from verifier variability, so the record is excluded from valid quality results.

The 20-repetition baseline for the five previously selected tasks did not preserve the final workspace and container state under this contract. Those measurements remain valid within their original scope but are not reused for new screening.

## Blob Retention and Retrieval

Each result is first finalized atomically in a local spool on the execution VM. Upload the payload first and the manifest last. Do not mark the upload complete until each object has been read back and its size and SHA-256 verified.

Record start and success counts separately for payload write, manifest write, payload verification read, and manifest verification read. An operation that started without a confirmed success response remains cost-unknown. A successful retry does not turn the earlier unresolved operation into zero.

A network or Blob error does not immediately discard the model execution. Preserve the local payload and perform bounded background retries. If verification is still incomplete after the final flush, leave the state as `retrieval_pending`; do not mark it complete.

Shutdown order is:

1. Read every payload and manifest back from Blob and verify SHA-256.
2. Download the full-size result in a separate collection environment and verify the same hash.
3. Check for missing or duplicate trial, attempt, and request IDs and reconcile cost totals.
4. Confirm that each required verifier replay produces the same judgment.
5. Only then allow local spool cleanup and VM deallocation.

Do not use a Blob ETag as a content hash. Do not delete local evidence before remote hash verification.

## Cost Records

Record provider, VM, Blob-write, Blob-verification-read, and network costs as separate components. Apply the same currency and pricing time to all four conditions.

Allocate VM cost for an active interval across concurrent attempts. Do not multiply the full VM rate by every worker; the allocations must sum to the total cost of the VM's active interval.

If any cost component is unresolved, leave directly attributable total cost missing. Record the confirmed subtotal and number of missing components together. Do not represent actual zero spend and missing instrumentation with the same value.

When a continuation run changes the source commit, preserve previously confirmed costs and unresolved cost estimates with their original lineage. Do not convert them into a new run's balance or stopping value. Include prior costs in cumulative reporting, but do not add the same cost twice when combining costs linked to prior quality results with diagnostic costs.

Shared idle time, approval waits, one-time setup, and long-term Blob storage are separate items. They are excluded from primary evaluation cost but remain in the explanation of total operating cost.

## Reproducible Analysis

Fix the evaluation array in `repetition × task × four conditions` order. Resample `none` and the three compression conditions together within the same repetition to preserve pairing and their shared-`none` correlation.

Use separate purpose-specific seeds for the primary analysis and the block-length-2 circular moving-block bootstrap sensitivity analysis. Record base seed `20260915`, NumPy `PCG64`, 50,000 percentile-bootstrap draws, quantile method `linear`, and batch size in the manifest. Synthetic-data validation uses independent seed `2026091501`.

The analysis code, input array, result, and manifest record the execution source commit. Do not change the primary analysis's repetition count, threshold, or confidence interval in response to correlation or variance observed after evaluation.

## Public and Private Boundary

| Private Blob source | Permitted in public documentation |
| --- | --- |
| Account, tenant, subscription, and resource identifiers | Public benchmark, task, tool, and model names and public revisions |
| Endpoints, private hosts, and absolute paths | Public-repository relative paths and deidentified execution environments |
| Raw provider request and response IDs | Request counts, status distributions, and hash-comparison results |
| Full prompts, tool traces, and assistant output | Aggregate tokens, calls, time, and failure classifications |
| Raw final workspace and replay archive | Workspace hash and replay-judgment agreement |

Environment, tools, versions, dates, samples, denominators, model, concurrency, and pricing time are conditions required to interpret the numbers and remain in public aggregates. Identifiers and private locations are not mixed with reproducibility conditions.
