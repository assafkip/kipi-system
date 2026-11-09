---
id: stop-designing-inside-the-review-loop
kind: methodology
title: Stop Designing Inside the Review Loop
date: 2026-11-09
---

When a pull request keeps returning with requested changes across multiple review rounds, check for three compounding causes and correct them deliberately.

1. Detect design happening inside review. If new requirements or stakeholder rulings arrive mid-review and each round adds new mechanisms (new states, new ordering rules, new communication channels), the PR has become the design venue. Components with no prior design and no existing consumer get shaped one review comment at a time, which guarantees more findings. When this happens, pause the PR. Write a short design note covering states, transitions, invariants and consumers for the new subsystem, get it agreed, then resume implementation against it.

2. Test properties and lifecycles, not individual findings. Adding a regression test that pins only the exact scenario a reviewer named leaves neighboring edges uncovered, so the next round finds the adjacent bug. For any stateful entity, enumerate its full lifecycle (for example: create, deduplicate, hold, resolve, release, recur) and write tests that walk the whole cycle, including the repeat and re-entry paths. Prefer invariant or property-style tests that assert what must always hold, not what happened in one case. When fixing a review finding, ask which lifecycle stage it belongs to and cover the whole stage.

3. Bound PR width to what can converge. A PR that bundles several independent concerns (core logic changes, validation, re-entry handling, scheduling or ordering, new notification channels, reporting output) multiplies the review surface and the interactions between findings. As a rule of thumb, if a PR has not converged after two rounds and it spans more than one subsystem, split it. Land the foundational mechanism first, then layer the dependent features in follow-up PRs, each with its own focused review.

Quick checklist before the next review round: Is every new component backed by an agreed design? Does every stateful entity have an end-to-end lifecycle test, including repetition? Can this PR be described as one coherent change? If any answer is no, fix that before pushing more patches.
