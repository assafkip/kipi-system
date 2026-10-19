---
id: put-spend-limits-on-the-shared-choke-point-enforce-them-in-c
kind: methodology
title: Put spend limits on the shared choke point, enforce them in code, and keep agent context fresh
date: 2026-10-19
---

When an automated system burns far more budget than expected, check for these four recurring gaps.

1. Cap the shared choke point, not the path that last failed. After an incident, teams usually add a limit to the specific loop that misbehaved. Other callers can still reach the expensive resource directly and bypass every limit. Instead, find the single resource that all paths converge on (a reviewer, a model endpoint, a paid API) and enforce the limit there, keyed on something callers cannot reset. A per-commit or per-entry-point counter resets whenever the input changes, so prefer a counter tied to the logical unit of work, such as the change request or ticket. Then enumerate every caller mechanically rather than by memory.

2. Turn lessons into enforcement. A written note or memory item depends on someone seeing it and choosing to obey it, and in practice it gets followed loosely. If a lesson matters, encode it as a hook, a script check, a test, or a hard limit, and treat the note as documentation of that mechanism, not a substitute for it.

3. Measure and bound spend per job. Nothing should be able to ship a script that calls a paid model without a budget check. Do three things: (a) keep an automated inventory of every script that calls the model, and fail CI if a caller has no budget guard; (b) record usage per job; (c) add a circuit breaker that halts a job when it exceeds its allowance, and alerts on it.

4. Don't reuse one long-lived agent for unrelated tasks. Each message to a resumed agent re-reads its entire accumulated context, so cost grows with history length. Start a fresh agent for each task with a narrow brief containing only what it needs, and pass results forward as small summaries.

Quick audit: list all callers of the expensive resource, confirm each passes through one enforced limit, confirm the limit survives input changes, confirm the lesson is enforced in code, confirm per-job spend is measured, and confirm long-running agents are not carrying stale context.
