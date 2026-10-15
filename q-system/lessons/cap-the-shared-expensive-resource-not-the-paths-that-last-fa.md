---
id: cap-the-shared-expensive-resource-not-the-paths-that-last-fa
kind: pattern
title: Cap the shared expensive resource, not the paths that last failed
date: 2026-10-04
---

Cost and loop guards tend to get added to whichever code path just caused an incident. Each cap then covers only that path. A caller that reaches the expensive resource directly (a reviewer, a model, a paid API) bypasses every one of them. Caps that reset on a changing key, such as a per-commit counter that restarts on each new commit, also fail to bound the total.

Pattern:
- Put the limit at the choke point itself: the single function or service every caller goes through. Key it on the stable unit of work (the change request, the job), never on a value that each fix or retry regenerates.
- Enumerate callers with a scan, not from memory. If you cannot list every script that calls the expensive resource, you cannot claim it is capped.
- Give each job a spend budget, measured and enforced, that acts as a circuit breaker. A script that calls a model should not be able to ship without a budget check, and a test should fail when a new caller appears with none.
- Do not store a lesson as a note and expect compliance. A reminder that surfaces only when someone reads it will be followed loosely. Turn the lesson into a code-level limit, hook or test, and treat the note as documentation of that mechanism.
- When orchestrating automated agents, do not keep resuming one long-lived agent. Every message re-reads its entire accumulated context, so cost grows with each turn. Start a fresh agent per task with a narrow brief.

Check before shipping any automation: which single point do all callers share, what limits it, and what test fails if someone adds a path around it?
