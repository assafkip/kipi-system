---
id: enforce-invariants-at-the-true-edge-on-every-path
kind: pattern
title: Enforce invariants at the true edge, on every path
date: 2026-07-20
---

A property you enforce once, at a convenient midpoint, is not enforced. Four recurring failure shapes share one cause: the guarantee lives before the last thing that can violate it, or on only one of the paths that reach the same resource.

How to apply:

1. Redaction/sanitization belongs at the egress edge, not mid-pipeline. If you scrub data at a serializer and then any augmentation, enrichment, or alternate (durable/replay) path runs afterward, it re-introduces what you removed. Either move the scrub to the single point where data actually leaves, or make every post-scrub mutation idempotently re-scrub. A cleanse that has code running after it is a leak waiting on the next added step.

2. Hiding something in the UI is not an access-control block. Removing an item from a list does nothing to the expensive or sensitive endpoint behind it. Enforce a state ('archived', 'retired', 'disabled') at the ACTION handler, and confirm every reachable caller honors it: direct API call, scripted client, replay, and any second entry point. If it can be reached without the view, the view's guard is decorative.

3. An append-only store ships its bound in the same change that creates it, not later. An in-memory cap on recent items is a false sense of bound: nothing limits the file, so a full-file parse per read and repeated appends turn 'persisted' into 'unbounded and O(size) per request'. Add compaction/rotation plus a bounded read up front.

4. A new flag or state is half-wired until it reaches every surface that observes it. Adding a mode to one path leaves the other paths acting as if it does not exist. Enumerate every surface that must respect the flag (each endpoint, each background/replay path, each reader) and prove each one checks it before calling the change done.

The unifying test: name the LAST place a value can leave, be acted on, grow, or be read, then put the enforcement there and on every path that reaches it. An invariant asserted anywhere earlier holds only until the next code path is added after it.
