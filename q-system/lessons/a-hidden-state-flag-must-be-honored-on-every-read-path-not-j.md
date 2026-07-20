---
id: a-hidden-state-flag-must-be-honored-on-every-read-path-not-j
kind: pattern
title: A hidden-state flag must be honored on every read path, not just the primary one
date: 2026-07-20
---

When you add a state that means "exclude this record" — soft-delete, archive, suppression, tombstone, deactivation — the intent is one line but honoring it is not. The record is read by many consumers: the main list, secondary lists, rollups, aggregates, digests, exports, and derived metrics. Each of those is a separate code path. Filtering the flag in the primary list does not filter it anywhere else, so the same leak reappears consumer by consumer, round after round, looking like a new bug each time when it is one unmet invariant.

The deeper trap is that derived metrics leak even after their record list is filtered. A rollup can correctly hide the excluded rows in its listing while still counting them in its totals, averages, or override tallies, because the count is computed on a different pass than the display. Filtering what you see is not the same as filtering what you measure.

HOW to build against it:

1. Name the invariant once, in words: "an excluded record appears in NO downstream read — no list, no aggregate, no metric, no export." That sentence is the spec every consumer is tested against.

2. Enforce the exclusion at a single shared chokepoint, not per-view. Push the filter into the query[PATH] layer that every consumer already calls, so honoring the flag is the default and opting out is the explicit, rare case. Per-view filtering guarantees you will miss one.

3. Enumerate consumers before you call it done. Grep for every reader of the affected table/collection and list them. The count of consumers is the count of places that must honor the flag; an unlisted consumer is an unfixed leak.

4. Test each consumer against the invariant, and test displayed rows and computed metrics separately. Assert both that the excluded record is absent from the listing AND that it contributes zero to every derived number that consumer emits.

5. Treat a re-audit finding as evidence the invariant is not centralized yet, not as a fresh isolated fix. If the same class recurs after a targeted patch, the patch was per-consumer; move the enforcement to the shared layer instead of fixing the next view.
