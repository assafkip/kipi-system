---
id: an-item-count-proves-a-step-was-reached-not-that-it-ran
kind: pattern
title: An item count proves a step was reached, not that it ran
date: 2026-08-11
---

Execution logs report per-step item counts, and the number is read as evidence the step did its work. It is not. In several orchestration runtimes a disabled or skipped step still appears in the run record, carrying its input count, because it passes its input straight through to the next step. The log shows a busy step doing nothing. The count is about the data that ARRIVED, not the effect that occurred.

Observed 2026-08-11 while re-enabling a suppressed pipeline branch. Reading the execution history back, the append step showed 24 items on the three runs BEFORE the change, which reads as the same 24 rows written to a client's spreadsheet four times over. Duplicate rows on a client sheet were the exact failure the engagement existed to prevent, so this looked like a serious self-inflicted incident. It had not happened. The disabled node was a pass-through and the count was its upstream input. The number that actually separated a write from a pass-through was the database step's `RETURNING id`, which gave 1 (the collapsed pass-through item) on every pre-change run and 24 on the real one. The independent confirmation was the backlog going 33 to 0 exactly once.

How to apply:

1. Verify an effect by its EFFECT, never by the count on the step that was supposed to produce it. A write is proven by reading the destination or by the row count the write itself returned.
2. Prefer a step that cannot be a pass-through as your witness: a database statement with `RETURNING`, a re-read of the target, a state counter that had to change. A pass-through cannot fake those.
3. Before concluding an incident from a log, ask what the log would look like if nothing had happened. If the answer is "the same", you have not measured anything yet.
4. The corollary for a scheduled job: a successful run is not a completed unit of work. A branch with nothing to do succeeds identically to one that did everything, so success is the wrong signal for any conditional writer.
5. This is cheap to check and expensive to skip. One query against the destination refuted a four-times-duplicated-client-data conclusion in under a minute.
