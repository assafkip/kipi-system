---
id: terminate-on-a-drained-work-queue-not-a-self-scored-plateau
kind: pattern
title: Terminate on a drained work-queue, not a self-scored plateau
date: 2026-07-06
---

An iterative discovery agent (crawl, investigate-until-done, frontier expansion) that decides it is "finished" from its own sense of progress will quit early the moment its tools degrade. It reads "I'm not surfacing anything new" as "the space is exhausted," when the real cause was a missing capability or an unavailable input. The fix is to make termination a function of a concrete work-inventory, and to reconcile what the agent claims against what it actually produced.

Five moves:

1. Maintain an explicit queue of discovered-but-unprocessed items. Every pass appends what it surfaces (leads, entities, pivots) to that queue as first-class records, and marks an item processed only after it has actually been pulled and resolved. Between passes, re-read the queue and feed the unprocessed items back in. Do not rely on the model to remember what it has not yet chased.

2. Make the stop condition a drained queue, not a plateau. The loop continues while unprocessed items remain and a resource budget is left. "I am not finding anything new" is not a terminal state while named-but-unpulled items still sit in the queue.

3. Separate "no work left" from "cannot do the work." When a step cannot run because a capability is missing or an input is unavailable, tag that item as blocked-on-tool, not as done. A blocked queue is a surfaced diagnosis (what is missing, why), never a silent completion. Degraded tools escalate; they do not lower the finish line.

4. Reconcile the narrative against the structured artifact before declaring success. Any claim the agent states in prose must be traceable to a record in the structured output; anything named in the summary but absent from the durable artifact is either promoted or re-queued. A rich prose summary must never stand in for a thin artifact — the artifact is the deliverable.

5. Assert the gap mechanically at closeout: count the entities named in the summary versus those present in the structured output and promoted downstream. A nonzero difference fails the run. This catches the "brag-list of leads that were never pulled" failure without a human re-read.

The tell: a run that "finished" is only proven finished if its work-queue is empty or every remaining item is tagged blocked-with-reason, and every claim in its summary maps to a promoted record.
