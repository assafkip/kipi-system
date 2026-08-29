---
id: a-safety-property-enforced-at-n-sites-is-not-a-chokepoint
kind: pattern
title: A safety property enforced at N sites is not a chokepoint; apply single-writer to invariants too
date: 2026-08-05
---

Single-writer discipline is usually applied to data paths: one function owns the write, so the write cannot be inconsistent. The same reasoning applies to INVARIANTS, and it is easy to miss because an invariant does not look like a resource.

Observed on a component required to stay blind to a value it was being measured against. Blindness was preserved at four independent seams: a runtime flag controlling capability, the content of a rendered prompt, what got printed to an interactive session, and how references were validated. Three of the four were wrong, each discovered in a separate review round, because each seam was a separate opportunity to get it right and nothing forced them to agree. The fix was one function constructing the entire view the component was permitted to see, plus one test asserting that view carries no forbidden field. Three of the four seams then became ordinary code that structurally could not leak.

The same shape appeared in a two-phase write whose consistency was maintained by careful ordering plus rollback. Three rounds each moved a boundary and each left a different inconsistency reachable, because rollback cannot undo an append. Recovering forward from a single irreversible step, with everything after it recomputable, removed the class rather than guarding it.

How to apply:

1. When a property must hold, count the places that preserve it. More than one means more than one chance to be wrong, and review will find them one round at a time.
2. Build one constructor that establishes the property, and write ONE test asserting the property of its output. Prefer an allowlist over deleting known-bad fields: a field a future contributor adds is then excluded by default rather than leaking until someone remembers to exclude it.
3. Ask what the component may CITE or emit, not only what it may perceive. Both are the same invariant and both fail independently.
4. In a multi-step write, make exactly one step irreversible. Everything before it is validated and reversible; everything after it must be derivable from what is already durable, so a late failure is recovered by recomputation rather than by an impossible rollback.
5. A late-stage failure of a derived artifact must never escalate into refusing an operation that already succeeded. Report it, repair it inline if bounded, and let a separate verifier own the residual state.

The general contract: if you would apply single-writer to a data path, apply it to the invariant. A property maintained by N cooperating precautions is a property waiting for the round that finds the N+1th seam.
