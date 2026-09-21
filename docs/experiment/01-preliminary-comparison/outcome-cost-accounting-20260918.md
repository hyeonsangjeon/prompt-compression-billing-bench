# Cost Accounting by Outcome: What Was Established

This document aggregates costs from completed execution into **pass**, **normal non-pass
after grading**, and **ended before quality judgment**. It made no new model calls. Rather
than summing rounded values from public Markdown tables, it reads only provider usage,
fixed-price calculations, virtual-machine allocations, and object-storage (Blob) and
network records retained in machine-readable private ledgers.

## 30-Second Summary

- The primary completed analysis contains **26 tasks and 104 conditions** across all four
  conditions. The Terminal-Bench built-in grader recorded 40 passes, 64
  `wrong_answer` results after normal grading, and 0 `wrong_format` results. A pass here
  **does not mean customer acceptance**.
- Applying the fixed price table to provider usage for these 104 conditions gives
  `$22.3333885` in calculated API cost. Dividing by 40 passes gives the arithmetic value
  `$0.5583347125`, but its numerator includes non-passing execution cost, so this is not
  “cost attributed to passes.” Calculated API cost is **not an actual invoice**.
- Structured records link exact execution cost to outcome for only 9 conditions. Within
  them, confirmed calculated API cost is `$2.277506` for 4 passes and `$7.56232` for
  5 normal non-passes. The remaining `$12.4935625` across 95 conditions is not allocated
  by outcome.
- Five long-running executions ended before grading: four operator stops and one stalled
  HTTP response. Confirmed calculated API cost is `$87.771254`. A `$0.1294175`
  input-only estimate for one request without usage is excluded. Quality is unknown for
  all five.
- Therefore, **program-wide cost per pass remains unknown**. Confirmed subtotals can be
  reported, but missing links are not filled with zero or generalized into a total.

> **Scope for citation**
>
> `$0.5583347125` is the arithmetic result of dividing calculated API cost for 104
> completed conditions by 40 passes. Do not cite it as program-wide cost actually
> attributable to passing executions or as an invoice amount. Outcome subtotals are valid
> only within the nine exactly linked conditions.

## Terms in Plain Language

| Term | Meaning in this document |
|---|---|
| Task | One problem to solve |
| Condition | One execution of the same task under `none`, squeez, Headroom, or LLMLingua-2 |
| Pass | Result marked passing by the Terminal-Bench built-in grader; not customer acceptance or product-approval evidence |
| Normal non-pass | Execution and grading completed, with `wrong_answer` or `wrong_format` |
| Before quality judgment | Technical incompletion, operator stop, or HTTP stall before the first formal grading; not a wrong answer |
| Evaluation `trial` | Unit counted once for a quality result |
| `attempt` | Execution unit that actually starts and may incur cost; cancellation before start is counted separately at zero cost |

Quality is counted once per trial. Cost is counted once per attempt that actually starts.
The same attempt's cost is not included under both passes and non-passes.

## Calculation Method

### Measurement Conditions

| Item | Value used | Calculation unit | Missing |
|---|---|---|---|
| Quality denominator | 26 tasks × 4 conditions = 104 conditions | One per condition | Repeated-run variability |
| API | Provider-reported input, cached-input, and output tokens | USD | Invoice reconciliation |
| Price table | Input `$2.5`, cached input `$0.25`, output `$15` per million tokens | Fixed-price calculation | Contract discounts, taxes, and billing adjustments |
| Virtual machine | Confirmed directly attributable time or union of overlapping processes | USD | Outcome-level allocation for all 104 conditions |
| Blob and network | Recorded write, verification-read, and transfer operations | USD | Retention cost and uninstrumented network activity |

For each public usage record, the calculator multiplies `input - cached input`, cached
input, and output by their corresponding rates. A difference in any digit from the API
cost stored in the ledger fails validation. `unknown` and `null` states are not changed
to zero.

### Four Cost Types Remain Separate

1. **Calculated API cost** is provider usage multiplied by the fixed price table.
2. **Directly attributable VM cost** is compute cost that can be allocated without overlap
   to the scope.
3. **Blob and network cost** covers confirmed storage, read, and transfer operations.
4. **Actual invoice** means billing records issued by the provider and infrastructure
   vendors. This material was not reconciled against them.

Locally recounted tokens in changed spans are also separate. They describe the size of
text that actually changed; they do not replace total API usage or cost.

## Established Cost by Outcome

### 104 Completed Conditions

| Outcome classification | Exactly linked conditions | Confirmed calculated API cost | Per-condition value |
|---|---:|---:|---:|
| Pass | 4 of 40 | `$2.277506` | `$0.5693765` within the 4 linked cases |
| Normal non-pass | 5 of 64 | `$7.56232` | `$1.512464` within the 5 linked cases |
| Unallocated by outcome | 95 conditions | `$12.4935625` | Not calculated |
| **All 104 completed conditions** | **104 conditions** | **`$22.3333885`** | Simple division by 40 passes: **`$0.5583347125`** |

The accounting contract includes `wrong_format` under normal non-pass, although none
occurred among these 104 conditions. The 95 unallocated conditions have known quality
judgments—36 passes and 59 `wrong_answer` results—but complete structured links between
those outcomes and exact attempt costs were not retained, so cost is not assigned
arbitrarily between the two outcomes.

| Outcome classification | Directly attributable VM | Confirmed Blob and network | Invoice reconciliation |
|---|---:|---:|---|
| 4 linked passes | Unknown | `$0.0001728` | Not performed |
| 5 linked normal non-passes | Unknown | `$0.000216` | Not performed |
| 95 unallocated conditions | Unknown | Unknown | Not performed |

The nine conditions retain per-execution VM ledger values, but concurrent executions
counted overlapping VM time. Summing them would double-count, so they were not promoted
to directly attributable cost. The public JSON retains the raw observed subtotal as a
supporting value and leaves direct attribution as `null`.

### Five Long-Running Attempts Before Quality Judgment

| End state | Started attempts | Confirmed calculated API cost | Quality results |
|---|---:|---:|---|
| Operator stop | 4 | `$80.879013` | Unknown |
| HTTP response stall | 1 | `$6.892241` | Unknown |
| **Total** | **5** | **`$87.771254`** | **0** |

These five attempts actually started, so confirmed costs remain despite the lack of
results. Conversely, there were 0 cancellations before start and their cost was `$0`.
The final request in the stalled HTTP attempt did not return provider usage. Its
input-only `$0.1294175` estimate remains separately unresolved and is not included in
`$87.771254`.

| Cost component | Confirmed value | Interpretation |
|---|---:|---|
| Calculated API cost | `$87.771254` | Includes only responses with confirmed usage |
| Directly attributable VM | `$4.204009802011` | Union of the five task-process intervals |
| Blob and network | `$0.000054` | Includes only operations on retained attempt records |
| **Confirmed subtotal** | **`$91.975317802011`** | Excludes the unresolved request; not a final total |

## Two-Way Reconciliation

The public calculator totals once by outcome classification and again by full included
scope.

```text
exactly linked passes             $2.277506
+ exactly linked normal non-pass  $7.56232
+ unallocated completed quality  $12.4935625
+ before quality judgment        $87.771254
+ cancelled before start          $0
= included confirmed calculated API cost  $110.1046425
```

The opposite calculation, `$22.3333885 for 104 completed conditions + $87.771254 for
long-running attempts`, also equals `$110.1046425`. The generator and tests fail if the
two totals differ.

The public JSON also contains the partial subtotal `$114.309095102011` after adding VM,
Blob, and network components. Its scopes differ: API covers the 104 completed conditions
and five long-running attempts; direct VM attribution covers only the five long-running
attempts; and Blob and network cover 14 exactly linked records. It is therefore not a
final total cost.

## Observation, Possible Explanation, and Limitation

**Observation.** Within the nine exactly linked conditions, calculated API cost was
`$2.277506` for four passes and `$7.56232` for five normal non-passes. Confirmed
calculated API cost for the five long-running attempts before quality judgment was
`$87.771254`.

**Possible explanation.** Different task difficulty and run length may have produced
large differences in request count and API usage. The long-running attempts accumulated
many repeated actions before grading. This evidence does not isolate how much each factor
contributed.

**Limitation.** Completed conditions ran once each, without controls for cache, request
count, execution path, or concurrency. A known verifier false-failure case also existed.
The nine conditions are a convenience sample with retained cost links, not a
representative sample designed for all 104. The evidence therefore does not support
compressor ranking, compression causality, quality non-inferiority, or population savings.

## Decisions This Material Supports

- A reporting format that keeps quality outcomes separate from technically incomplete cost
- Keys that link trial quality to the cost of attempts that actually start in future runs
- A procedure that approves API, VM, Blob and network, and invoice-reconciliation status separately
- Which aggregate metrics remain withheld until missing links are supplied

## Decisions It Does Not Support

- Ranking compressors by value for cost
- A causal claim that compression changed quality or cost
- Actual billed cost per pass after product adoption
- Population savings for other tasks or customer data

Design gaps also remain. The decision this evidence would change and the falsification
criterion must be agreed before another run. Same-condition variability was not measured
first, and verifier validation and customer-data representativeness remain insufficient.
A resumed run should preregister cost and time limits, repetition count, cache and
concurrency controls, and the scope of invoice reconciliation.

## Public Evidence and Recalculation

- [Processed public ledger](../../../data/experiment/outcome-cost-evidence.json): exact outcome-and-cost linkage input without raw requests, responses, or private identifiers
- [Outcome-accounting JSON](../../../data/experiment/outcome-cost-accounting.json): public generated result
- [JSON Schema](../../../schemas/outcome-cost-accounting.schema.json): required fields, fixed values, and `null` boundary
- [Aggregation code](../../../src/outcome_cost_accounting.py): price-table recalculation, classification, and two-way reconciliation
- [Direct tests](../../../tests/test_outcome_cost_accounting.py): duplicate quality and attempt records, price drift, unresolved values, and document-contract checks
- [Technical preliminary-comparison evidence](preliminary-comparison-20260916.md): detailed observations for 26 tasks, 104 conditions, and 5 long-running attempts

The public input, generated result, and schema can be checked without calling a model or
provider:

```bash
uv run --locked python -m src.outcome_cost_accounting --check
uv run --locked python -m unittest tests.test_outcome_cost_accounting -v
```

Public files exclude raw requests and responses, endpoints, credentials, tenant values,
personal paths, and private execution identifiers. Program-wide cost requires structured
linkage for the remaining 95 conditions and other historical technically incomplete
attempts before it can be calculated.
