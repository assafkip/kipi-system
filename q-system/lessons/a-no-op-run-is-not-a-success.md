---
id: a-no-op-run-is-not-a-success
kind: pattern
title: A no-op run is not a success
date: 2026-07-06
---

A job's terminal status must be derived from the work it actually produced, not from the fact that it reached the end without throwing. "No error occurred" and "real work was done" are two different facts, and a run that completes cleanly while producing nothing collapses them into a single misleading green light. The person reading the status sees "done" and infers "the work happened"; the two can diverge silently.

Define, for each kind of job, the artifact that constitutes real output: rows written, items collected, actions taken, cost incurred, steps executed. Before stamping success, check that at least the minimum expected quantum of that artifact exists. If the run finished with zero of everything it was supposed to produce, that is a distinct outcome, not success. Surface it under its own status (empty, no-op, starved) so it is visibly different from both a real success and a hard failure.

Watch for the specific trap where an internal sub-step returns partial or placeholder state that looks structurally valid but represents no work: a stub summary instead of executed actions, a default object instead of gathered results, a completed wrapper around a body that never ran. Structural validity of the payload is not evidence that work occurred. Assert on the substance (count, magnitude, effect), not on the shape.

Make the check a gate at the point where the status is assigned, so it cannot be bypassed by a caller that only inspects the top-level status flag. A downstream consumer should be able to trust that success means output exists, without re-deriving that fact from the raw artifacts itself.
