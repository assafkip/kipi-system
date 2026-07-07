---
id: centralize-every-axis-of-a-validity-rule-and-enforce-it-at-t
kind: pattern
title: Centralize every axis of a validity rule, and enforce it at the write, not the read
date: 2026-07-06
---

When you factor "is this thing valid / show-worthy?" into a shared authority, notice that the decision usually has more than one axis. One common split: (a) is this VALUE a real instance of its type, and (b) is this TYPE allowed to exist as a first-class thing at all. Unifying one axis while leaving the other scattered as copy-pasted inline conditions is a half-fix that will recur on the axis you skipped. Before you call the rule centralized, enumerate its independent questions and give each its own single home.

Enforce the rule at the point of CREATION, not only at the points of display. A validity condition duplicated across N read paths still leaves every write/creation path free to mint the very thing the read paths filter out. Once minted, that data accumulates edges and relationships that no reader ever surfaces, so the corruption is invisible until something reads it a new way. A filter that lives only on the read side is a suggestion; the write side is where it becomes a guarantee. If a single check appears inline in several readers and in zero writers, treat that asymmetry itself as the bug.

Treat low-confidence, provisional records differently from confirmed ones. When a value is extracted from loose, ambiguous input as a candidate that a later pass is supposed to confirm-or-drop, do not let it enter shared, high-trust structures with the same standing as a verified value. Reusing an extractor built for high-signal input against low-signal input inherits its permissiveness; keep provisional items quarantined until the promotion step runs, and make "unpromoted" a state the durable store can represent and gate on, not a convention held only in prose.

Checklist: list every independent question your validity rule answers and confirm each has exactly one authority; confirm the authority is consulted on the write path, not just the read paths; audit for a check that exists inline in readers but nowhere in writers; and keep provisional/candidate data out of trusted shared structures until an explicit promotion step confirms it.
