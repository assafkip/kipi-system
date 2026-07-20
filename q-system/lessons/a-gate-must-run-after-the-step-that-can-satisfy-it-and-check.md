---
id: a-gate-must-run-after-the-step-that-can-satisfy-it-and-check
kind: pattern
title: A gate must run after the step that can satisfy it, and check only what the pipeline neutralizes
date: 2026-07-20
---

When a multi-stage pipeline builds an output by transforming a shared base through ordered stages, three failure modes turn a correctly-firing gate into a permanent, silent hold. Order the gate and reconcile its contract to avoid them.

1. Gate ordering must match the pipeline's own repair order. If a validation gate checks for a defect that a LATER stage is responsible for fixing, any input carrying that defect is unsatisfiable at the gate: the stage that would clear it never gets to run. Place a gate AFTER the stage that repairs what it checks, or move the repair earlier. A gate whose passing condition is only produced downstream of itself will hold forever.

2. The neutralization step and the gate must share one reconciled contract. When a deterministic pre-step strips or parks the surfaces a gate rejects, enumerate both sets and prove they match. If the gate rejects surfaces A, B, C, D but the pre-step only neutralizes A, B, C, the pre-step is structurally short of the gate and every input hits the hold. Treat 'what counts as a violation' and 'what gets neutralized' as one list with a test that they are equal, not two lists maintained independently.

3. The shared base is a hidden dependency; test a real build through the gate. Both the neutralization step and the gate depend on the exact contents of the base being transformed. A base that is relocated, updated, or swapped can start carrying un-neutralized content that trips the gate — with nothing catching it until the pipeline runs for real. Add a test that builds an output from the CURRENT base and drives it through the gate stage. That test is what converts a base change from a silent time-bomb into a caught regression.

The unifying rule: a gate is only healthy if (a) something downstream of nothing-yet-run can satisfy it, (b) it checks exactly the set your own repair covers, and (c) a test exercises the real inputs it guards. Miss any one and a correct gate becomes an unreachable wall.
