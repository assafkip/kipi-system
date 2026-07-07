---
id: contract-the-assembled-artifact-not-each-defect-you-patched
kind: pattern
title: Contract the assembled artifact, not each defect you patched
date: 2026-07-06
---

When an output is assembled from several independent sources (computed values, generated prose, static text, human notes, separate rule engines), the failure mode is fixing quality one caught defect at a time. Each patch hardens the exact sentence that failed; the next run generates a new sentence from the same unguarded class, and it ships. You are chasing instances of a class instead of closing the class.

Two shifts fix this at the structure level.

1. Write an artifact-level contract of invariants that hold for the WHOLE output, stated as classes, not instances. Turn every past defect into the general rule it was an example of. 'This count was wrong once' becomes 'every quantity carries the scope/basis it was measured under.' 'This status line overclaimed' becomes 'every assertion is either factual or explicitly labeled a recommendation.' 'This question went unanswered' becomes 'every claim the consumer raised is answered or explained.' 'This aggregate lacked provenance' becomes 'every cohort/summary claim carries its N-of-total provenance.' The contract is the union of these classes.

2. Run the automated check on the FINAL assembled artifact, read the way its consumer reads it — not on the upstream inputs, observations, or job state. A consistency gate that inspects the source data cannot see a contradiction introduced during assembly, or a claim the template phrased badly. If a human is the only thing reading the composed output end to end, human catch is your only detection, and it is unreliable by design.

How to apply:
- Before adding another targeted patch, ask: what CLASS does this defect belong to, and is that class an invariant in the artifact contract? If not, add the class, not just the fix.
- Keep one place that enumerates the contract. Each invariant maps to a check that parses the assembled artifact.
- Point detection at the composed output. Verify the thing you ship, in the form you ship it.
- Treat a defect that a per-instance patch could fix as evidence the class is unguarded upstream — the patch is a symptom, the missing invariant is the cause.
