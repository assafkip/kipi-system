---
id: cap-the-shared-choke-point-not-each-path-that-reaches-it
kind: pattern
title: Cap the shared choke point, not each path that reaches it
date: 2026-10-05
---

Cost and loop incidents often trace to guards placed on individual callers instead of on the resource they all call. Each past failure gets a cap on the path that just failed, so the guard population is whatever someone remembered to enumerate. Any caller outside that list, such as an ad hoc session calling the expensive service directly, bypasses every cap. Per-key caps also reset when the key changes: a limit scoped to a commit hash restarts on every fix commit.

How to apply it:
- List every caller of the expensive or looping resource from code, by search, not by memory.
- Put the cap inside the resource's own entry point, keyed on something a caller cannot reset (day, job, total). Every path then inherits it.
- Cap total spend per job or per day, not only worker starts or loop rounds. Starts and rounds are proxies for the cost you care about.
- Add a scan that lists every script calling the model, and fail a build when one ships without a budget check.

A lesson that lives only in a note is a suggestion. Move it into a script, hook or test that stops the behavior, because a session follows a note only if it surfaces and the session chooses to obey.

For agent orchestration, do not reuse one long-lived agent across tasks. Every message to a resumed agent re-reads its whole accumulated context, so cost grows with each turn. Start a fresh agent per task with a narrow brief, and the per-task cost stays flat.

Test for done: call the expensive resource directly, bypassing every wrapper, and confirm it still refuses once the budget is spent.
