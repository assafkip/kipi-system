---
id: compute-the-number-from-data-you-already-hold-before-inferri
kind: pattern
title: Compute the number from data you already hold before inferring it
date: 2026-10-05
---

When a report shows two figures that disagree, the gap is a question the data in hand can usually answer. Do not close it with a plausible explanation.

The failure: a data pull returned records that each carried a nested child collection. The parser read only the top-level rows and dropped the nested field. The report then saw a mismatch between a summary counter (7) and the top-level count (3), and explained it with 'almost certainly nested replies'. It also stated a derived status ('question still unanswered') that the dropped data would have contradicted. A human who had direct knowledge of the source caught the error.

The cause was an analysis defect, not an environment fault. Nothing failed to load. The answer sat in a field the parse skipped.

The pattern:
- Before you write a hedge word (almost certainly, probably, likely) next to a number, check whether the payload already contains what would settle it.
- Inspect the full shape of one raw record, including nested arrays and optional fields, before choosing what to parse.
- Reconcile every summary counter against a count you compute yourself from the rows. If the two disagree, treat the gap as an open defect, not a footnote.
- Flatten nested structures into the total you report, or state explicitly that you counted top level only.
- Never report a derived state (open, answered, unread, failed) from a partial slice of the records that determine it. Compute it over the whole set, or label the claim as unverified.
- Add a deterministic check: a script that asserts reported counts equal computed counts and fails loudly on mismatch. A reminder in a prompt will not hold this line.

Test for the habit: if your explanation of a discrepancy could be confirmed or refuted by reading data you already fetched, you skipped a step.
