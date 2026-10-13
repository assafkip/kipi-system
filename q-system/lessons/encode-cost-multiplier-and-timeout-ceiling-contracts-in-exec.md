---
id: encode-cost-multiplier-and-timeout-ceiling-contracts-in-exec
kind: pattern
title: Encode cost-multiplier and timeout-ceiling contracts in executable checks
date: 2026-10-12
---

When an option multiplies per-unit cost and a hard time limit bounds each unit of work, the relationship between them is an implicit contract. If it exists only as a prose comment in a file nobody is editing, the knowledge is present but cannot fire, and the same failure repeats in a different area of the codebase.

Symptoms to recognize:
- Intermittent failures hitting a different subset of items on each run.
- A timeout or cutoff set near the mean of the measured duration distribution, so roughly half of the expensive runs get cut off.
- A prior fix that was to disable the feature instead of resolving the budget mismatch.

How to apply the lesson:
1. Measure the duration distribution (min, max, mean) for each configuration of the option, not just the default. Compare the timeout to the upper tail, not the mean. A cutoff within a small margin of the mean will sever a large share of runs.
2. Express the contract in code instead of a comment. Keep a single shared definition that maps each cost-affecting option to an expected cost multiplier, and have the call path validate the requested options against the ceiling before dispatch.
3. When the check fails, force an explicit choice: turn the option off, split the work into smaller units, raise the limit with a justified margin, or use a fallback path. Never let it run and time out silently.
4. Add a test that fails if someone enables a costly option without a matching budget or fallback.
5. Put the guard where the option is set, not where the original diagnosis was written, so any new caller or lane hits it automatically.
6. When writing an incident analysis, search for earlier occurrences of the same failure class in other areas. If one exists, record that the root cause was a missing executable link between the knowledge and the code path, not just the specific numbers.

Rule of thumb: a lesson that lives only in a comment protects only people who happen to read that comment. Convert it into a check that runs on every path that can trigger the failure.
