---
id: fail-safe-gates-should-degrade-the-output-not-halt-the-run
kind: pattern
title: Fail-safe gates should degrade the output, not halt the run
date: 2026-10-05
---

When a validation step runs as a fail-safe because upstream classification returned nothing, check what its failure branch does. A common defect: the halt condition tests for a classified item that is, by construction, absent. The condition is false, so the failure falls through to the strictest path, a whole-run abort.

The empty-classification case is the one with the least reason to demand evidence. Nothing was alleged, so nothing needs proving. Treating it as the strictest case inverts the intent.

Check these three things:

- **Trace the empty input.** Feed the gate an empty classification and follow the branch. Ask which clause decides halt versus degrade, and whether it can be true when the list is empty.
- **Look for an unreachable graceful path.** The degrade logic often already exists further down: a list of untestable items carrying a reason, a helper that separates 'input absent' from 'input present but unread', and a step that suppresses conclusions drawn from untestable evidence. If the halt sits upstream of all of it, the graceful path is dead code for this case.
- **Decide per case, not per gate.** A missing input should halt only when something specific depends on it. Otherwise ship the partial result with an explicit coverage note naming what could not be checked and why.

The comment justifying the halt ('nothing to degrade') is a signal to inspect. 'Nothing to degrade' is a reason to ship with a coverage note, not to discard the analysis.

Test: a regression case with an empty classification and a missing optional input must produce a report with a coverage note, not an abort.
