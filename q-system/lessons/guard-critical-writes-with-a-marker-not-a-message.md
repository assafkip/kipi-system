---
id: guard-critical-writes-with-a-marker-not-a-message
kind: pattern
title: Guard Critical Writes With a Marker, Not a Message
date: 2026-10-31
---

When shared mutable state (a working copy, a database schema, a deploy slot) is attended by automation that fires on activity, do not try to pause that automation by sending it a request. The request is itself activity: delivering it ends a turn, trips the trigger, and the automation runs on whatever half-written state exists at that instant. A notice that must travel through the same channel the trigger watches can never arrive before the thing it means to stop.

HOW:

1. Make the suppression out-of-band and readable by the trigger. Before touching shared state, the writer creates a run marker in a location the automation checks unconditionally at entry. Put enough in the marker to judge liveness: the owning process id, a start timestamp, and a declared maximum age. Scope one marker to one unit of work and delete it in a cleanup path that runs on success, failure, and signal.

2. Invert the decision. The automation's first action is to read the marker, not to act. If the marker is live, it exits without mutating anything and logs why. If the marker is older than its age bound or names a process that no longer exists, it removes the marker and proceeds. Staleness handling belongs in the automation, not the writer, so a crashed writer cannot wedge the system permanently.

3. Stop relying on a guarded re-run to repair damage. A second pass that only checks whether a resource looks busy will find it already released and conclude nothing is wrong. Prevention at entry is the only reliable point; detection afterward sees a consistent-looking result built from inconsistent inputs.

4. Serialize on the real lock, with a bound. Every write to the shared resource in the writer waits for the exclusive lock rather than failing fast, with an overall timeout and retries narrowed to the specific lock-contention error. Retrying on any error will mask genuine corruption and replay partial work. Log each wait so contention is visible rather than inferred.

5. Never let automation attribute work it did not author. If the automation commits, publishes, or persists on behalf of a writer, the generic identity it stamps on that output destroys the provenance of the real change and makes the mix-up invisible in history. Have it refuse instead.

TESTS (all three are required; the first two alone pass against a broken implementation):

- Positive suppression: fire the automation with a live marker present and assert no mutation occurred and the skip was logged.
- Contention tolerance: hold the lock for a few seconds while the writer runs, assert the run still succeeds, and assert the wait appears in the log so you know the wait path was exercised rather than the lock happening to be free.
- Negative control: stub out the wait-and-retry helper and assert the contention scenario now fails. Without this, a test that passes because the lock was never actually contended is indistinguishable from a test that passes because the fix works.
