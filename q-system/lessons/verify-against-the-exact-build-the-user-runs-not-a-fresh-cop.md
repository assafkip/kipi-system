---
id: verify-against-the-exact-build-the-user-runs-not-a-fresh-cop
kind: methodology
title: Verify against the exact build the user runs, not a fresh copy of it
date: 2026-07-06
---

When a fix produces no visible change across repeated attempts, first prove you and the user are exercising the same artifact before touching the code again. Deploy or build steps that mint a new, immutable address on every run create a trap: your fix lands on the newest instance while the person reporting the bug keeps hitting an older, frozen one that permanently serves the pre-fix code. The fix is real; it just isn't where they're looking.

Apply this as a verification discipline:

1. Pin one stable reference (a fixed alias, a promoted target, a single long-lived endpoint) and make every fix flow to that exact reference. Hand the user that same reference, never a per-build address.

2. When a symptom is invariant under every change you make, treat that as a signal you're not observing the code you edited, not that the bug is deeper. An unchanging output across genuinely different builds almost always means the observed build and the changed build are two different things.

3. Confirm identity before re-diagnosing. Embed a cheap version marker (a build id, a changed label, a header) that differs between old and new builds, and read it from the running artifact the user is on. If the marker is stale, the problem is delivery, not logic.

4. Run the ground-truth probe against the user's actual instance, not a fresh one you spun up to test. Testing a clean copy proves your fix works somewhere; it does not prove the user is running it.

The rule: every fix targets one pinned artifact, and verification queries that same pinned artifact. Divergence between 'where the fix went' and 'what the user runs' is the first hypothesis when nothing changes, not the last.
