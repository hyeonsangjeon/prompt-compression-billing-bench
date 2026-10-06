# GBB Share Text: First-Study Compression and Cost

Copy-ready message:

> We compared no additional compression, squeez, Headroom paths-only, and LLMLingua-2 on the same 26 Terminal-Bench 2.1 tasks, one run per condition, using `gpt-5.4` records from 2026-09-16-17 UTC. Calculated API cost was $5.62 with no additional compression, $6.66 with squeez, $5.36 with Headroom, and $4.69 with LLMLingua-2. That is +18.6%, −4.6%, and −16.5% versus no additional compression, using the unrounded cost values.
>
> The observation is narrower than a savings claim. The tools changed input in 23 compressed-condition runs from 18 tasks. Those changed spans fell from 97,723 to 50,824 local tokens, about 48% lower, but that is not a 48% reduction in total input or cost. Across those 23 comparisons, cost went down in 14 and up in 9. Total input, cached input, output, and request counts all matter.
>
> In practice, colleagues should check their own workload's full provider input, cached-input subset, output tokens, request counts, retry behavior, and pricing terms before treating compression as a cost lever. The short report is [results-briefing-en.md](results-briefing-en.md), and the computation-friendly table is [results-briefing-en.csv](results-briefing-en.csv). The underlying first-study record starts at [01-preliminary-comparison/README.md](01-preliminary-comparison/README.md).

Vicky recommended sharing this summary. That recommendation is not evidence that she verified or endorsed the results.
