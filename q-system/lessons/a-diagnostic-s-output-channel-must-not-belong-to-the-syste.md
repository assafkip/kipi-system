---
id: a-diagnostic-s-output-channel-must-not-belong-to-the-syste
kind: pattern
title: A diagnostic's output channel must not belong to the system it observes
date: 2026-08-29
---

A probe can run correctly, compute the right answer, and still tell you nothing, because the channel it reports on is owned and suppressed by the thing it was built to observe. Its silence is then indistinguishable from a clean result, and silence is the answer people want, so it gets accepted.

This is a near neighbour of "a check must be able to fail", but the failure sits one layer out. The predicate is sound and can fail. What is broken is the path from the predicate's verdict to the person reading it. Ordinary review cannot see it, because the code under review is correct.

Observed 2026-08-29 while hunting an import defect that appeared only on a Linux CI runner. The probe was a pytest plugin that inspected `sys.path` in `pytest_runtest_teardown` and wrote its findings with `sys.stderr.write`. pytest captures stderr during a test. The plugin executed, found the pollution it was looking for, and printed into a buffer that was discarded. The run produced no probe output at all, which read exactly like "scanned everything, found nothing wrong", and the wrong conclusion was one sentence away from being written down. Rewriting it to append to a file made the same probe report three polluted `sys.path` entries on the first attempt.

The same shape recurs wherever an observer runs inside its subject: a test-framework plugin writing to captured stdio, a hook whose stderr the harness swallows, a subprocess whose output the parent never drains, a logger configured by the application it is auditing, an assertion inside an `except` that the caller silently absorbs.

How to apply:

1. Before trusting a probe's silence, prove the probe can SPEAK. Make it emit one unconditional line at startup ("PROBE ARMED", plus the state it sees). If that line is missing from the output, nothing the probe would have said could have reached you either, and its silence carries no information.
2. Report on a channel the subject does not control. A file the probe opens and writes itself, a named pipe, a socket, an exit code. Not the stdio the harness owns, not the logger the application configures.
3. Ask who owns the buffer. Test frameworks capture stdio per test. Hook runners routinely discard non-zero-exit output. A parent that does not read a child's pipe will block or drop it. In each case the writer succeeds and the reader never exists.
4. Treat "the probe found nothing" and "the probe produced no output" as different results, and make them look different. An empty findings section under a printed ARMED banner is a negative result. A completely absent section is an unknown.
5. Distrust a diagnostic that has only ever returned the answer you were hoping for. Force it to fire once against a case you know is dirty, on the same channel and inside the same harness, before you rely on it against a case you are unsure about.

The general contract: an observer inherits the failure modes of whatever it reports through. Verify the reporting path with a known-true signal before reading anything into the absence of a signal.
