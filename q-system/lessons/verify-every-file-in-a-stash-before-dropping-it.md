---
id: verify-every-file-in-a-stash-before-dropping-it
kind: methodology
title: Verify Every File in a Stash Before Dropping It
date: 2026-10-31
---

A stash created to unblock a merge is not a neutral parking spot. Once the conflicting paths are stashed, the merge resolves them toward the incoming or current branch tip, which is correct merge behaviour but wrong for the parked content: the newer version of those files now exists only inside the stash entry. Dropping the entry at that point silently reverts work.

The common failure is a sampling check. Engineers confirm that some later commit or an automated hook touched one of the stashed paths and conclude the stash is redundant. That check answers a different question — whether the file changed at all — not whether the merge preserved the specific content that was stashed. It also leaves the remaining files in the entry completely unexamined, and those are usually where the loss is: appended data rows, status notes, or handoff text that no other commit would ever reproduce.

HOW:

1. Before dropping any stash that was taken to unblock a merge, enumerate every file in the entry, not just the one that caused the conflict.
2. For each file, diff the stashed version against the post-merge tip. Treat "the file was modified by something else" as irrelevant; only a diff against the current tip tells you what is missing.
3. Classify each hunk as newer content (must be restored) or stale pre-merge state that the merge legitimately superseded (must be discarded). When in doubt about structured data, compare at row or record granularity rather than at file granularity.
4. Restore the newer hunks and commit them with the per-file verification recorded in the message: counts added, counts removed, counts differing, and which specific lines are superseded by the merge and intentionally dropped. This makes the judgement auditable later, when nobody remembers the merge.
5. Only then drop the entry.

The single exception: if every file in the entry is byte-identical to the post-merge tip, the entry carries no information and can be dropped without further diffing. That is the only safe shortcut.

Generalization: any mechanism that temporarily removes changes from the working tree so another operation can complete — stashes, backup copies, reverted commits, disabled migrations, commented-out blocks — creates a reconciliation debt. The operation that unblocked you is allowed to make decisions about the parked paths, and it will make them without knowledge of what you parked. Close the loop by diffing the parked state against the final state file by file, and record the comparison rather than trusting memory.
