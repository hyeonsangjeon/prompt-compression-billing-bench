# Follow-up Study: Cache Reuse and SWE-Lancer Execution

After the [preliminary comparison](../01-preliminary-comparison/README.md) documented the
repository's input-compression paths, two questions still required separate executions.
Could repeated input processing be compared across reuse
and compression conditions? Could one fixed software task move through environment setup,
model and tool execution, and grading while producing an admissible trace?

These follow-up records sit together for navigation, not because they form one ranking or
performance comparison. The Cache execution depends on comparable requests and complete
comparison cycles. The SWE-Lancer execution depends on one fixed task following the
admitted execution, isolation, and grading protocol. Counts or failure states from one
substudy cannot be used as quality evidence for the other.

## Could reuse and compression be compared?

The Cache execution did not test whether a stored answer could be replayed. It asked
whether a provider could reuse processing for repeated leading input and whether reducing
the input with `squeez` changed that result. Reuse `0`, `1`, and `2` are not retry counts.
They are the planned sequence with zero, one, and two admitted matching predecessor
requests while the compression condition stays fixed.

The `none`/reuse-0 bundle completed. In the following `none`/reuse-1 bundle,
`cancel-async-tasks` reached its third logical request, but the predecessor execution had
only two requests for that task. There was no third request to pair. Validation stopped the
current request before provider dispatch, and the first attempted cycle remained invalid.
The provider returned `18` successful responses with usage observations, yet the valid
comparison-cycle count was `0`; those numbers describe different layers of the run.

The record therefore does not calculate a Cache effect, miss rate, savings, reuse-level
difference, or compression effect. Read the [Cache summary](cache-reuse/README.md) for the
sequence and denominators, then use the
[complete Cache report](cache-reuse/execution-20260923.md) for measurement conditions,
calculated cost, evidence hashes, and the public quotation boundary.

## Did the fixed software task reach model execution and grading?

The SWE-Lancer execution fixed candidate `28565_1001` and planned one path: prepare the
task environment, start the sandbox, let the solver use the model and tools, run the
grader, and seal the trace and cleanup. Instead, the runner left two separate output groups
against the one-execution plan. Both timed out while the sandbox was starting, before any
provider, model, API, tool, or grader dispatch.

Initial pre-dispatch verification passed `27/29` checks and failed `task.row` and
`image.config`. Owner-controlled corrections later produced `31/31`, but that later result
did not erase the first failed record or authorize the second runner group. The command
configured `disable_internet=true`, while the guarded start observed
`allow_internet=true`. The valid-protocol-trace count was `0`.

The two `correct=False` rows are startup-error placeholders, not graded failures. They do
not establish model quality, pass rate, ranking, stability, or representative cost. Read
the [SWE-Lancer summary](swe-lancer/README.md) for the execution sequence and the
[complete SWE-Lancer report](swe-lancer/fixed-trace-20260923.md) for the fixed conditions,
two-group evidence, and claim boundary.

## How to read zero and status values

The two zero-valid-result counts above are observations. They do not make every `0` in
these documents the same kind of measurement. Retry `0` is configured, while SWE's
calculated API cost of `USD 0.000000` is derived from a record with no provider dispatch.
`unknown`, `not_applicable`, `not_measured`, and `not_run` mean, respectively, not
established, not applicable, not measured, and not run. None is interchangeable with a
successful zero result.

## Reading paths

| Reader question | Start here | Complete evidence |
|---|---|---|
| Why was the Cache comparison invalid? | [Cache summary](cache-reuse/README.md) | [Complete Cache report](cache-reuse/execution-20260923.md) |
| How far did the SWE execution proceed? | [SWE-Lancer summary](swe-lancer/README.md) | [Complete SWE-Lancer report](swe-lancer/fixed-trace-20260923.md) |
| What preceded these follow-ups? | [Preliminary comparison](../01-preliminary-comparison/README.md) | [Preserved English experiment index](../README.md) |
| Why was the SWE candidate admitted? | [Historical candidate evaluation](../swe-lancer-candidate-evaluation-20260920.md) | The execution-admission boundary, not the later invalid trace |

## Historical boundaries

- “SWE-Lancer third-benchmark candidate” is wording retained in the earlier candidate
  evaluation. It does not create a new `03-` experiment or describe the later invalid
  trace.
- EDA rounds 1 and 2 classified and reviewed preliminary-study material. They are not
  numbered executions in this follow-up directory.
- The first-study trees, frozen English snapshot, restored Korean sources, existing
  figures, and measurement lineage remain in place.

The Korean current-study entry is [2차 연구](../../../docs/experiment/02-follow-up/README.md).
