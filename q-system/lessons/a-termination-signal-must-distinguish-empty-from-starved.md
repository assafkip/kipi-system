---
id: a-termination-signal-must-distinguish-empty-from-starved
kind: pattern
title: A termination signal must distinguish empty from starved
date: 2026-07-06
---

An iterative search or expansion loop (crawl, frontier expansion, investigate-until-done, retry-until-clean) needs a stop condition, and the default one is "this round produced no new work." That condition is ambiguous: it fires both when the search space is genuinely exhausted AND when the round was starved — its inputs were degraded, rate-limited, or cut short before finishing. Treating starved as exhausted ends the job early and ships a partial result labeled complete.

Three moves:

1. Make the stop signal a typed value, not a boolean. Emit distinct states: EXHAUSTED (a full round ran on healthy inputs and surfaced nothing new) versus STARVED (the round ran on degraded inputs or was truncated mid-way). Only EXHAUSTED is a terminal success. STARVED retries or surfaces a warning; it never counts as done. A single 'empty' flag collapses the two and is read by everyone downstream as 'nothing more to find.'

2. Gate the terminal state on input health, not just on the output count. Before accepting 'no new work,' confirm the round actually completed on healthy collection: every source responded, no rate-limit backoff was active, no worker terminated early. If any input was degraded, an empty result is unproven, not final — an empty round on a broken pipe is silence, not absence.

3. Do not exclude freshly discovered items from the set you continue chasing. A newly found lead is almost always single-source at the moment of discovery, so a filter that only advances corroborated or validated items drops exactly the newest ones — and their absence starves the next round, which then trips the empty-stop. Carry unvalidated new items forward as candidates and validate them by chasing, not before.

The tell: a run that 'finished' is only proven finished if its last round ran on healthy inputs and its continuation set included the round's fresh, still-uncorroborated finds.
