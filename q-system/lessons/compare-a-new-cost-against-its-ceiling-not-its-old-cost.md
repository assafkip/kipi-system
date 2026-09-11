---
id: compare-a-new-cost-against-its-ceiling-not-its-old-cost
kind: pattern
title: Compare a new cost against its ceiling, not against its old cost
date: 2026-08-28
---

Turning on a richer mode of an external call (a "details" / "include extra fields" / "deep extraction" flag) makes each call slower. The instinct is to measure the change and judge whether the slowdown is affordable: "115s to 240s, about twice as slow, fine for a job that runs twice a week." That judgment is against the wrong number. The number that decides whether the change works is the CEILING the call runs under, and it is usually defined somewhere else.

Hosted job APIs, synchronous run endpoints, request gateways and CI steps all have a hard wall the caller does not own. Below the wall, cost is a preference. Within roughly one standard deviation of it, cost is a coin flip. The failure this produces is diagnostic poison: a run where a different subset of cells fails each time, which reads as an unreliable vendor rather than as a budget that no longer fits.

Four moves, in order:

1. **When a change makes something slower, the next line names the budget.** Not "2.1x slower" but "240s against a 290s timeout against a ~300s server wall". If you cannot state the ceiling, you have not finished measuring. A cost with no denominator is a number, not a measurement.

2. **Check whether the ceiling can be raised at all before planning to raise it.** A server-side wall cannot be bought past; raising the client timeout above it only means waiting for a run the server already killed. When the expensive mode's mean sits near an unraisable wall, the mode does not fit and no configuration value will make it fit. The remaining options are all "do less work per call": narrower scope, smaller batch, or splitting one call into several.

3. **An expensive mode ships with a cheaper fallback or it does not ship.** Retrying the identical expensive call is not a fallback; a call that ran out of budget will run out of budget again, so a retry count buys nothing but latency. Make the attempt sequence a ladder where each step is strictly cheaper than the last, so the unit degrades to partial data instead of to nothing. Losing one enriched field for one cell beats losing the cell.

4. **Record per-unit cost in the artifact, and flag the ones near the ceiling.** Without a duration on each record, a unit at 98% of budget and one at 15% are indistinguishable, so the margin can only be discovered after it is gone. With it, the margin is watchable, and a unit over a threshold gets reported as at-risk while it is still succeeding.

The verification is not "the timeout error stopped". It is: a unit whose expensive attempt fails still returns usable data through the cheaper path, and the artifact says which units took that path.

**The meta-lesson, which is why this one exists as an executable and not only as advice.** This exact trade had already broken a different lane in the same codebase eighteen days earlier, with the same shape and a different flag name. The diagnosis was written up correctly, in detail, as a comment inside the very file defining the timeout. It did not prevent the repeat, because a scar recorded as prose protects only the file it sits in and only the reader who happens to open that file. If a cost/ceiling relationship matters, it needs a test that fails: pin the ceiling, assert the expensive mode is opt-in rather than baked in, and assert the fallback path is genuinely cheaper. Prove each guard by restoring the original bug and watching it go red. A comment is a note to someone already looking in the right place, which is precisely the person who did not need it.
