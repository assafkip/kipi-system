---
id: when-a-fan-out-push-fails-at-exactly-one-target
kind: pattern
title: When a fan-out push fails at exactly one target
date: 2026-10-12
---

A change that propagates from one source to many consumers will fail first, and sometimes only, at the consumer with the most local validation. That asymmetry is information about the target, not evidence that the payload is wrong. Diagnose the target before touching the change.

Three mechanisms produce the single-site failure, and each has its own fix:

1. Asymmetric local gates. Count how many consumers run any check at commit time. If one runs tests and the rest run none, the rest are silent by absence, not by health. Where a consumer's tests exercise ITS OWN code against the incoming shared files, a shared change those tests depend on needs a matching local change in the same commit, and a push that carries shared files only can never produce one. That coupling is an implicit contract: it exists in the consumer's test suite and is written nowhere the propagator can read. Make it explicit, either by declaring that consumer's dependency so the push can carry both halves, or by removing the cross-boundary assertion from the commit gate and running it after the sync instead.

2. The push lands in a live working copy, not in a known state. A sync that writes into an existing checkout inherits whatever branch and drift that checkout was left on. The gates then execute the checkout's copies of the test and build code, so a fix already merged upstream is not present and the failure reproduces forever. Measure the drift as a precondition: commits behind the integration branch, and the count of differing files. Either bring the target to a known state first or refuse to sync a target past a drift threshold. A detector that reports drift but never blocks a sync does not change the outcome.

3. Reverse-direction edits. When a consumer edits a file the shared source owns, the next push correctly refuses it as locally ahead. The sync is doing its job; the edit was in the wrong place. Enforce ownership where the edit happens rather than where the sync lands, so an in-place edit to a managed file is rejected at write time with a pointer to the upstream path.

The general rule: a fan-out mechanism carries a payload and assumes a precondition at every target. Preconditions diverge, payloads do not. When one target fails repeatedly and the others pass, enumerate what that target does differently before re-reading the payload.
