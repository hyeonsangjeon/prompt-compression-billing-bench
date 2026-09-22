# Stopping and Cost-Safety Policy for Future Paid Runs

**Scope:** This document applies to future paid provider runs that begin with ledger schema version 4. It does not change historical ledgers, measurements, hashes, or result JSON. Some approval fields in the public ledgers are blank, so those ledgers cannot be executed as-is.

## 30-Second Summary

- Each `attempt`—one actual attempt at one task—has limits on provider HTTP attempts, calculated API cost, elapsed time, request size, and output tokens.
- The entire run also has a calculated API cost limit and a UTC deadline. Execution stops before any provider call if either cost limit or the deadline is missing or unapproved.
- Reaching a limit is not a wrong answer. It is recorded as **technically incomplete** with unknown quality: `budget_stopped` when a cost or call budget stops it, and `censored` at another observation boundary.
- Waiting for natural termination is not allowed in the general comparison. A separate pilot would require a preapproved cost, maximum exposure, and manual stopping rule. The current runner has no entry point for that pilot.

## Enforced Limits

A `trial` is the quality unit for one task, repetition, and condition. An `attempt` is an execution that actually starts within a trial. A preparation retry leaves separate attempt costs, but contributes only one quality result to the trial.

| Boundary | Schema version 4 policy | Enforcement point | Result when reached |
|---|---:|---|---|
| Provider HTTP attempts per attempt | 60 | Before scheduling the 61st send | `budget_stopped` |
| Calculated API cost per attempt | Positive value approved before execution | Before scheduling each send and after reconciling each response | `budget_stopped` |
| Calculated API cost for the full run | Positive value approved before execution and no lower than the attempt limit | Before scheduling each send and after reconciling each response | `budget_stopped` |
| Attempt elapsed time | 2,400 seconds | While monitoring the execution process and request waits | `censored` |
| Full-run deadline | Explicit future UTC time approved before execution | While monitoring requests, waits, and processes | `censored` |
| Request size | 8,000,000 UTF-8 wire bytes | On receipt before transformation and immediately before sending | `censored` |
| Response output | Request `max_completion_tokens=2,048` | Fixed before sending and checked after usage is received | `censored` |
| Provider HTTP wait | 300 seconds | Each external HTTP attempt | `censored` or transport error |
| Transient HTTP attempts | 3 total | HTTP 429 handling | Technical error after exhaustion |
| One retry wait | Up to 120 seconds | Before applying `Retry-After` | `censored` |
| No-progress repetition | Fewer than 3 distinct progress signals in the most recent 8 logical requests | Before the next external send | `censored` |

Each 429 retry for the same logical request counts as a separate provider HTTP attempt. A progress signal is the SHA-256 of the most recent assistant command plan and the following user observation rather than their raw text. A request for which no signal can be produced remains in the window with the same “no signal” value.

Calculated API cost is provider usage multiplied by the fixed rates in the ledger; it is not an invoice. Before sending, the runner reserves cost using locally counted uncached input tokens, 4,096 tokens of protocol headroom, and the output limit. This reservation does not guarantee provider billing, so it is reconciled against actual usage after the response. Confirmed cost, unresolved exposure for responses without usage, and in-flight reservations all count when deciding whether another request is allowed. Unknown values are not converted to zero.

## Values Required Before Execution

The public `ledgers/native.template.toml` and `ledgers/screening.template.toml` show the fixed boundaries. The following values do not receive public defaults:

1. `max_api_cost_usd_per_attempt`: calculated API cost allowed for one actual task attempt
2. `max_api_cost_usd_per_run`: calculated API cost allowed for the entire new run
3. `run_deadline_utc`: an explicit future UTC deadline
4. `cost_limits_approved = true` and the actual approval evidence
5. Execution approval, price-source and checked-at evidence, and deployment-sharing coordination evidence

Both cost limits must be positive, and the full-run limit cannot be lower than the per-attempt limit. The three boundary values cannot be filled only in part. Execution also does not start if the deadline has passed or the price table is empty. A general comparison cannot increase or disable the remaining fixed boundaries. Any required change needs a new policy revision, source commit, and ledger review.

## Interpreting a Limit Stop

A limit stop is not a quality judgment such as `pass`, `wrong_answer`, or `wrong_format`.

| Record field | Value |
|---|---|
| Technical status | `technical_incomplete` |
| Quality status | `unknown` |
| Stop class | `budget_stopped` or `censored` |
| Censoring | `right_censored` |
| Quality denominator | Excluded |
| Automatic resend | None |

`budget_stopped` means the call-count or calculated-cost budget was reached. `censored` means observation ended at a time, request-size, output-token, retry-wait, or progress-signal boundary. Neither becomes a wrong answer under the built-in grader. If execution ended before the verifier ran, quality remains unknown.

## Evidence Retained

Each stop record preserves:

- The stop reason, whether its scope was the attempt or full run, the applied limit, and the observed value
- The last logical-request and HTTP-attempt positions, request SHA-256, and byte count
- The final response's HTTP status, SHA-256, and usage-confirmation state
- Confirmed calculated API cost, unresolved exposure, and any in-flight reservation
- Source commit; ledger and run-manifest SHA-256; and task, container, and workspace lineage
- Workspace preservation, state-replay manifest status, and whether the verifier ran

Published results exclude raw requests and responses, endpoints, credentials, tenant values, and personal paths. A technical stop is not promoted to complete evidence before state replay and remote-hash verification finish. If even the maximum exposure for a request without usage cannot be calculated when resuming a run, no new paid request is sent.

## Natural-Termination Observation Is a Separate Pilot

`natural_termination_observation` is always `separate_pilot_only` in a general-comparison ledger. A general comparison may not disable the limits above and wait for natural termination.

A separate pilot would need at least a preapproved calculated cost, maximum exposure, manual stopping rule, responsible operator, and evidence-retention scope fixed in an independent ledger and schema. This repository currently has no execution contract or entry point for that pilot, so natural-termination observation cannot run. A large number or blank limit in the general comparison is not a substitute.

## Historical Records and Remaining Limitations

- Schema version 1–3 ledgers and existing results remain verifiable as historical records under their original policies. New provider runs use only schema version 4.
- When historical results are linked read-only, a result affected by the 60-call or 2,048-output-token boundary is not reused as the same result in a new run.
- Cost reservation does not guarantee the provider's actual billing cap. Missing provider usage or different tokenization leaves unresolved exposure and requires invoice reconciliation.
- The progress signal is an operating rule that counts SHA-256 diversity in command plans and observation strings. A changed string does not establish meaningful progress and is not quality or completion evidence.
- The 2,400-second attempt limit covers the process boundary including preparation, agent work, and verification. It is not a limit on a specific stage or pure model time.
- Harbor's internal stage timers remain disabled to avoid truncating different evidence at different stages. The outer supervisor and protected loopback transport enforce the attempt and request boundaries above.

The exact machine contract is in [`execution-safety-policy.schema.json`](../../schemas/execution-safety-policy.schema.json), ledger validation is in [`execution_safety.py`](../../src/execution_safety.py), and runtime boundaries are in [`live_transport.py`](../../src/live_transport.py).
