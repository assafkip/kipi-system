---
id: compute-counts-from-data-you-already-hold-before-inferring-t
kind: methodology
title: Compute counts from data you already hold before inferring them
date: 2026-10-19
---

When a data pull reports a total that doesn't match the sum of the parts you parsed, treat the gap as a defect in your own parsing until proven otherwise. Do not close it with a plausible explanation such as 'the difference is probably nested items.'

The failure pattern: a collection fetched from a source often contains nested child collections (replies, sub-items, child records). A parser that reads only the top-level rows silently drops them, and the report then presents a partial view as the complete set. Downstream claims built on it (for example, 'this item is still unanswered' or 'nobody followed up') can be false.

How to apply:
1. Before parsing, inspect the raw response shape. List every field that holds a nested array or object, and decide explicitly whether each is in or out of scope.
2. Flatten or recurse through nested children so the parsed set covers everything the source returned.
3. Reconcile: compare your computed total against any total the source reports. If they differ, open the data and find the cause. Do not guess.
4. Ban hedged inference words ('almost certainly', 'probably', 'likely') in a report where the answer can be computed from data already in hand. Either compute it, or label the figure as unverified and state exactly what was not examined.
5. Before asserting a negative state ('unanswered', 'missing', 'no response'), check the full set including nested children and any activity by the user or owner. A negative claim needs stronger evidence than a positive one, because it can send someone to redo work already done.
6. Add a regression check: an assertion that parsed count equals source-reported count, failing loudly on mismatch.

The root cause is an analysis defect that was always latent, not an environmental failure. The fix is in how output is parsed and how claims are worded, not in retrying the fetch.
