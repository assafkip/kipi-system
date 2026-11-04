---
id: measure-tool-usage-from-system-logs-not-conversation-records
kind: methodology
title: Measure Tool Usage From System Logs, Not Conversation Records
date: 2026-11-04
---

When you need to know how often a tool, API, or service was actually invoked, treat human-readable conversation or session records as the least reliable source and go to the system's own instrumentation first.

How to do it:

1. Enumerate every place the tool leaves a trace before counting anything. Typical sources: the tool's own server or daemon log, shell/command history, process accounting, request logs on the receiving side, audit tables, and metrics counters. Note which of these are complete by construction (written on every invocation) versus incidental (written only when something is displayed, logged at a verbose level, or echoed back).

2. Pick a ground-truth source that is written at the point of execution, not at the point of presentation. A counter incremented inside the call path cannot miss calls; a record produced by a display layer only captures calls that layer happened to render.

3. Count from the ground-truth source first, independently, before looking at the narrative record. Counting the narrative first anchors your expectation and makes you rationalize the gap instead of investigating it.

4. Then reconcile: join the authoritative events back to the narrative turns by timestamp or request ID. Classify each authoritative event as matched or unmatched. Unmatched events are the finding.

5. Investigate the unmatched set for a mechanism rather than dismissing it as noise. Common mechanisms for invisible invocations:
   - calls made inside background jobs, daemons, cron entries, or queued workers
   - calls made from scripts, wrappers, or helper utilities that invoke the tool several times per outer action
   - retries, timeouts, and automatic fallbacks that fire more than once per logical request
   - batch or fan-out paths where one user-facing action maps to many underlying calls
   - warmups, health checks, and cache refreshes

6. Report both numbers and the ratio, with the mechanism named. "Authoritative count N, visible count M, gap explained by X" is an actionable result; a single number is not.

7. If no complete source exists, treat that as the first defect to fix. Add a counter or structured log line at the call site before drawing conclusions about volume, cost, rate limits, or quota.

Why it matters: understating invocation counts by a factor of roughly two is easy and silent. Decisions downstream of the count — capacity planning, cost attribution, rate-limit headroom, deciding whether a dependency is load-bearing, or judging whether a feature is used — all invert when the real number is double the visible one. The error is systematic and always in the same direction: presentation layers can only undercount, never overcount.

General rule: count events where they happen, not where they are narrated. Any record produced for human consumption is a sample of execution, not a census of it. Validate the gap on more than one case before trusting the ratio, since the size of the gap depends on how much automation sits behind each visible action.
