---
id: check-liveness-at-the-source-of-truth-not-at-each-exit-path
kind: pattern
title: Check Liveness at the Source of Truth, Not at Each Exit Path
date: 2026-11-09
---

Problem shape: a piece of state stored in one place (for example, a pending request, flag, or reminder) is only valid while some other record elsewhere is still live. The relationship between the two is an implicit contract: nothing in the code enforces it, and validity is computed indirectly from the second store.

Failure mode: every code path that removes, releases, replaces, or otherwise ends the second record becomes a 'door' through which the first piece of state can silently become stale. Fixes made one at a time ask 'where does this record go away?' and patch that specific path. Each review round then finds another door, and any path added later reopens the bug. This is the signature of fixing scenarios instead of fixing the invariant: each round pins only the case someone happened to name.

How to recognize it:
- A second or third fix for 'stale X' touches a different removal or replace path than the last one.
- Validity of state A is derived by tracking mutations to state B rather than by querying B directly.
- Reviewers keep describing new sequences of events rather than a new kind of bug.

How to fix it:
1. State the invariant in one sentence, phrased about the source of truth (for example, 'the request is live if and only if its owning item is still open').
2. Move the check to the point of use, or to one reconciliation step, that asks the source of truth directly. Do not mirror the answer through every mutation path.
3. If you must cache, make the cache derivable and re-validate it against the source on read, or reconcile it in a single place that runs after any mutation.
4. Write one lifecycle or property-style test that asserts the invariant across all transitions, including ones that do not exist yet: generate or enumerate sequences of create, update, replace, release, and delete, then assert the derived state agrees with the source after each step. Avoid one test per reported scenario.
5. When reviewing a fix for stale derived state, ask 'is the underlying thing still open?' instead of 'which path removed it?'. If the answer requires listing paths, the design is still path-dependent.

Heuristic: if the number of places that must remember to update A grows with the number of ways B can change, the contract is in the wrong place. Collapse it to a single query against B.
