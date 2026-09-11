---
id: bind-a-verification-run-to-the-version-it-verifies
kind: pattern
title: Bind a verification run to the version it verifies
date: 2026-08-31
---

A run that starts before the change lands tests the old artifact and reports a verdict about code that was never under test. The failure is silent: the log looks normal, the exit code is real, and the natural reading of a bad result is "the fix did not work" rather than "the fix was absent".

How to prevent it:

1. Stamp identity at start. At the top of any verification run, record the version identifier of every artifact the run exercises: content hash, revision id, or build id. Write it into the run's own log or result record, not just to the console.
2. Compare, do not assume. Before trusting a result, compare the stamped identity against the change you meant to verify. If the run's artifact predates the change, the result is void, not negative.
3. Make the check refuse. Encode the comparison in the runner so a mismatched run aborts or marks itself INVALID. A note in a checklist does not survive a hurried session; a precondition that exits nonzero does.
4. Treat concurrent edit and run as a hazard class. Any workflow where an artifact can be modified while a long job reads or executes it will hit this again by a new route: an edit mid-read, a job queued before a commit, a cached build, a stale deployed copy. Fix the class, not the instance.
5. Escalate on recurrence. The first occurrence invites a one-off explanation. When the same wrong result arrives by a second route, the correct conclusion is that no invariant exists, and the fix is a barrier rather than a better explanation.

The general rule: a result is only evidence about the version it actually ran against. If the run cannot name that version, it produced no evidence at all.
