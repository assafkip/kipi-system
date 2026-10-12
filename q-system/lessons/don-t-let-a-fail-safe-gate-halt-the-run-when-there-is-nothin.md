---
id: don-t-let-a-fail-safe-gate-halt-the-run-when-there-is-nothin
kind: pattern
title: Don't let a fail-safe gate halt the run when there is nothing to degrade
date: 2026-10-12
---

Pattern: when a validation gate is designed to degrade gracefully (mark one claim as untestable, ship the rest), check what happens in the case where the gate runs as a fail-safe because nothing was classified. That is the case where the halt condition is easiest to misfire.

The failure mode: a gate is scoped per item, so a failed check downgrades only that item. A second branch handles the case where the gate ran by default, with no item attached to it. The reasoning there is 'there is nothing to degrade, so halt the whole run.' That reasoning confuses 'no item to mark' with 'no value to deliver.' The input with the least reason to need the evidence ends up with the strictest treatment, and the user gets no output at all.

How to apply it:
1. Enumerate the gate's inputs, including the empty or unclassified case, and write down the outcome for each. Look for any place where less information leads to a harsher result.
2. For every hard halt, ask whether a degraded path already exists elsewhere in the code. If it does, check that the halt branch can reach it. Often the graceful path is implemented but sits behind a condition the empty case never satisfies.
3. When a required input is absent, fall back to a run-level coverage note, such as 'this evidence was not provided, so these checks were skipped.' Do not discard the analysis. Reserve a whole-run halt for failures that make every result untrustworthy.
4. Make the missing-input reason precise. Distinguish 'the input was never supplied' from 'it was supplied but not read.' Never state one when you only know the other.
5. When a check is marked untestable, also suppress any observations produced from that unavailable evidence, so the output stays consistent.
6. Add a regression test for the empty or unclassified input through the full pipeline, asserting that a report is still produced and carries the coverage note.

Signal to watch for: a code comment that justifies a halt with 'there is nothing to degrade.' Treat it as a prompt to ask whether the output should degrade at the run level instead.
