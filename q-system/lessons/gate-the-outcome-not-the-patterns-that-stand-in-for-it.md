---
id: gate-the-outcome-not-the-patterns-that-stand-in-for-it
kind: pattern
title: Gate the outcome, not the patterns that stand in for it
date: 2026-07-06
---

When a fix has to hold a user-visible result, make a deterministic check assert that result end-to-end. Do not let the result depend on author discipline, prose in a plan, or a check that only looks for known bad patterns.

Three traps to close:

1. Test the seam the user hits, not a surface near it. "Done" and "verified" mean the exact path a user takes produced the correct output — the same deep link, the same entry point, the same state. Verifying an adjacent path that shares code proves nothing about the one that ships broken. Name the seam before you claim done, then drive it.

2. A pattern check is not an outcome check. Asserting the absence of three known anti-patterns can pass green while the feature is dead, because the check never confirms the positive result: that the thing renders what it returns, that the old surface was removed when its replacement shipped, that the new surface clears the quality bar. If a check can be green while the defect is live, it is watching the wrong thing. Add an assertion whose only way to pass is the real outcome.

3. A gate that covers future work leaves earlier work unowned. When you ship a gate that forces every new deferral to carry a tracked owner, the deferrals written before or around it are unowned by construction. Enumerating them is a one-time backfill, not something the forward gate will ever catch. Sweep the existing set the moment the gate lands.

Also pin the interpreter, toolchain, or environment your gate runs under. A check run with the wrong runtime can look dark (missing dependency) or falsely pass; make the registered command pin the exact environment so "it ran" and "it ran correctly" are the same statement.

The test for whether you are done: can the check be green while a user hits the defect? If yes, the check asserts machinery, not outcome — replace it with one that fails when the outcome is wrong.
