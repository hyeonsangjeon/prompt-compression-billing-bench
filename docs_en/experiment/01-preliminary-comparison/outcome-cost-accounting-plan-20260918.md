# Plan for Accounting Pass, Non-Pass, and Quality-Unknown Cost (As Recorded)

This plan was written before aggregation to connect AI execution cost not only to total
tokens, but also to **the number of verified passing results obtained**. A pass here is a
`pass` from the Terminal-Bench 2.1 built-in grader, not customer acceptance. It is not
claimed as a proxy for customer value or contractual acceptance.

> **Document status.** The original classifications, formulas, and completion conditions
> remain as a historical plan. Aggregation for the publishable scope was later completed.
> Confirmed results and the still-unallocated scope appear in
> [Cost Accounting by Outcome](outcome-cost-accounting-20260918.md). Do not cite this plan
> as though it were the current result.

## 30-Second Summary

- The **completed cohort** containing all four conditions has 26 tasks and 104 conditions:
  40 `pass`, 64 `wrong_answer`, and `$22.3333885` in calculated API cost.
- **Total calculated cost per passing condition** in this scope is
  `$22.3333885 ÷ 40 = $0.5583347125`. A presentation may show `$0.5583`, but retains
  the source value and formula.
- Its numerator includes both passing and wrong-answer costs in the completed cohort. It
  is not program-wide cost including every separately ended technically incomplete or
  operator-stopped attempt.
- Confirmed calculated API cost of `$87.771254` from five long-running attempts is cost
  before quality judgment. It is not combined with `wrong_answer` or the 104-condition
  quality denominator.
- At planning time, exact pass and wrong-answer costs required rejoining outcome-level
  costs in the private ledger. Three-decimal rounded costs in public tables are not summed
  and presented as precise values.

Aggregation under this plan made no new model calls. Its scope was limited to existing
ledgers and retained evidence.

## Why Measure This Value

Even if input tokens fall, total cost can rise when request count, retries, execution path,
or cache state changes. Conversely, total cost alone does not show how much produced
passes and how much was spent on wrong answers or technical incompletion.

The aggregation was designed to answer:

1. How much calculated cost produced one condition that passed verification?
2. How much was spent on normal non-passes after grading and on endings before quality
   judgment?

For presales and fixed-price work, these values can identify operating cost lost to retries
and incompletion. They do not turn benchmark passes into customer acceptance or generalize
the value to actual contract margin.

## Outcome Categories

| Outcome | Plain meaning | Quality denominator | Cost treatment |
|---|---|---:|---|
| `pass` | Execution, evidence retention, and grading completed; built-in grader passed | Included | Included in pass-attributed cost |
| `wrong_answer` | Normal grading completed but result was below criteria | Included | Included in normal non-pass cost |
| `wrong_format` | Normal grading completed but format was below criteria | Included | Included in normal non-pass cost |
| Technical incompletion | Communication, execution, or evidence retention did not finish before grading | Excluded | Included in pre-quality-judgment cost |
| Operator stop | Operator stopped an active run before quality could be determined | Excluded | Included in pre-quality-judgment cost |
| Cancelled before start | No actual attempt began | Excluded | Excluded from cost |

Technical incompletion and operator stops do not become wrong answers. Confirmed usage from
a late response remains in cost without creating a retrospective quality judgment.

In this document, a `trial` is one quality result defined by task, repetition, and
condition, while an `attempt` is an execution that actually runs that trial. Retries do
not add quality results, but every attempt that starts retains its cost.

## Values Already Fixed

### Completed Cohort

| Item | Value | Condition |
|---|---:|---|
| Tasks | 26 | Tasks for which all four conditions completed |
| Conditions | 104 | 26 tasks × 4 conditions, not 104 independent tasks |
| Passes | 40 conditions | Built-in task-grader `pass` |
| Normal non-passes | 64 conditions | All `wrong_answer` |
| Calculated API cost | `$22.3333885` | Provider usage × fixed price table; not invoice reconciliation |
| Total calculated cost per passing condition | `$0.5583347125` | `$22.3333885 ÷ 40` |

Recheck that condition-level calculated API costs `$5.61866`, `$6.663187`,
`$5.3620835`, and `$4.689458` sum to `$22.3333885`. This total and the 40 passes are
pinned in the [public aggregate JSON](../../../data/experiment/preliminary-comparison-summary.json).

### Long-Running Attempts Before Quality Judgment

| Item | Value | Treatment |
|---|---:|---|
| Long-running attempts | 5 | 4 operator stops and 1 HTTP response stall |
| Confirmed calculated API cost | `$87.771254` | Pre-quality-judgment cost |
| Separate estimate for request without usage | `$0.1294175` | Excluded from confirmed total |
| Quality | Unknown | Not counted as `pass` or `wrong_answer` |

`$87.771254` is not the program-wide sum of all pre-quality-judgment costs. Public
technical evidence contains additional separately classified technically incomplete
attempts. It is not called program-wide cost until every attempt is combined without
duplicates.

## Metrics Defined by the Plan

### 1. Total Calculated Cost per Pass in the Completed Cohort

```text
total calculated cost per pass in the completed cohort
= total calculated API cost of the 104 completed conditions
  ÷ number of passes in the 104 completed conditions
= $22.3333885 ÷ 40
= $0.5583347125
```

This metric can be published. It does not remove `wrong_answer` cost from the numerator.
It must state alongside the value that separate technically incomplete attempts are
outside the numerator.

### 2. Pass-Attributed Cost

```text
pass-attributed cost
= exact calculated API cost of completed conditions
  whose quality_result is pass
```

This value was not fixed at planning time. Three-decimal condition costs in public
technical tables are not precise aggregation inputs. The [aggregation result](outcome-cost-accounting-20260918.md)
separates the subset later linked exactly from the remaining unallocated scope.

### 3. Normal Non-Pass Cost After Grading

```text
normal non-pass cost after grading
= exact calculated API cost of completed conditions
  whose quality_result is wrong_answer or wrong_format
```

This cost remains visible rather than hiding failures. It is not combined with technical
incompletion cost.

### 4. Cost Before Quality Judgment

```text
confirmed cost before quality judgment
= confirmed provider + directly attributable VM + Blob and network cost
  of attempts that actually started but did not enter the quality denominator
```

When some cost is unresolved, report the confirmed subtotal and unresolved count together.
Do not convert unresolved values to zero.

### 5. Program-Wide Cost per Pass

```text
program-wide cost per pass
= confirmed cost of every attempt actually started within a fixed period
  ÷ deduplicated passing trials
```

This value is not calculated now. The numerator must combine the completed cohort,
retries, technical incompletions, and operator stops under one time and deduplication rule.
Dividing long-running cost outside the quality denominator directly by the 40 passes would
mix scopes.

## Fields to Join

In an environment with private-ledger access, join these fields at attempt level:

| Field | Purpose |
|---|---|
| `task_id`, `condition`, `trial_id`, `attempt_id` | Deduplication and attribution |
| `quality_result`, `evidence_disposition` | Pass, non-pass, and unknown-quality classification |
| `included_in_quality_denominator` | Quality-denominator membership |
| Confirmed provider cost and unresolved status | Calculated API cost |
| Directly attributable VM cost | Avoid double-counting overlapping runs |
| Confirmed Blob and network cost | Direct execution cost |
| Start, finish, and operator-stop status | Distinguish pre-start cancellation from an actual attempt |
| Price-table revision and `invoice_reconciled` | Separate calculated cost from an actual invoice |

Do not parse Markdown tables as source data. Aggregate from validated structured ledgers
and attempt evidence, then produce public JSON and documentation as presentation outputs.

## Aggregation Order

1. Fix the aggregation period and included execution revisions.
2. Link each `(task, repetition, condition)` trial to its attempts.
3. Exclude plans that never started.
4. Include confirmed cost from every attempt that started, regardless of outcome.
5. Count quality once for every evidence-complete trial.
6. Partition cost into `pass`, normal non-pass after grading, and before quality judgment.
7. Confirm that those three costs equal confirmed cost across included started attempts.
8. Keep calculated API cost, VM and Blob and network cost, and actual invoices in separate columns.
9. Exclude raw requests, responses, endpoints, credentials, and personal paths from public aggregates.

## Machine Validation

- The completed cohort must contain 26 tasks, 104 conditions, 40 `pass`, and 64 `wrong_answer`.
- Condition-level calculated API costs must sum exactly to `$22.3333885`.
- `$22.3333885 ÷ 40` must equal exactly `$0.5583347125`.
- Classified cost totals must equal confirmed cost of included started attempts.
- Do not count one trial's quality result once per attempt.
- Late-response usage may enter cost but cannot change the quality denominator.
- Keep unresolved cost, overlapping VM allocation, and unreconciled invoices as distinct states.
- Do not recreate exact totals from rounded public-table values.

If any check fails, do not publish cost by outcome. Retain only confirmed subtotals and the
blocking reason.

## Ten Experiment-Design Questions

| Question | Current answer | Gap |
|---|---|---|
| What decision does the result support? | Shows where operating cost went among passes, non-passes, and unknown outcomes | Contract-pricing criterion is separate |
| What would falsify the hypothesis? | Reject aggregation if classified costs do not reconcile to total cost | Before invoice reconciliation |
| How many axes moved? | Request count, cache, path, and concurrency varied in addition to compression | Cannot isolate compression causality |
| Was variability measured first? | Completed comparison ran once per condition | Repeated variance unmeasured |
| Was the judge validated? | Built-in grading is linked to restore and regrading | Known false-failure effect |
| Was configuration controlled? | Settings and provider-reported model were recorded | No guarantee of determinism |
| What is measured? | Links calculated cost to quality judgment | Not actual invoice or customer value |
| Does input favor one side? | Tasks were purpose- and candidate-focused | Not representative of a customer population |
| When does it stop? | Use existing evidence only; stop if join validation fails | No new model calls |
| Is it tied to a customer environment? | Public-benchmark grader pass | Not validated as a proxy for customer acceptance |

## Presentation Language

> Across 104 completed conditions, `$22.33` in calculated cost from API usage and a fixed
> price table produced 40 passes. Because costs from normal non-passes after grading were
> not removed, total calculated cost per passing condition in this scope was `$0.5583`.
> Separately, `$87.77` in confirmed calculated cost from five long-running executions
> that never reached quality judgment was not combined with wrong answers or the
> 104-condition quality denominator.

When asked, immediately add:

> A pass here is a Terminal-Bench built-in-grader pass, not customer acceptance, and cost
> is calculated by applying a price table to API usage rather than an actual invoice.

## Planning-Time Blocker and Current Status

At planning time, the external environment did not access the private attempt ledger. The
plan was to aggregate outcome-level cost in an approved internal environment using only
existing evidence. It explicitly avoided remote login or model execution before the
private connection was restored. A publishable partial aggregation and two-way
reconciliation were later completed, but the linkage needed for program-wide metrics
remains incomplete.

The plan's completion criteria were:

- Preserve exact outcome-level cost and included and excluded attempt lists in structured JSON.
- Make aggregation JSON, calculation code, and documentation pass two-way reconciliation.
- Separate publishable values from private-ledger values.
- Place unreconciled invoices, one run per condition, and known confounding beside the relevant numbers.
- Use only existing evidence, without a new model call.

## Evidence

- [Experiment-design review appendix](experiment-briefing-20260919.md)
- [Technical preliminary-comparison evidence](preliminary-comparison-20260916.md)
- [Public aggregate JSON](../../../data/experiment/preliminary-comparison-summary.json)
- [Evaluation protocol](../evaluation-protocol.md)
- [Reproducibility contract](../reproducibility-contract.md)
