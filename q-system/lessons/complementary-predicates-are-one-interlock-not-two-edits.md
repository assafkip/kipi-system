---
id: complementary-predicates-are-one-interlock-not-two-edits
kind: pattern
title: Complementary predicates are one interlock, not two edits
date: 2026-08-17
---

When two consumers only stay out of each other's way because their selection rules are exact complements of a single condition, that condition is not a filter detail. It is the whole safety property, and it lives in two places at once.

Remove it from one side while the other side is still running and both consumers now claim the same items. Whichever gets there first marks them handled, so an item lands in one destination, in both, or in neither, purely by timing. Nothing errors. The damage looks like a data-quality problem weeks later, not like a change that broke.

## How to handle it

1. Before widening or dropping any selector, ask what stops the other consumers from picking up the same rows. If the answer is "they filter on the negation of this," you are holding one interlock, not one condition.
2. Change both sides in a single atomic write: one commit, one deploy, one migration, one config push. Not two ordered steps, however short the window looks.
3. If the deployment mechanism cannot land both sides together, invert the order: stop the other consumer first, take the resulting coverage gap, then widen. A gap is recoverable by replay. An overlap corrupts the record of what was already handled, and you often cannot tell after the fact which consumer got which item.
4. Never widen first and shut down second. That ordering is a race with a data-loss outcome, and the interval it is open for is not the interval you planned.

## Test for it

Write the case where both selectors run against the same input at the same time and assert exactly-one-destination. If your test harness can only run the consumers sequentially, it cannot see this class of defect, so at minimum assert that the two selectors are provably disjoint over the same input set, and make that assertion fail when the predicate is edited on one side only.

## Design note

Disjointness enforced by two independently editable predicates is fragile by construction. Where you can, derive both from one shared definition, or route through a single dispatcher that assigns each item to exactly one consumer. Then the property is structural instead of a convention two files agree to keep.
