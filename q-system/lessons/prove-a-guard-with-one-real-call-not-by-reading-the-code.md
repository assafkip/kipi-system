---
id: prove-a-guard-with-one-real-call-not-by-reading-the-code
kind: methodology
title: Prove a guard with one real call, not by reading the code
date: 2026-10-12
---

A limit, a detector and a meter all fail the same way: they get checked against a description of the system instead of a run of it. Four habits keep that from happening.

## 1. Verify a guard by executing it, not by scanning for it

A scan that marks a call site "covered" because its file references the check only proves the text is present. The check can sit below an early return the real path always takes.

How:
- Make the proof one real invocation plus an assertion on the artifact the guard writes (a ledger row, a counter, a log line). Presence of the call is not the assertion.
- Add the negative: feed an input that must be refused and watch it get refused. A check no input can turn red protects nothing.
- Place the guard at the single chokepoint the path cannot skip, above any early return, rather than at each caller.
- Enumerate every runtime root before trusting a coverage number: alternate working copies, linked checkouts, deployed or vendored copies. The code that runs live is often not the tree the scanner walked.

## 2. A detector needs a drain, or it reads as coverage

A number that has reported the same unresolved total for days is reporting a process failure, not a backlog.

How:
- Give every detector an owner and a consumer: something that converts findings into fixes on a stated cadence.
- Baseline the count and ratchet it. Fail when it rises, and fail when it has not fallen by the agreed date.
- Treat an unchanged count as its own alert, separate from the findings themselves.
- If nothing will ever drain it, delete the detector. A permanently red signal trains everyone to ignore it.

## 3. Unattended invocations need an explicit lean contract

When background work reuses the interactive entry point, it inherits the interactive setup: plugins, hooks, rules, ambient instruction files. Shared config grows over time, so the cost of a scheduled job rises with no change to the job.

How:
- Write down, in code, what a non-interactive invocation loads: working directory, config, extensions, tools, instruction files. Default every one of them to off and opt in deliberately.
- Measure per-invocation setup cost in a test with a ceiling. Growth in shared config then fails a check instead of appearing on a bill.
- Separate the entry point for unattended work from the one humans use, so a convenience added for humans cannot leak into every scheduled run.

## 4. Spend that never reaches the meter is invisible

If some execution paths do not report into the same ledger the owner reviews, the largest consumers can be the ones nobody can see.

How:
- Attribute every spawned worker, nested or parallel, to the ledger the owner actually reads. An unattributed path is an unbounded one.
- One job per worker. A bundled brief recreates the cost that splitting was meant to avoid, while looking like compliance with the rule.
- Where a path genuinely cannot be metered, cap it instead. A hard ceiling on an unobservable path beats a number you will never see.

## The general shape

After fixing a resource problem, ask one question before closing it: which run proved the fix, and what artifact did that run leave behind. If the answer is a code reading, the fix is a belief.
