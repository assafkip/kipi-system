---
id: the-most-used-path-is-usually-the-least-judged-one
kind: pattern
title: The most-used path is usually the least-judged one
date: 2026-09-07
---

# Pattern

Quality checks get attached to whichever execution path existed when the check was written. A lighter path added later for speed or convenience reuses the production steps but not the evaluation steps, then becomes the one people reach for daily. The result is that the highest-volume path carries the thinnest acceptance signal, and every run on it looks successful.

## How to detect it

- List every way work can enter the system: each command, flag, mode, or shortcut that produces the same class of output.
- For each path, write down which evaluation stages actually execute on it. Not which stages exist in the codebase; which ones run on that path.
- Rank the paths by usage. If the most-used path has the fewest evaluation stages, that is the defect.
- Read the acceptance record for a recent run on the light path. If the only recorded signals are structural (exit code zero, schema valid, required checks green), nothing in that record says the output was any good.

## How to fix it

- Attach evaluation at the shared stage that all paths pass through, not at the entry point. An entry point is where the omission happens; a chokepoint downstream of every entry cannot be skipped by adding a new front door.
- Make the absence of an evaluation stage an explicit recorded state rather than silence. A run that skipped the judge should say UNJUDGED in its trail, so a reader can distinguish "passed the judge" from "never met one".
- Prove the wiring by running the light path against input the judge should reject. If it still comes back accepted, the check is not attached, regardless of what the code inventory shows.

## Why it survives review

The evaluator exists, so anyone auditing the component list concludes quality is covered. The gap is a missing edge between a component and a path, not a missing component. Only tracing each entry path end to end surfaces it.

## The repeat signal

When the same analysis is written more than once with no code change between writings, the analysis is not the deliverable and repeating it changes nothing. A finding that recurs unchanged across investigations is evidence that the fix has never been attempted, and the next action is wiring, not another writeup.
