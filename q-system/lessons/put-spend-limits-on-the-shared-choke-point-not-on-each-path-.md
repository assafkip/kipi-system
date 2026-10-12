---
id: put-spend-limits-on-the-shared-choke-point-not-on-each-path-
kind: methodology
title: Put spend limits on the shared choke point, not on each path leading to it
date: 2026-10-12
---

When automation burns far more budget than expected, the cause is often that limits were added one at a time to whichever path last failed, while the expensive shared resource (a reviewer, a model call, a paid API) had no limit of its own. Any caller that goes straight to the resource bypasses every per-path cap.

How to apply:
1. Enumerate the choke points. List every place a costly or looping operation is ultimately invoked, by scanning the codebase for callers rather than from memory. Include a check that flags new scripts calling the resource without a budget.
2. Enforce caps at the resource boundary. Put the round, count, or token limit inside the shared entry point, keyed by a stable identity such as the work item, not by something that resets on every change (for example a commit hash that changes with each fix). Per-path caps can remain as defense in depth.
3. Make a budget breaker the default. Track spend per job or per bot, and halt or escalate when it is exceeded. A script should not be able to ship without passing through this check.
4. Turn lessons into enforcement. A written note or memory only works if it surfaces and is obeyed, and partial compliance is common. When an incident teaches a rule, encode it as a hook, script limit, or test, and treat the note as documentation only.
5. Keep agent context small. Resuming one long-lived agent makes every message re-read its entire accumulated context, so cost grows with history. Prefer fresh agents per task with narrow briefs and only the context they need.
6. Verify the property, not a proxy. Test that total spend on the resource is bounded, not merely that individual paths have limits.

Signal to look for: after an incident, ask whether the new cap sits on the path that failed or on the thing that all paths share. If it is the former, move it.
