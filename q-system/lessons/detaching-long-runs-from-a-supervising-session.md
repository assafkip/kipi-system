---
id: detaching-long-runs-from-a-supervising-session
kind: pattern
title: Detaching Long Runs from a Supervising Session
date: 2026-10-31
---

When work must continue after the process that requested it goes away, do not start it inside a call the supervisor tracks. Anything launched from a tracked or managed call inherits that call's lifetime: when the supervisor reaps the call for resource pressure, or the session process exits, the child dies with it — backgrounding tricks inside the call do not save it, because the kill targets the process group or the session's whole tree.

HOW:

1. Put the start logic in a standalone launcher (a script or small entry point) that is invoked as its own top-level command, outside the supervised call boundary. The launcher's only job is to spawn the real work fully detached: new session/process group, stdin closed, stdout and stderr redirected to files on disk, then exit immediately with the identifier of what it started.

2. Make the run's state live in files, not in memory and not in the caller's handle. On start, write a pid file plus a small status record (target, start time, log path). On completion, append a terminal marker line (a done record carrying exit status). Treat the file set as the single source of truth for "is it running, did it finish, did it succeed."

3. Have the requester poll, never hold. The supervising session reads the pid file and status file on an interval and returns; it never blocks on the child, keeps a pipe open to it, or stores a reference that only exists in session memory. Any observer that can read the directory can answer the same questions, including a fresh session after a restart.

4. Enforce concurrency limits in the launcher itself, not in the caller. Before spawning, check for a live run for the same target: pid file present and that pid actually alive. If one exists, or if the configured cap for that run kind is already reached, exit non-zero with a clear message and spawn nothing. This is what keeps repeated or retried start requests from stacking up duplicate workers that then compete for the same resources.

5. Make stale state self-healing. A pid file whose process is gone and that has no terminal marker is a crashed run: the launcher should clear it and be allowed to proceed, so a prior kill does not permanently block future starts.

6. Make partial progress idempotent. Since a detached run can still be killed mid-flight, have it checkpoint so that resumption does not duplicate side effects — record each externally visible action before or atomically with performing it, and check that record on restart.

TESTS TO WRITE:

- While a run is live, assert the pid file exists and names a live process.
- Invoke the launcher a second time for the same target while the first is live; assert it exits non-zero and that no additional process was spawned.
- Kill the supervising session while a run is live; assert the run keeps going and still writes its terminal marker.
- Leave a pid file pointing at a dead pid with no terminal marker; assert the launcher treats it as stale and starts successfully.
- Assert the terminal marker records the exit status, so pollers can distinguish "finished" from "finished successfully."

RULE OF THUMB: if the lifetime of the work is longer than the lifetime of the thing asking for it, the request and the work must be separated by a process boundary the supervisor does not own, and they must communicate only through durable state on disk.
