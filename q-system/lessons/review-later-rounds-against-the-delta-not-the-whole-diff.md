---
id: review-later-rounds-against-the-delta-not-the-whole-diff
kind: methodology
title: Review Later Rounds Against the Delta, Not the Whole Diff
date: 2026-11-07
---

When a change stays open across several review rounds, read the whole change once, then read only what changed since the last reviewed commit.

How to apply it:

1. Round one reads the full change, line by line. It sets the baseline that later rounds build on.
2. Every later round reads only the commits added since the previous round: the diff from the last reviewed commit to the new head. Record the last reviewed commit with the verdict, so the next round has an exact starting point.
3. Every doubtful case falls back to a full read, never to a smaller one. That covers a rewritten history (rebase or force-push), a last reviewed commit that is no longer an ancestor of the head, a change to a shared interface or data shape, and a fix inside the risky areas round one named.
4. An empty delta is not a review. If nothing changed since the last reviewed commit, the earlier verdict stands and no new round runs.
5. A merge of the base branch into the change inflates the delta with code the change did not write. Read the change's own diff in that round instead.

Why it pays off: full re-reads of an unchanged diff cost reviewer time each round and find almost nothing new. Reading the delta puts the effort where the information is new.

Pitfall: delta-only rounds can miss a problem that only shows up when separately approved commits interact. Before the final approval of a long-lived change, skim the complete diff for coherence. CI still runs the full suite on every push, so the delta rule narrows what the reviewer reads, not what the tests check.
