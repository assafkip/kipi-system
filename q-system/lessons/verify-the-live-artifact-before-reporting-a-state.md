---
id: verify-the-live-artifact-before-reporting-a-state
kind: methodology
title: Verify the live artifact before reporting a state
date: 2026-07-20
---

When you conclude that a component is broken or working, base that conclusion on the live artifact itself, not on an indirect signal. Log lines, config-path guesses, alarm text, and cached state files are proxies; every time a proxy has been checked against the live artifact, the proxy was the one that lied.

Two traps recur:

1. Reading a stale record as if it were current. Check the timestamp on any log or state file before you treat its contents as today's truth. A days-old error is not today's breakage.
2. Checking one location and concluding "not configured" when the real value lives somewhere else. One negative lookup is not absence.

The fix is cheap and always the same: query the live thing directly. Run the probe, hit the datastore, load the page, read the running process's output, inspect the actual ignore[PATH] state. Prefer proof over inference: when you can drive the real action and read the result back (perform the operation and read the returned identifier), do that instead of guessing success from a side signal.

One more habit for recurring alerts: before you re-triage a repeating failure on a surface, read any existing root-cause notes for that surface and report the delta. Did the prescribed fix ship? What changed since last time? Re-deriving yesterday's finding wastes the run and hides whether the earlier fix landed.
