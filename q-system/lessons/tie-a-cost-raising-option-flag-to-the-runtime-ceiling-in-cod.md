---
id: tie-a-cost-raising-option-flag-to-the-runtime-ceiling-in-cod
kind: pattern
title: Tie a cost-raising option flag to the runtime ceiling in code
date: 2026-10-04
---

A recurring failure: an option that raises per-unit work (extra detail, richer payloads, media or enrichment fields) pushes each unit's duration toward a hard timeout. The first time, the team diagnosed it correctly, measured the durations, saw the cutoff sat on the population mean, and wrote the diagnosis as a prose comment next to the timeout. The second time, in a different workflow using the same remote runner, someone enabled an equivalent option, hit the same wall, and repeated the mistake. The knowledge existed but nothing could trigger it, because it lived in a file the second author had no reason to open and no executable connected the flag to the limit.

What to do:
- Treat 'this option makes each unit slower' and 'the ceiling is N seconds' as one coupled fact. Encode it where the option is defined or enabled, not beside the timeout.
- Make the coupling executable: a table of measured per-unit durations keyed by option set, plus a check that fails or forces a fallback when the observed maximum, or the mean plus a safety margin, approaches the ceiling. A cutoff near the mean will sever about half of all runs.
- Fail loudly at configuration time. Reject or flag an option combination whose measured cost does not fit, instead of discovering it as intermittent partial failures.
- Read the failure signature as a clue. 'Some units fail, a different subset each run' with a stable ceiling points to a timeout sitting inside the duration distribution, not flaky infrastructure.
- When fixing one lane, grep sibling lanes that share the runner and the option class, and attach the guard to all of them.
- Prefer a fallback path (split the work, lower the detail, run asynchronously) over silently dropping the option.

A prose comment records a lesson. Only a check enforces it.
