---
id: a-halt-meant-for-degraded-input-fires-when-there-is-no-input
kind: pattern
title: A halt meant for degraded input fires when there is no input left to degrade
date: 2026-10-04
---

When a pipeline has a graceful-degradation path (ship the result with a coverage note, mark the unverifiable part as untestable), check that every branch that reaches a halt can also reach that path. A common gap: a gate runs as a fail-safe when classification returns nothing, but the code that decides whether to degrade or halt keys off a positive classification result. Empty classification makes the 'is this gated' test false, so the failure falls through to a whole-run halt.

The reasoning in the comment is usually honest: with nothing classified, there is nothing to degrade. The unexamined step is treating that as a reason to discard the whole analysis instead of shipping it with a note. The input with the least reason to demand a given piece of evidence (nobody alleged the thing the evidence would support) gets the strictest treatment in the system.

Second factor: the graceful path already exists a few lines below the halt, with a reason-builder that separates 'the input file is absent' from 'it exists but was not read', an explicit untestable marker carried forward, and suppression of anything the model narrated about untestable evidence. The halt branch simply cannot reach it.

How to apply:
- For every fail-safe gate, enumerate its triggers, including the empty-classification case, and trace each to either degrade or halt. Write down why each halt is justified.
- Key the degrade-or-halt decision on the same condition that turned the gate on, not on a narrower positive-match test.
- Reproduce with the empty-input case: no classified items, evidence file absent. Expect a report with a coverage note, not a halt.
- Treat a halt that fires only when there is nothing to protect as a smell. Fail-safes should be loosest where the stakes are lowest.
- Keep reason strings honest: distinguish 'missing' from 'present but unread' so the coverage note never claims more than was checked.
