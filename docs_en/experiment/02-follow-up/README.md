# Follow-up Study: Cache Reuse and SWE-Lancer Execution

This directory is the current entry point for two execution records produced after the
[preliminary comparison](../01-preliminary-comparison/README.md). “Follow-up study” is an
organizational boundary, not a claim that Cache reuse and SWE-Lancer form one comparison.
They ask different questions and use different denominators.

## Results first

### Cache reuse

**Question and conditions.** The plan combined `{none, squeez}` with reuse levels
`0 → 1 → 2`, five fixed tasks per cell, and concurrency `1`. It asked whether the run
could produce valid cycles for a cache comparison.

**Observation.** Eighteen provider calls succeeded, but the first attempted cycle became
invalid during request-prefix validation. The observed valid-cycle count was `0`.

**What this cannot establish.** The record does not establish a Cache effect, miss rate,
savings, reuse contrast, stability, or condition-level quality. See the
[Cache reuse summary](cache-reuse/README.md) for the actual sequence and denominators.

### SWE-Lancer

**Question and conditions.** The plan fixed candidate `28565_1001`, one execution,
concurrency `1`, and zero runner or SDK retries. It asked whether that execution could
produce one provider-backed sandbox and grader trace.

**Observation.** Two runner groups appeared against the one-execution plan. Both timed
out during sandbox startup, before provider or grader dispatch. The observed valid
protocol-trace count was `0`.

**What this cannot establish.** The record does not establish task pass or failure,
model quality, pass rate, ranking, stability, or population cost. See the
[SWE-Lancer summary](swe-lancer/README.md) for the failed checks and protocol limits.

The two zero-valid-result counts above are observations; this does not make every `0` in
these documents an observed measurement. Retry `0` is a configured value, and zero
calculated API cost is derived from recorded provider usage. `unknown`, `not_applicable`,
and `not_measured` mean, respectively, not established in this record, not applicable,
and not measured. They are not interchangeable with zero.

## Reading order

1. Use this page to identify each question and its claim boundary.
2. Read the substudy landing page for the conditions, observation, possible explanation,
   and limits.
3. Use the linked complete report when quoting values, evidence hashes, or measurement
   conditions.

The landing pages are short navigation summaries. The complete reports retain the
measurement definitions, usage and cost provenance, safety controls, evidence hashes,
and cleanup state.

## Historical boundaries

- “SWE-Lancer third-benchmark candidate” is wording retained in an earlier candidate
  record. It does not create a new `03-` experiment or rename the later invalid trace.
- EDA rounds 1 and 2 classified and reviewed preliminary-study material. They are not
  numbered executions in this follow-up directory.
- The first-study trees, frozen English snapshot, restored Korean sources, existing
  figures, and measurement lineage remain in place.

The Korean current-study entry is [2차 연구](../../../docs/experiment/02-follow-up/README.md).
