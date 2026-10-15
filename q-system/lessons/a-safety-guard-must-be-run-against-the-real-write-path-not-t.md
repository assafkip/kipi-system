---
id: a-safety-guard-must-be-run-against-the-real-write-path-not-t
kind: methodology
title: A safety guard must be run against the real write path, not trusted from its own report
date: 2026-10-05
---

After shipping an automation, an adversarial review found that the project's own writer-registry check printed OK while two newly added writers were hitting a protected, live target that the check's own header said must never be written.

The general pattern: a guard that enforces an invariant can pass for the wrong reason. Its OK means 'the rules I know how to evaluate found no violation', not 'the invariant holds'. If new writers are not registered with the guard, or the guard's discovery logic never sees them, the guard is silent while the invariant breaks.

How to review for this:
- Start by asking whether the risky component can even reach the data. If the write path has no model or non-deterministic step, say so first, so the review spends its time on the real integrity risks.
- Read the guard's stated invariant (its header or docs), then independently find every writer to the protected target by searching the code and the deployed workflows for the target's identifier. Do not use the guard's own inventory as the list.
- Compare the two lists. Any writer the guard did not count is a finding, and the guard's pass is evidence about the guard, not about the system.
- Run the guard and record its exact output next to your independent count (here: it reported a writer total and OK while the real set was larger).
- Check the actual data: count the cells or rows written to the protected target during the run, and note any prior manual or bulk edit that has no protection except rollback files.
- Fix both halves: register or block the undeclared writers, and make the guard derive its writer list from the code or deployed config so a new writer cannot be omitted.

Rule of thumb: every claim in a review should come from running something. A guard's green result is a claim to test, not a result to cite.
