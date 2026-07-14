---
id: an-auto-commit-to-the-current-branch-strands-unmerged-work
kind: pattern
title: An auto-commit to the current branch strands unmerged work and makes it read as deleted
date: 2026-07-14
---

A hook that auto-commits changed files stages them to WHATEVER branch is currently checked out. This is invisible and convenient until the working tree sits on a branch that does not contain a body of work built on a different, unmerged branch. Then the auto-commit does two quiet kinds of damage. It commits routine churn onto the checked-out branch, widening that branch's divergence from the one holding the real work. And because the checked-out branch never had the real source, the working tree shows only empty scaffolding, so the work looks DELETED. It is not. It is on another branch, the auto-commit is steadily driving the two branches apart, and an offsite backup that pushes the OTHER branch starts failing on non-fast-forward.

How to diagnose and prevent it:

1. Before concluding that code was deleted, check the branch, not the tree. Read the current branch, then test whether the file exists on other branches and which branches contain the last commit that had it. Source absent from the working tree but present on another branch was never deleted; it was stranded. A grep of the working tree proves nothing when the wrong branch is checked out.

2. An auto-commit hook needs a branch expectation, not just a target. Either pin it to the intended branch, or have it refuse (or warn loudly) when the checked-out branch is not the one work is expected on. A hook that silently commits to any branch turns a wrong-branch checkout into a slow, compounding divergence no one sees until the working tree looks empty.

3. Treat a failing offsite-backup push as a divergence alarm, not noise. When the backup that pushes the work-branch starts rejecting on non-fast-forward while the auto-commit keeps succeeding on the checked-out branch, the two have split. Reconcile the branches before the gap grows; the fix is a merge, not a rebuild.

The durable rule: an auto-commit that stages to the current branch is a foot-gun on a wrong-branch checkout. It never deletes work, it strands it, and it hides the strand behind empty scaffolding. Check the branch before believing code is gone, and give the auto-commit a branch expectation so it cannot quietly drive a divergence.
