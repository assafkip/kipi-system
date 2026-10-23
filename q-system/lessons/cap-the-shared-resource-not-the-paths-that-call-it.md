---
id: cap-the-shared-resource-not-the-paths-that-call-it
kind: pattern
title: Cap the shared resource, not the paths that call it
date: 2026-10-05
---

A limit written on a caller path only binds that caller. When several entry points converge on one expensive operation (a model call, a review cycle, a paid API, a build runner), per-path caps leave every unlisted path uncapped, and a new caller added later is uncapped by default. The limit belongs where the spend happens.

How to place a limit on a shared expensive operation:

1. Name the operation that actually costs money or time, then enumerate every caller of it from the code, not from memory. The uncapped path is usually the direct one a human or a session invokes by hand.
2. Put the counter inside the operation itself, so every caller decrements the same budget. Caller-side caps become redundant, which is the correct outcome.
3. Choose a counter key that cannot be reset by the work itself. Keying a retry budget to the artifact under change (a revision id, a content hash, a head commit) means each fix resets the count and the loop never terminates. Key it to the unit you want bounded instead: the task, the day, the job.
4. Make the budget a required argument, not an optional one. If a new script can call the expensive operation without declaring a ceiling, ceilings will be missing from most scripts.
5. Emit per-job consumption to a place a query can read. An unmeasured budget cannot be tuned and an overrun cannot be attributed to a job.

Two habits that compound the same cost:

- A bound recorded as a note for a future reader is not a bound. Whoever reads it next may follow it loosely, which looks like compliance and costs nearly as much as none. Convert it to a counter in the code path, then let the note explain the counter.
- Resuming one long-lived worker re-reads its accumulated context on every message, so cost per step grows with session length. Prefer a fresh worker per task with a narrow brief; carry state in files between them rather than in one worker's history.
