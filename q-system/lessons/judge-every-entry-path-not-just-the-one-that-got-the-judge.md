---
id: judge-every-entry-path-not-just-the-one-that-got-the-judge
kind: pattern
title: Judge every entry path, not just the one that got the judge
date: 2026-10-04
---

When a system has several ways to produce the same kind of output, quality checks tend to end up on the path that was built first or is easiest to instrument. The path people actually use can be the one with no judge at all.

Pattern:
- List every entry path that can produce the deliverable. For each, write down which checks run: structural gates, a fidelity check against a reference, a style or quality review, an independent critic.
- Flag any path where the only check is a structural pass such as a lint or schema gate. That signal says the output is well-formed. It says nothing about whether the output is right.
- Treat a clean gate report on an unjudged path as unverified, not as passing. A clean-and-wrong result is the expected failure there.
- Wire the same content judge into every path, or make the missing judge an explicit, recorded decision with an owner and a date.
- Add a test that generates a real batch through each path and has the judge score it. A path nobody has ever run end to end through the judge is untested, however green its gates are.
- When a root-cause review repeats the same finding across several dates, the fix is not another write-up. Turn the finding into a check that fails when a path lacks its judge.

Signs you have this problem: the most-used path has the thinnest review, acceptance is described only as 'gates: clean', and each incident review restates the earlier one with new evidence but no change.
