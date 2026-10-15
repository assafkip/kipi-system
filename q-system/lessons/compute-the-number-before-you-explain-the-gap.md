---
id: compute-the-number-before-you-explain-the-gap
kind: pattern
title: Compute the number before you explain the gap
date: 2026-10-04
---

When a report shows two figures that disagree, such as a total of 7 against 3 listed items, the reconciliation is a computation, not a guess. Open the data you already hold and count. Do not write 'almost certainly X' to close the gap.

The failure pattern: a parser reads only the top level of a nested structure, discards the child collections, then explains the resulting mismatch with a plausible story. The story was a hypothesis. The evidence to confirm or refute it sat in the discarded field.

Two separate defects hide here:

1. Partial parse reported as complete. The code read one layer of a tree and presented that layer as the whole set. Any conclusion built on it ('nothing is waiting', 'no one replied') inherits the hole.
2. Inference standing in for a lookup. The report noticed the discrepancy, which was the right instinct, then resolved it with language instead of data. Hedge words like 'almost certainly', 'probably' and 'likely' next to a number are a signal that a check was available and skipped.

How to apply it:

- When two counts disagree, treat the gap as a task: find the field that accounts for it and sum it. Report the sum, or report that the field was absent.
- Before saying a response is complete, list the fields the source returned and confirm each was either used or deliberately dropped. A dropped nested collection needs a stated reason.
- Any absence claim ('no reply', 'unanswered', 'none found') must be checked against every level of the structure, not just the first.
- Reserve inference for facts the data cannot provide. Label it as inference, and name the lookup that would replace it.
- Add a reconciliation assertion to the pipeline: the reported total must equal the sum of the parts you parsed. A mismatch fails the run rather than getting narrated.

A reader who owns the underlying facts will catch a wrong claim immediately, and the cost lands on their time. The cheaper check is the one you run before you report.
