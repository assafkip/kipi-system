---
id: designing-and-verifying-stop-conditions-in-unattended-long-r
kind: methodology
title: Designing and Verifying Stop Conditions in Unattended Long Runs
date: 2026-10-31
---

## When to apply
Any job meant to run unattended for hours (batch scrapers, migrations, simulations, soak tests, overnight pipelines) that contains logic deciding when to abort early.

## How to build the stop condition
1. Treat every abort predicate as a classifier with two classes, not one. Before writing it, collect at least one example you want it to match and two or three examples you want it to ignore — same source, same shape, different meaning.
2. Prefer the narrowest match that still works: exact codes or typed fields over message text; anchored or structured matching over free substring search. A bare substring taken from one real message will almost always be broader than the concept you had in mind.
3. Derive the predicate from the class of signals, not from the single sample in front of you. Ask "what else could the upstream system emit that contains this fragment?" and write that answer down as a case.
4. Write the negative tests first and make them fail if the predicate is loosened. A predicate with only positive coverage is untested — it cannot distinguish "correct" from "matches everything."

## How to avoid duplicated decision logic
1. If the same marker, literal, or threshold appears in more than one entry point, extract it into one shared function or config value with one test suite. Copies drift and get fixed one at a time.
2. Grep for the literal before you consider a fix complete; fix every occurrence in the same change, or delete the copies in favor of the shared one.

## How to make an early stop loud
1. Assume no one reads logs until the run was supposed to be over. A log line is not a notification.
2. Emit an explicit terminal event on every exit path — success, planned stop, and abort — carrying the reason and the elapsed time versus the intended duration.
3. Add an external expectation check: a heartbeat the job writes periodically plus a watcher that alerts when heartbeats stop before the scheduled end time. The watcher must live outside the process it watches, so a crash cannot silence it.
4. Alert on "finished suspiciously early" as its own condition. Duration far below plan is a defect signal even when the exit code is zero.
5. Where the stop is recoverable, prefer pause-and-ask or bounded retry with backoff over hard exit, so a false positive costs minutes instead of the whole window.

## Review checklist
- Does each abort predicate have at least one test that feeds it a near-miss input and asserts it does not fire?
- Is the matching literal defined exactly once?
- Would an abort in hour one reach a human before the scheduled end?
- Is an unexpectedly short run itself an alertable outcome?

## Why this ordering matters
The over-broad predicate and the silent exit are independent faults that multiply: one causes a wrong stop, the other hides it until the opportunity window has closed. Fixing only the predicate leaves the next unrelated failure equally invisible, so add the detection path even when you believe the logic is now correct.
