---
id: derive-user-facing-state-from-the-evidence-not-a-proxy-field
kind: pattern
title: Derive user-facing state from the evidence, not a proxy field
date: 2026-08-24
---

A displayed status is a claim. When that claim is computed from one convenient stand-in (a hand-set enum, a single boolean, the last row's direction), it drifts from reality the moment any other store changes without touching the stand-in.

HOW:

1. For each user-facing state, write down the question it answers in plain words, then list every store that holds evidence for that question. If the list has more than one entry and the state reads from one of them, you have a proxy, not an answer.

2. Read the evidence to the end before deciding. A record's first field often disagrees with its last: direction is not intent, presence is not activity, an acknowledgment is not a request. Determinism about a low-level attribute does not license a high-level conclusion built on it.

3. Make the derivation a single function with every evidence source as an input, and let the stored field be its cached output rather than its source. Never let the display path and the derivation path read different things.

4. Enumerate the sources in code, not in the reader's head. Keep the evidence sources in one list that the derivation iterates, so adding a source without wiring it in is a build or test failure. A cross-cutting rule implemented for exactly one input path, and assumed to generalize, is the usual failure.

5. Reconcile on a schedule and log disagreements. Any record where the stored field and the freshly derived value differ is a defect report about the derivation, not a row to quietly overwrite.

6. Test with the cases the proxy gets wrong: evidence present in a source the derivation forgot, evidence that reverses meaning when read fully, evidence that is not the kind of thing the state is about at all. A test suite that only exercises the proxy's happy path proves nothing.

When a prior fix made some lower-level attribute reliable, treat that as one input to the next layer, not as the next layer's answer. Stacking a claim directly on a newly trustworthy primitive is how the same defect recurs one level up.
