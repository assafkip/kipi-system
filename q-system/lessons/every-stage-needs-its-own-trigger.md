---
id: every-stage-needs-its-own-trigger
kind: pattern
title: Every stage needs its own trigger
date: 2026-07-27
---

## When this applies

An automated multi-stage job produces no visible output, and the first hypothesis is an external blocker (rate limit, bot protection, auth change, API change). Before accepting that, run the checks below.

## How to apply

**1. Prove the local path ran before blaming anything remote.**
- Search the full trigger inventory (schedulers, timers, cron tables, watchdogs, queue consumers, event handlers) for the specific stage that produces the visible effect. Search by name, do not assume.
- An external-block diagnosis requires evidence a request actually left the machine: a log line, a response code, a captured error. No attempt in the logs means the block hypothesis is unsupported.

**2. Give every stage its own registered trigger.**
- If stage B exists only as a step written inside stage A's procedure, B runs only when A happens to reach it. That is not wiring, that is a coincidence.
- Contract: for each stage, name the thing that starts it and where that starter is registered. A stage with no registered starter is dead no matter how correct its code is.
- Cheap audit: list all registered triggers, list all stages, diff the two lists. Anything on one list and not the other is the gap.
- The asymmetry to look for: a sibling path that works usually has both a live host process and its own schedule entry. The broken path has neither.

**3. Resolve executables explicitly in scheduled contexts.**
- Background and scheduler environments start with a minimal search path and no shell profile. A bare command name that resolves interactively fails there.
- Use an absolute path or an explicit configured variable, with a startup lookup that fails loudly rather than silently.
- Test it by running the entry point under a deliberately stripped environment, not from your own shell. Passing interactively proves nothing about the scheduled run.

**4. Make handoff writes conditional, never unconditional.**
- A producer that always writes its output will overwrite ready work with an empty result whenever it wakes outside its active window.
- Persist only a non-empty result, or require an explicit clear operation to empty the handoff. Treat "empty" as a state distinct from "no new data this cycle."
- Reproducer: stage two items, run the producer under conditions that yield zero items, assert both items survive.

## Failure signature

Output appears when a human runs the job by hand but never on schedule. That combination points at the trigger inventory and the runtime environment, not at the remote service.
