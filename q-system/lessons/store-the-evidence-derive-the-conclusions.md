---
id: store-the-evidence-derive-the-conclusions
kind: pattern
title: Store the evidence, derive the conclusions
date: 2026-07-20
---

When a system builds up state by observing a stream of inputs, decide up front which representation is the source of truth, and make it the durable one. The failure mode: you persist the *conclusions* (the accumulated, judged, human-facing view) but discard the *evidence* they were derived from. On any reload, restart, or cold path, you can neither reconstruct the conclusions nor re-derive them, because the raw inputs are gone. The conclusions look authoritative but nothing can regenerate or audit them.

How to build it right:

1. Name the source of truth explicitly. Exactly one representation is primary and durable: the append-only log of raw observations/events. Everything a user or downstream step reads is a *derived view* computed from it. Write this down as a decision, not an accident of which code path ran first.

2. Persist evidence, not just verdicts. Store the inputs at the grain you'd need to re-derive every downstream conclusion. If a value was judged, inferred, or accumulated, keep what it was judged *from*. A stored conclusion with no retained evidence is a dead end.

3. Make derivation pure and repeatable. The live path and the cold-load/reconstruction path must run the *same* derivation over the same durable source, so a reload reproduces the exact view instead of a divergent or empty one. Two code paths that both write the 'current state' independently is the smell — collapse them to one deriving function over one source.

4. Never let a reload be a loss function. Test the cold path deliberately: kill the process, reload from the durable source alone, and assert the reconstructed view equals the live one. If it can't be reconstructed from what's on disk, the disk isn't holding the source of truth.

5. Count your representations. If the same state exists in several places (live accumulator, cached view, persisted snapshot, what a caller reads back), enumerate them and confirm each is either the single source or a pure derivation of it. Any representation that's independently authoritative is a future divergence.

The invariant: given only the durable store, you can regenerate every conclusion the system has ever shown. If you can't, you're persisting answers while destroying the only thing that could justify or rebuild them.
