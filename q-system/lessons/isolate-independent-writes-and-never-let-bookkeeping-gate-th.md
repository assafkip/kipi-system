---
id: isolate-independent-writes-and-never-let-bookkeeping-gate-th
kind: pattern
title: Isolate independent writes, and never let bookkeeping gate the deliverable
date: 2026-08-03
---

When a job writes N independent records to an external service and then produces one user-facing output, three failure modes compound. Build against all three.

**1. Fail per item, not per loop.**
If each write is an independent fact, one write's failure says nothing about the next. Wrap each iteration in its own try/except, record per-item status (ok / failed / skipped), and continue. At the end, report the tally and re-raise or retry only the failed subset. A single transient network error should cost one record, not the remainder of the batch.

**2. Order by priority: deliverable first, bookkeeping second.**
If a run both updates internal state and emits the output someone actually consumes, emit the output first, or at minimum put the bookkeeping in a path that cannot abort the emit. Otherwise an outage in a system nobody reads takes down the thing everybody reads. Test for this explicitly: force the bookkeeping dependency to fail and assert the deliverable still lands.

**3. Verify any contract you did not write.**
Data produced by a different runtime (another service, a hosted job, a partner) has a shape you are guessing at until you have captured a real instance of it. Grepping your own repo proves nothing about what the other side emits. Before writing parsing logic, capture one live payload, store it as the fixture, and derive the parser from it. Add a runtime shape check that logs loudly on mismatch instead of silently taking a wrong branch.

**Why a green test suite does not clear this.**
Fixtures authored from the same mental model as the code make the suite self-consistent on a fiction. A test that encodes the code's assumption cannot falsify that assumption. The falsifier is captured live data (or a contract check against the producer), not another handwritten fixture.

**Checklist before shipping a batch-write job:**
- Each iteration isolated; per-item outcome recorded.
- The user-facing output cannot be blocked by an internal write.
- Every externally-produced payload has one captured real sample as its fixture.
- One test forces the external dependency down and asserts the deliverable survives.
