# Native candidate-compression experiment contract

This is an implementation and pre-execution design contract, **not a native
experiment result or approval to call a model**. The optional Foundry path is
separate from the legacy local-model runner and the frozen static demo.

## Fixed comparison and gates

`run.py native` runs the existing five purpose-selected Terminal tasks with
Harbor 0.22.0 / the instrumented Terminus 2 agent. All conditions use the same
pinned task images, instructions, native tests, model settings, observation
policy, transport and metrics, including the same approved verifier revision. The order is **none baseline, then squeez,
Headroom and LLMLingua-2 comparisons**. Each comparison uses the baseline's
complete repetition count. There is no delete-all arm. This runner does not run
DeepSWE or a substitute benchmark.

The reviewed squeez 1.48.4 profile is `wrap "cat input.txt"`, with a fresh private
HOME/CWD per candidate. In the audited corpus it retained the **first 30 content
lines and deleted the suffix**, sometimes also removing a blank line. It is a
lossy truncation intervention, not a lossless character codec. A universal
`--full` switch is not part of this contract. Complete stdout, including tool
metadata and recovery notices, reaches the agent and counts toward local size.

Raw originals are retained privately for auditing, but **no recovery tool is
exposed to the agent**. A recovery notice is not proof of an available retrieval
path. The agent can still rerun commands or reread files through its terminal;
those actions must be counted, not assumed free. All conditions keep Harbor's existing
10,000-byte middle-elision behavior. Pre-Harbor terminal output is recorded
separately so that loss by Harbor is not attributed to squeez.

Headroom 0.36.5 uses only the audited `compact_lossless(text, "paths")` helper.
It factors repeated directory prefixes, accepts a change only when UTF-8 bytes
decrease without fewer displayed lines, and checks `path_unheading` against the
original bytes on every call. This restricted profile is not Headroom's default
router or a measurement of the whole product.

LLMLingua-2 0.2.2 uses the large MeetingBank checkpoint at the pinned revision
and `rate=0.5`. It selects source tokens to retain; it is a lossy token-selection
compressor, not a generated summary. Eight offline Python 3.10 workers load one
model copy each and accept at most one request per worker. All eight workers run
the three fixed fixtures; a ledger mismatch or cross-worker output mismatch stops
the run. Pool wait, adapter execution and worker inference time are recorded
separately. The current native path does not impose a worker-response or pool-wait
timer, and every worker must complete its close handshake or report an explicit
process error.

The checkpoint loads from a verified local directory while the upstream 0.2.2
token-boundary branch reads its `model_name` string. After loading, the worker
binds that discriminator to the pinned public model ID instead of depending on
the VM directory name. The runtime record verifies the same ID.

LLMLingua receives the complete identified candidate in one inference call. The
adapter does not truncate it at the former 5,000-character boundary. The event
records source, worker-input and output SHA-256 plus character, UTF-8 byte and
line counts; discarded-suffix fields remain empty for schema continuity. This
is an adapter policy, not behavior supplied by LLMLingua.

The template at `ledgers/native.template.toml` is deliberately unapproved and
not runnable. Before execution it needs an explicit rule/execution approval
reference, current rates with a source/check time, a deployment coordination
reference and a reporting target. The reporting target is not a process timer.
The ledger records provider throughput limits and service errors as external
constraints and fixes eight simultaneous native trial processes. These are
deployment constraints and comparison controls, not a harness cost or time stop.

The current native path does not impose a dollar stop, provider-call count,
completion-token cap, request-byte cap, phase timer, whole-run timer or deadline
timer. It omits Terminus 2 `max_turns`; Harbor 0.22.0 then uses its internal
default of 1,000,000, which remains a product implementation boundary and is not
described as unlimited. Provider context length, request size, throughput and
policy rejection remain external constraints. All calls, elapsed time and costs
are still measured.

Concurrency is a comparison control, not an experiment arm. The validator rejects
any value other than eight instead of issuing a warning that could be ignored.
Changing it requires an explicit contract/code change and a new execution SHA;
the none baseline and every comparison must use the same complete runner and queue
section. Each outer process still runs one Harbor trial and one agent at a time.

The baseline has a separate continuation gate after its first five complete
repetitions. If the range of passed-task counts is at most one, collection
continues to 10 without claiming stability. A range greater than one stops the
run for judge, runtime and design review instead of automatically spending the
20-repetition allowance. One point is one of five tasks; the threshold is a
predeclared judgmental operating limit, not an empirically calibrated confidence
bound. Earlier unchanged-call variability motivated having a gate but did not
numerically derive this threshold.

`--source-commit` is mandatory. The designated full SHA must match a clean HEAD
and the committed source inventory. Source, ledger and dependency-lock snapshots
travel with every run; trial and transport records carry the same SHA. The
benchmark checkout and every copied task file are compared against its pinned
Git revision. The environment image reference and Dockerfile are replaced by
the ledger's immutable image digest. The nginx verifier alone also receives the
hash-bound `nginx-request-logging-verifier-v2` revision: source SHA-256
`045cc716c14efde3b0dcff5fc7c85ec5d18bfc6ce66f8b40a418fa2a3a4acda0`
must produce effective SHA-256
`20812107bc3bfc541728a2d10e3da0552e907d949e1347a03d33aa26954f8902`.
It accepts the equivalent `$name` and `${name}` Nginx variable forms; all other
native test text and instructions remain unchanged. Any source or effective-hash
mismatch stops preparation. The ledger, task-source record, summary and execution
record retain the revision. Native tests for all other tasks are unchanged.
Critical installed dependencies are checked against `uv.lock`.

## Transmission boundary

```text
native runner and source/ledger checks
  -> Harbor / LiteLLM / OpenAI SDK
  -> authenticated loopback proxy, separate route for each trial
  -> capture original JSON and identify source-bound log candidates
  -> common none/squeez/Headroom/LLMLingua-2 adapter and FrozenRequestGuard
  -> shared deployment RPM/TPM reservation queue
  -> verify the actual serialized bytes again, immediately before sending
  -> Foundry, raw response and usage capture
  -> native verifier, classified failure evidence and task metrics
```

The live policy is `echo_bound_terminal_logs_v2`. A candidate must follow an
assistant response actually received in that trial, match its echoed terminal
command, and fit a conservative command/output rule. Code reads, mixed code,
structured JSON/YAML, unknown commands, ambiguous boundaries and unmatched
output stay protected. A matching hash proves structural preservation, **not
that the classified log is semantically safe to discard**. The policy does not
widen itself to reproduce a historical candidate percentage.

Protected changes, unexpected settings or malformed JSON block transmission.
The run-wide stop latch also blocks queued requests, retries and later tasks.
The supervisor interrupts the Harbor process group and force-kills it if it
does not exit. Diagnostics preserve JSON paths, affected segments, first
differences and expected/actual hashes. Finished trial routes are closed;
response logging drains before metrics and final artifact hashes are collected.
With concurrent trials, requests already dispatched before a peer failure cannot
be recalled; this boundary is retained in the timestamps and transport records.

Each complete five-task repetition is also copied to a local managed-disk spool
through an atomic directory rename. Its tar payload contains the completed trial,
judge, request/response, source and adapter evidence available at that boundary.
A single background uploader uses the VM's system-assigned Managed Identity,
uploads the payload first and publishes `manifest.json` last. The manifest binds
the payload path, byte count and SHA-256 to the run, source commit, ledger and
repetition. Account URLs and spool roots come from `NATIVE_BLOB_ACCOUNT_URL` and
`NATIVE_BLOB_SPOOL_ROOT`; credentials and tokens are never written to the ledger
or result.

A Blob failure does not stop benchmark workers. The immutable local payload stays
in the spool while bounded retries record attempt times and a sanitized error
category. A preserved failed spool can be resumed with the same destination and
lineage checks. At run shutdown, unfinished uploads are a hard gate: the native
measurement becomes `retrieval_pending`, not complete. Reading every remote
manifest and payload checksum from the collection host remains an external VM
shutdown gate; the agent has no access to this result-recovery path.

Docker resource cleanup after a forced interruption is **not validated** by a
host process-group test. Harbor is configured to delete environments, but an
operator must check for leftover containers on the execution host. An HTTP
request already sent cannot be recalled; ambiguous failures retain unknown usage
and any explicitly labelled estimate rather than being retried as free calls.

## Units and task metrics

All metrics are collected for **all four** conditions from the same path.

| Field | Definition and boundary |
|---|---|
| `turns` | Recorded Harbor `source=agent` trajectory steps, including repair/confirmation steps when Harbor writes them; not HTTP attempts or unfinished steps |
| `logical_model_calls` | Requests received by the proxy, not appearances of the same conversation in saved history |
| `total_model_calls` | Every outgoing provider HTTP attempt, including bounded 429 retries; successful responses and deliveries are separate counts |
| `delivered_responses_without_separate_agent_step` | Delivery count minus native steps; Harbor can repair an output-length error inside a turn. This gap is recorded, not silently equated to turns |
| `provider_tokens.input_tokens`, `output_tokens` | Separate provider-reported usage totals; not a reconciled invoice. Missing usage is null with a known subtotal and unknown-attempt count, never an invented zero |
| `cached_input_tokens` | Observed cache-read usage; missing cache detail is null, not zero. Cache behavior is not controlled |
| `local_tokens.input_tokens` | `o200k_base` message-content tokens per sent attempt, excluding API role framing; retries count again |
| `local_tokens.output_tokens` | Visible assistant-content tokens; not hidden reasoning or provider-billed output. Unknown responses leave a subtotal rather than a complete total |
| `cost` | Usage multiplied by ledger rates, with unknown charges and input-only estimates kept separate; no invoice reconciliation claim |
| `same_command_reexecutions` | Sum of occurrences beyond the first for each byte-identical complete command block actually accepted by the terminal wrapper |
| `same_subcommand_reexecutions` | Additional conservative lexical count for shell units such as `find` inside `ls && find`; not proof of command completion or the same filesystem/cwd |
| `post_changed_output_*` | Repetition linked by command text and time to an earlier changed output; retained evidence, **not proof that truncation caused the repetition** |
| `compressor` | Candidate calls, changed occurrences, adapter wall time, worker-pool wait, adapter execution and LLMLingua worker inference; source/worker-input/output/discarded-suffix hashes and sizes stay in private transport evidence |
| `timing.compress_seconds` | Sum of measured compressor wall time, including worker-pool wait; concurrent calls can make the sum exceed run wall time |
| `timing.transport_seconds` | Client HTTP wall time minus provider-reported service TTLT when both are available; otherwise null with a known subtotal |
| `timing.model_seconds` | Provider-reported `engine_ttlt_ms`, converted to seconds; otherwise null with a known subtotal |
| `native_outcome` | Unmodified native binary reward plus failure categories, per-test evidence and integrity warnings |
| `concurrency`, `deployment_limits` | Fixed outer native-trial concurrency plus the ledger RPM/TPM, check time and source; written to both `summary.json` and `execution.json` and revalidated from the saved ledger |
| `retrieval` | Per-repetition local payload size/SHA, Blob names, attempts, sanitized failure category and ETags; payload-before-manifest ordering is recorded, while collection-host read verification remains an external shutdown gate |

Waits, control keystrokes, undecomposable scripts and uncertain submissions have
separate fields. Proposed assistant commands that never reach the terminal do
not count as executed. Lower input tokens alone do not establish savings: output,
retries, turns and command repetition may increase total cost.

## Proposed baseline calculation

`equal_half_support_v1_proposal` is a **predeclared operational stopping rule**,
not a statistical test of convergence, equivalence or noninferiority. Accept it
explicitly in the execution ledger before observing a baseline.

One repetition is all five fixed tasks, each with a valid native reward in
`{0,1}`. The primary quality unit is **passed tasks per five-task repetition**,
an integer from 0 through 5. Record the observed minimum/maximum/range, mean,
sample standard deviation, and per-task pass counts. Use the observed range as
the primary tolerance; standard deviation is descriptive, not a normality-based
threshold for this small, heterogeneous binary sample.

- At five complete repetitions, stop for design and runtime audit if the suite
  range is greater than one. A range of zero or one only permits continued
  collection; it is not stability evidence and does not replace the checks below.
- At 10 complete repetitions, compare repetitions 1–5 with 6–10. Stop range
  collection if suite minima/maxima match and each task has the same observed
  support (`{0}`, `{1}` or `{0,1}`) in both halves.
- Otherwise extend to **20 total**, comparing 1–10 with 11–20. If the same
  checks still fail, stop as inconclusive; do not collect 30 or change tasks.
- Matching supports do not imply equal frequencies. Half histograms and mean
  differences remain visible. An all-failing baseline or a full 0–5 range cannot
  detect useful degradation and is marked inconclusive, even if supports match.
- Every compressor uses the same complete repetition count as the accepted baseline.
  A suite count below the baseline minimum, or a failure on a previously
  always-passing task, is below the observed tolerance. Values above the baseline
  maximum require review rather than automatic attribution to truncation.
- Within-range observations are not proof of equal quality. Floor tasks cannot
  show further degradation. Zero actual interventions do not test an adapter's
  safety; unchanged short logs cannot establish that throwing away lines is safe.

Invalid/missing judge evidence, incomplete mandatory metrics, protection errors,
settings/model-revision changes, explicit process errors and ambiguous transport
failures stop the run. Elapsed time or accumulated cost alone does not. They are
not native zeros or grounds for replacing tasks.
Stored decisions and repetitions are reconstructed from per-trial artifacts on
verification; changing a summary alone cannot change the accepted baseline.

## Judge scope and known gaps

Terminal tasks define their own `tests/test.sh`; the selected five use pytest
exit status to write the native reward. Retain `result.json`, `reward.txt`,
`ctrf.json`, test stdout and process/exception evidence. Cross-check test counts,
duplicates, reward files and pass/fail consistency without loosening thresholds.

Failure categories are `wrong_answer`, `wrong_format`, `timeout`, `tool_error`
and `other`. They describe observed signatures, not a diagnosis that compression
caused a failure. Unclassifiable failures preserve the raw evidence and use
`other`; the agent's answer is not used to regrade a native failure.

The fixed judges are not complete semantic oracles. Known subcheck gaps include
unchecked user fields/conditional conflict checks in the merger, regex matches
inside nginx comments and no assertion that a new request appears in its log,
and acceptance of printed verification text by the certificate-script subcheck.
These do not demonstrate that an invalid solution passes **all** native tests.
The nginx variable-syntax correction does not close these other coverage gaps.
Keep scores from the original and revised verifier revisions separate and disclose
the applicable revision.

The actual DeepSWE wrapper resets test-patch files, applies the hidden patch,
and runs `/app/test.sh base` and `/app/test.sh new`. It rewards only two zero exit
codes; setup/patch failures are not model-quality zeros. Its wrapper does not
guarantee per-test structured failure records or nonzero test counts. A future
DeepSWE run needs mode-specific logs and framework reports before individual
causes/coverage can be certified. This five-task runner does not claim to have
executed DeepSWE, nor count a SWE-bench surrogate as DeepSWE validation.

## Resource and control boundaries

The runner schedules contiguous waves of at most eight native trials, including
across repetition boundaries. The queue holds an exclusive process lock on a
persistent, deployment-bound file and uses an internal thread lock for rolling
RPM/TPM reservations and provider cooldown. Every participating deployment caller
on that host must use the **same absolute queue path**, not a new file per run.
The process lock rejects a second uncoordinated runner rather than merging two
independent in-memory schedulers. It does not control unrelated callers on other
hosts or direct API clients. Record how deployment isolation/cooperation was
checked before execution.

Temperature 0 and reasoning effort none are checked on the wire and recorded,
along with provider-reported model revision/fingerprint. They do **not** prove
determinism, losslessness, immutable backend state or cache control. Baseline
repetitions precede comparison to measure observed variability; baseline-before-tools
ordering still permits temporal/backend drift, while requests within an arm may
overlap under the fixed concurrency. Record timestamps and per-call usage.

## Adapter prerequisites and fixed probes

The Headroom adapter loads the exact `lossless_compaction.py` extracted from the
0.36.5 wheel through `HEADROOM_LOSSLESS_MODULE`. Both the module and wheel hashes
are fixed in the ledger. The full package dependency tree is not imported by the
live runner.

LLMLingua uses `LLMLINGUA_PYTHON`, `LLMLINGUA_MODEL` and the existing
`TIKTOKEN_CACHE_DIR`. `requirements/llmlingua2-cpu.txt`, five model files, two
tokenizer tables, the worker source and their byte counts or SHA-256 values are
fixed. Before a native request can be sent, all eight fresh workers must reproduce
three checked fixture output hashes for a path listing, severity log and
package-install output. Cross-worker disagreement also stops before provider
access. The probes do not guarantee byte equality on another CPU or dependency
stack; they test it on the execution host instead of assuming it.

The frozen 107-occurrence development corpus contains **10**, not 12, candidates
over the former 5,000-character adapter limit. All 10 belong to
`log-summary-date-ranges`; they represent three unique inputs repeated across
historical requests. This recount describes the removed profile. The discarded
suffixes in that historical measurement contained later file-listing rows, and
two occurrences also contained all 10 later `find` paths. It is not evidence for
the current uncapped adapter.

The earlier static corpus measurement observed a mean **4.13 seconds per candidate
span** for LLMLingua-2 on an eight-vCPU host with one active compressor. That is
a planning input, not an intrinsic tool speed or an eight-worker live result.
The earlier plan was **46–48 minutes** for the three 10-repetition tool conditions,
or **53–56 minutes including a 10-repetition baseline**. It assumed the former
adapter profile. Current uncapped candidates, turns, candidate occurrences,
eight-worker CPU contention and provider waits can change it, so those values are
not a current schedule guarantee.

The eventual result must retain the static risk observations used to select this
condition: all 107 candidate occurrences kept their line counts, but none of the
2,375 nonempty source lines remained byte-identical; line boundaries therefore did
not preserve fields, identifiers or states. Examples lost `[ERROR]` and `[WARNING]`,
split `1.22.1` into `. 22. 1`, and removed `denied` from
`policy-rc.d denied execution`. The eight reviewed tools contained no validated
summarizer that preserves the meaning of arbitrary structured command output;
they truncated content, factored notation or selected tokens.

## Model-free validation and execution separation

```bash
uv sync --locked --extra native
LITELLM_LOCAL_MODEL_COST_MAP=true uv run --locked --extra native python -m unittest discover -s tests -v
uv run --locked --extra native python run.py native _work/native.toml \
  --source-commit "$SOURCE_COMMIT" --condition none --check
uv run --locked --extra native python -m src.adapter_preflight _work/native.toml \
  --source-commit "$SOURCE_COMMIT" --output _work/adapter-preflight/$SOURCE_COMMIT
```

`--check` validates local prerequisites only; it does not start Harbor, contact
IMDS/Foundry or call any provider model. The baseline check verifies artifacts
for all four conditions, not only the selected condition. The separate adapter
preflight sends eight synthetic candidates per condition through the common
recorder and protection guard, uses only an in-process synthetic response, and
constructs all eight LLMLingua workers. It verifies byte-exact system/task
instructions, file-read code and assistant history for every condition, then
injects a protected mutation and confirms that neither it nor later requests
reach the synthetic sender. It records software timings but is not a native
quality or provider-latency measurement. Both checks fail on a dirty or wrong
source tree; native execution also requires an approved, operational ledger and
the separate `--execute` flag. Every non-`none` condition requires `--baseline
runs/<id>`.
Do not run either arm until authorized. The loopback SDK, dummy process and
synthetic driver tests are software checks, not native quality/billing evidence.

Exit 0 means checks succeeded or the requested measurement completed; exit 2 is
a preflight/verification error; exit 3 denotes a stopped, inconclusive or
retrieval-pending execution.
Raw diagnostics and artifacts stay under ignored `runs/`. There is no automatic
native-results publisher, commit, push or repository visibility change.
