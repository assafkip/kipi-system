---
id: check-a-slower-mode-against-the-hard-ceiling-and-wire-the-ch
kind: pattern
title: Check a slower mode against the hard ceiling, and wire the check in code
date: 2026-10-05
---

Failure class: a known constraint existed only as prose, in a place the current author was not reading, so it could not stop a repeat.

Setup: a richer mode of an external call (a details or extra-fields flag) roughly doubles per-call time. The call runs under a hard ceiling the caller does not control, such as a hosted API wall. Months earlier, one team measured the slowed calls, saw the timeout sit on the population mean, and wrote the full diagnosis as a comment. Later, a different team turned on the same kind of flag on the same host. Same symptom returned: some cells failed, a different set each run. Nobody had connected the flag to the ceiling in anything that executes.

Why it recurs:
- A comment is knowledge that only fires if someone reads that file. Edits happen elsewhere.
- Reporting a slowdown as a ratio ("2x slower") hides the real question: how much headroom is left under the ceiling.
- Failures that vary by run look like vendor flakiness, so people retry or blame the vendor instead of checking the budget.

What to do:
1. State every slowdown against its ceiling: measured mean and spread, configured timeout, and hard wall, side by side. If the mean plus one standard deviation crosses the timeout, the mode does not fit.
2. Put the constraint where the flag is set. Make the flag and its ceiling live in one config object, and add a startup or test-time check that fails when a flag marked as slow is enabled with a timeout inside its measured range, or without a fallback (chunking, async runs, or the flag off).
3. Record the measured range next to the flag as data, not as a comment, so the check can read it.
4. When a failure pattern is a random subset of units on each run, compare per-unit durations to the timeout before suspecting the dependency.
5. When you find a prior diagnosis in prose, treat it as a missing check: convert it into a test or validator in the same change.

Signal that the pattern applies: any option that adds work per call, any external system with a fixed wall, and any history of intermittent partial failures.
