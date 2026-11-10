---
id: guard-the-invariant-once-not-each-branch-that-a-review-names
kind: methodology
title: Guard the invariant once, not each branch that a review names
date: 2026-11-10
---

Symptom: a change needs several review rounds. Each round finds a defect in a different branch of the same feature, and each fix adds a condition only to the branch the finding pointed at. The fix moves the hole without closing it.

Root causes and how to avoid them:

1. Write the invariant down as one sentence before patching anything.
State the rule as a single read, for example: "an entity's derived state equals the set of its live related records, and every decision about the entity consults that set." Then list every code path that reads or changes that state: creation, recording, display or labeling, resume or retry, and routing or dispatch. Make all of them go through one function that computes or checks the invariant.
A guard placed inside one branch of a dispatcher cannot protect the other branches. When a review finding names one branch, ask whether the invariant also holds for every sibling branch. Check paths that never read the state at all, and paths that have no persisted state to check against.

2. Measure usage before building the riskiest option at full scope.
If one option in a set of decisions creates permanent objects through a non-atomic sequence of writes, it carries most of the risk and most of the review cost. Before shipping it at full scope, sample real decisions to see how often that option is actually chosen. If it is rare, ship a narrower version first, or defer it.
Treat measurement as reconnaissance: checking an existing signal before building can show that no new code is needed.

3. Test the state machine across time while the data changes between runs.
Tests that cover a single run, or two runs with nothing changed in between, miss most lifecycle defects. Add multi-run tests that mutate the parent and the related records between runs, for example:
- reopen
- cancel or delete
- move to a different scope or owner
- add or remove a child
Assert the invariant after every run.
If a reviewer finds a bug by writing such a sequence by hand, turn that sequence into a permanent test. Then generalize it across all branches.

Checklist for a multi-branch decision feature:
- one written invariant;
- one enforcement point that every branch calls;
- a usage measurement for the highest-risk branch;
- multi-run mutation tests for each branch.
