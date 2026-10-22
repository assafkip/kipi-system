---
id: a-guard-that-reports-ok-may-not-cover-the-writers-you-just-a
kind: methodology
title: A guard that reports OK may not cover the writers you just added
date: 2026-10-04
---

When you ship new code that writes to a protected resource, run the project's own invariant checker against the new state before you call the work done. Do not trust that the checker covers your change.

The failure pattern: a static guard declares a rule such as 'nothing may write to resource X'. It enforces that rule by scanning for writers it already knows about. Your new writers reach X through a path the scanner does not model: an undeclared registry entry, a different call style, a config-driven target. The checker prints OK. The invariant is broken anyway, because OK means 'no violations among the writers I can see', not 'no violations'.

How to review for it:
- Read the guard's stated invariant, then list every write you actually shipped. Compare the two by hand, not through the guard's output.
- Run the guard, then diff its count of known writers against your own count. A shortfall means the guard is blind to some of yours.
- Treat a green result as a claim to test. Add a deliberate violation (a throwaway writer aimed at the protected target) and confirm the guard fails. If it stays green, the guard checks a proxy, not the property.
- Record manual bulk edits separately. A hand-run backfill sits outside every automated guard, so its only protection is the rollback files. Name that gap in the review.
- Separate the risk you were asked about from the risk that exists. Here the worry was model nondeterminism in the write path. The model was absent. The real integrity risk was a deterministic writer hitting a protected target unseen.

Rule of thumb: after adding a writer to a shared resource, make the guard prove it can see that writer, then make it fail on purpose once.
