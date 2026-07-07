---
id: wire-a-hard-constraint-into-the-done-gate-and-halt-when-a-pl
kind: methodology
title: Wire a hard constraint into the done-gate, and halt when a plan quietly relaxes it
date: 2026-07-06
---

A constraint stated as non-negotiable at the top of a spec, but never encoded in the criteria that decide "done," is not enforced — it is decoration. Two failure modes conspire, and both are structural, not attention lapses.

**1. A plan can silently demote a hard constraint to a defaultable assumption.** When the person who owns a constraint hands off work, a planning step often narrows or defers it — "we'll do the full version later; for now these parts render an empty placeholder," "scope this phase to the visible layer, backfill depth next." That is the forbidden thing recast as a default the owner must now notice and veto inside a long document. The burden of catching the contradiction gets inverted onto the human. The correct move is the opposite: when a plan step contradicts a stated hard constraint, HALT and force explicit reconciliation — surface the exact conflict ("this deferral relaxes the 'no X' constraint you marked non-negotiable; confirm or restate") before any work proceeds. Silence plus subsequent activity is not approval; a hard constraint stays hard until its owner explicitly relaxes it in response to the named conflict.

**2. Acceptance criteria drift to proxies the hollow version also passes.** Under time pressure, "done" collapses to whatever is cheap to check — it builds, the tests are green, a screenshot looks right, the surface renders without erroring. Every one of those is satisfied by an implementation that is faithful in appearance and absent in substance. The constraint lived in prose; the gate measured proxies; the two were never connected, so the gate measured the wrong thing. The fix is to translate the constraint itself into an executable acceptance check. If the requirement is completeness ("every original element has a real equivalent, nothing is a placeholder"), the gate enumerates the elements and asserts each has a non-stub implementation — not that the whole thing renders. If the requirement is behavioral depth, the gate exercises the behavior, not the paint.

**How to apply.**
- For each constraint marked non-negotiable, write down the acceptance check that would fail if it were violated. If you cannot state that check, the constraint is unenforced — treat that as a blocker, not a detail.
- Never let a check that a placeholder passes stand in for a check of the thing itself. "Renders," "builds," "tests pass," "looks identical" are proxies; enumerate-and-assert-real is the constraint.
- When any plan step would narrow, defer, or phase-out a hard constraint, stop and name the contradiction to its owner. Do not encode the relaxation as a default and rely on them to catch it.
- Connect the prose to the gate explicitly: the sentence stating the constraint and the criterion enforcing it should reference each other, so a later reader cannot satisfy one while ignoring the other.
