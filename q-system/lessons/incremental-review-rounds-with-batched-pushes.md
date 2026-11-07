---
id: incremental-review-rounds-with-batched-pushes
kind: methodology
title: Incremental Review Rounds with Batched Pushes
date: 2026-11-07
---

When a change set stays open across many review rounds, scope each round to the delta rather than the whole diff, and batch the response to each round into a single push.

How to apply it:

1. Do one full, line-by-line review in the first round, and reserve that depth for code where a defect is costly (security boundaries, data migrations, concurrency, money or permission logic). This first pass establishes the baseline the later rounds build on.
2. For every round after the first, review only the commits added since the previous round. Use the tooling's commit-range or "changes since last review" view so the previously approved content is not re-read. If the tool lacks this, record the last-reviewed commit identifier in a review comment so the next round has an unambiguous starting point.
3. Author side: collect all fixes for a round and push them once. Avoid pushing each fix separately, since each push can trigger a new notification, a new check run, and an implicit new round of reading.
4. Classify low-risk edits out of the review path entirely. Formatting, comment wording, documentation text, generated artifacts, and file-mode changes can be covered by automated checks alone, with no human round. Make this explicit in the project's review guidance so skipping is a stated policy rather than an individual judgment call.
5. Re-expand the scope when the delta invalidates the baseline: a force-push or rebase that rewrites history, a change to a shared interface or data shape, or a fix that touches the risky areas identified in step 1. In those cases redo a full pass on the affected surface.

Why it pays off: repeat full reviews of an unchanged diff cost real reviewer time per round and produce almost no new findings, while adding latency that keeps the change open longer and invites more drift. Restricting attention to the delta concentrates reviewer effort where information is actually new.

Pitfalls to watch: delta-only review can miss emergent problems from the interaction of separately approved commits, so before approving a long-lived change, do a final skim of the complete diff focused on coherence rather than line correctness. Also ensure automated checks genuinely cover the categories you are waving through; skipping review on trivial edits is only safe if something else is enforcing style, build, and test correctness.
