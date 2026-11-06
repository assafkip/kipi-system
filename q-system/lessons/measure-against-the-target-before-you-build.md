---
id: measure-against-the-target-before-you-build
kind: methodology
title: Measure against the target before you build
date: 2026-10-12
---

When the goal is "make the output look like this reference set", the first move is a measurement, not a fix. Build the comparison instrument before any generation change: take the reference set's own coding scheme (whatever dimensions actually define its shape) and score both the current output and the reference on it. The gap you get back is the spec. Without it, every round is a guess dressed as a fix.

HOW:

1. Define the instrument first. A defect count is not a comparison. Counting rule violations, filter hits, or gate passes tells you nothing about shape, because the shape lives in distributions the rules never mention (how often a given move appears, how pieces open, how they end). Pick dimensions you can score on both sides, score a sample of each, and report the two distributions side by side.

2. Re-measure every round, with the same instrument. If a round does not produce a new pair of numbers on the same axes, it produced no evidence. Compare to the reference, not to the previous attempt.

3. Make reviewer rulings cumulative in code. Append every approval and rejection to a ledger the generation step reads on every run: approved items as exemplars, rejected items with the stated reason. Rulings held only in a prompt or a brief get overwritten by the next round, so fixes replace each other instead of compounding.

4. Stop a worker on its second identical failure. Same failure twice means the diagnosis is wrong, not that the attempt needs another try. Count repeats yourself rather than waiting for the reviewer to notice, kill that worker, and send a fresh one whose only job is root cause.

5. Prove it by hand before automating. Produce output manually until it is approved, then automate the approved shape. Automating an unapproved shape multiplies a guess.

6. Convert style feedback into judgment, not filters. "Too technical" means write for a different reader; it does not mean ban a word list. Banned-word filters are measurable and therefore tempting, and they move the defect count while leaving the shape unchanged.

The cap: three rounds on the same class of fix, then stop and surface the diagnosis (what was tried, what failed, current state). A fourth round of the same class is the failure, not the fix.
