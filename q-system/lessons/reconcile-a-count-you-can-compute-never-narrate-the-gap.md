---
id: reconcile-a-count-you-can-compute-never-narrate-the-gap
kind: pattern
title: Reconcile a count you can compute; never narrate the gap
date: 2026-09-07
---

A report claimed something was missing. The data proving otherwise was already sitting in the payload the job had fetched, one level down, unread.

The shape: an API returned a tree (top-level items, each carrying a child array). The parse walked the outer list only. The summary counter said 7, the parsed rows numbered 3, and the report closed that gap with the phrase "almost certainly nested replies" instead of opening the array it already had in memory. Then it made a negative claim ("this one is unanswered") that a full read would have contradicted.

Two separable defects, and they need separate fixes.

**1. Flattening a nested structure and reporting the top level as the whole set.** The parse was not wrong about what it read. It was wrong about what it claimed. A tree read as a list is a silent truncation: no error, no empty result, just a smaller number that looks like an answer.

**2. Filling a known discrepancy with a plausible sentence.** Any time a provider hands you both a summary counter and the underlying items, those two numbers are a free consistency check. When they disagree, that is a resolvable fact, not a thing to explain.

## The rules that generalize

- **Reconcile before reporting.** If the payload carries a count and also carries the items, compare them. Equal, report. Unequal, resolve it or say the reconciliation failed and by how much. Never report the smaller number as the total.
- **Hedge words are a stop signal, not prose.** "Almost certainly", "presumably", "the rest are probably" inside a report about data you already hold means you did not open the field. Treat them as a lint target: an inference about your own payload is a defect, because the ground truth is local and free.
- **Negative claims carry the highest cost.** "Nothing there", "none found", "unanswered", "no response" send a human to redo work they already did, or to act on an absence that does not exist. An absence claim needs a completeness proof: every container walked to its leaves, or the claim is downgraded to "not found in the top level I read".
- **Re-read before you re-fetch.** The instinct when a result looks thin is to run the extraction again with different parameters. Cheaper and more often correct: dump the raw response you already paid for and check whether the missing thing is in it. Most "the source did not give us X" turns out to be "our parse dropped X".
- **Fixtures must contain the nesting.** A flat fixture cannot catch a flattening parse. Every recursive or tree-shaped source needs at least one test case with populated children, and an assertion on the leaf count, not just the root count.
- **Classify it correctly or you will fix the wrong layer.** This is an analysis defect, not a source or environment defect. The upstream behaved. Blaming the provider here would have produced a retry, a different tool, or a bigger budget, and none of them would have touched the parse.

## The one-line check

Before any claim about how many, or about something being absent: name the field in the response you read to decide it. If the answer is an inference rather than a field, open the field.
