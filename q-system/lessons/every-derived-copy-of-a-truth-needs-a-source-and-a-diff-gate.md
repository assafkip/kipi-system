---
id: every-derived-copy-of-a-truth-needs-a-source-and-a-diff-gate
kind: pattern
title: Every derived copy of a truth needs a source and a diff-gate
date: 2026-07-20
---

When one fact lives in a canonical place AND in copies generated, cached, cloned, or merely claimed from it, those stores drift by default and the copy that actually runs is silently not the one you edited. Treat this as a class, not a one-off.

HOW:

1. Name the source. For any fact that exists in more than one place, designate exactly one canonical store. Every other representation is derived and must be regenerable from it.

2. Change the source, never the copy. Edit at the canonical store and re-run the generating flow. Hand-editing a cache, clone, or vendored duplicate leaves the source and copy divergent by construction; the next regeneration silently reverts your edit or, worse, never notices.

3. Bump a version key on every regeneration. A cache that can't tell its copy is stale will serve the old one forever. If the copy carries no version/hash tied to the source, it cannot self-invalidate.

4. Add a diff-gate per pair. For each source-and-copy pair, ship a deterministic check that fails when they disagree (compare content, or compare a hash of the source against a recorded hash in the copy). A rule that merely *claims* the copy is kept in sync is prose; the gate is the enforcement. One gate per pair is not enough for the class: enumerate the pairs and gate each.

5. Prove the running system loads the copy you changed. Grepping that the new text exists in a repo file proves nothing when the runtime loads a different clone. Verify by observing the live behavior, or by grepping the actually-loaded copy.

6. When you find one drifted pair, look for siblings. Duplication of one fact is rarely unique; the same shape usually recurs across settings vs template, cache vs live contract, and doc-claim vs wiring. Capture each as its own gated item so none is silently dropped.
