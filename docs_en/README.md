# English Documentation

This directory preserves the reviewed English documentation while the original
`docs/` paths continue to serve the Korean documents shared with the KT audience.

## Current follow-up

- [Follow-up study entry](experiment/02-follow-up/README.md)
- [Cache reuse summary](experiment/02-follow-up/cache-reuse/README.md)
- [SWE-Lancer summary](experiment/02-follow-up/swe-lancer/README.md)

These are independent substudies. The Cache attempt produced zero valid cycles,
and the SWE-Lancer attempt produced zero valid protocol traces. Neither record
supports an effect, ranking, stability, pass-rate, or model-quality conclusion.

## Preserved historical entry points

- [Repository overview](../README.md)
- [Exploratory data analysis](eda/README.md)
- [Historical experiment record](experiment/README.md)
- [First-study preliminary comparison](experiment/01-preliminary-comparison/README.md)
- [Examples guide](../examples/README_en.md)
- [Ledger guide](../ledgers/README_en.md)
- [Snapshot provenance and hashes](SNAPSHOT.md)

The historical experiment index and snapshot retain their reviewed bytes and older
status text. Use the current follow-up entry above for the later work.

## Post-snapshot measured results

The following complete reports were added after the preserved English snapshot and
are not part of its byte-identity inventory:

- [Cache reuse execution result](experiment/02-follow-up/cache-reuse/execution-20260923.md) —
  actual provider execution reached 18 successful calls, but the attempted
  cycle was invalid and produced zero valid cycles, so no cache comparison was
  produced.
- [SWE-Lancer fixed-trace result](experiment/02-follow-up/swe-lancer/fixed-trace-20260923.md) —
  two runner groups breached the one-execution contract and both timed out
  during sandbox startup, before any provider or grader call; zero valid
  protocol traces were produced.

Current English-only implementation guides remain at their established paths:

- [Runtime-owner handoff](../docs/runtime-owner-handoff.md)
- [Cache-reuse contract](../docs/cache-reuse.md)
- [Native execution contract](../docs/native-contract.md)
- [Accountless native record](../docs/accountless-native.md)
- [Local native record](../docs/local-native.md)
- [Local recovery contract](../docs/squeez-recovery.md)
