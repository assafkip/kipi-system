---
id: separate-a-wrong-value-from-a-hidden-one
kind: methodology
title: Separate a wrong value from a hidden one
date: 2026-08-17
---

A report that something "looks wrong" or "isn't there" collapses two different failures into one sentence. Either the stored value is incorrect, or the value is correct and something between the store and the viewer is withholding it. Correcting data and delivering data are separate systems, and success in the first says nothing about the second.

Routing logic is usually the hidden half. Confidence thresholds, validation flags, review queues, staging and publication states, permission scopes, freshness windows, and dedup filters all decide which surface a record reaches. They read fields that have no relationship to the one under suspicion, so a field can be repaired to perfection while the record stays parked in a queue nobody looks at.

How to work it:

1. Before touching anything, read the record at the source of truth. If the value there is already correct, the problem is delivery, and any edit to the value is wasted motion.
2. If the source value is correct, walk forward one hop at a time toward the surface the person was looking at. At each hop ask what that layer decided about this record and on which field. Stop at the first hop where the record is absent or transformed; that is the actual defect site.
3. If the source value is wrong, fix it, then still walk the same path forward. A newly written record is subject to the same routing rules, and a fix that never surfaces reads to the reporter as no fix at all.
4. Confirm the fix from the place the person actually looks, not from the store you edited. Same view, same filters, same account.

Ask the reporter where they were looking when they saw the problem. The surface they name tells you which routing path to walk. Answering "the value is now correct" while the record remains invisible closes a ticket without changing anything anyone can see, and the same report comes back.
