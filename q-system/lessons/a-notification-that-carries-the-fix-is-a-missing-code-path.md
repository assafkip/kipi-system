---
id: a-notification-that-carries-the-fix-is-a-missing-code-path
kind: pattern
title: A notification that carries the fix is a missing code path
date: 2026-08-03
---

## The shape

Automation reaches a state it has fully diagnosed, then hands the diagnosis to a human along with the exact command that resolves it. Every fact needed to act is already in memory at the moment the code decides to delegate: the condition was evaluated, the precondition was checked, the remediation string was constructed. The only thing missing is the call.

This is a defect in the producer, not a wording problem in the message. Rephrasing the alert changes nothing; the human is still the interpreter of a decision the machine already made.

## The detector

Grep the codebase for alert, notify, page, and log-warning payloads that contain an imperative command, a shell invocation, an API call, or a link that does one thing. For each hit ask two questions:

1. Does the code have every input the command needs at this point?
2. Is the operation reversible or idempotent?

Both yes means the notification is a stand-in for a call site. Both yes with a human in the middle means the queue depth of pending work equals human availability, which is the actual outage.

## The fix

Replace the message with the action, then notify only on the outcome:

- Guard the action with the same predicate that used to guard the alert. If the predicate was strong enough to justify telling a human exactly what to do, it is strong enough to gate the call.
- Attempt the action; report success as a state change, not a task. Report failure with the reason, which is now the only thing a human can add value to.
- Keep the human path only for authorization classes: spend, publish, delete, or anything with an irreversible external effect. Those are decisions, not executions.

An alert that says something was done is signal. An alert that says something should be done is a queue with one worker who is asleep.

## The second failure, which is worse

When a team recognizes this class and fixes it, the fix usually lands on the one surface where it was noticed. The insight gets written into a header comment or a postmortem and stops there. Other surfaces with an identical shape keep paging, because nobody searched for siblings.

Two disciplines close that gap:

- **Name the class, then sweep for it.** When a fix is motivated by a general defect class, the same change ticket includes a repo-wide search for the class and an explicit list of every other site found, each either converted or recorded with a reason. A class fix that touches one file is an unfinished fix.
- **Prove the fix has a caller.** A remediation helper written to replace a human step is inert until something invokes it. Search for references outside its own tests before calling it shipped. Zero non-test callers means the old behavior is still the live behavior, and the alert volume will confirm that whether or not anyone reads it.

A declared-capability manifest checked in CI catches the second one deterministically: a helper that exists but is undeclared and uncalled fails the check instead of quietly meaning nothing.

## Acceptance test

Before closing this class of work, the check that can actually fail is a measurement, not a reading: count the notifications emitted over a fixed window and classify each as authorization-required or self-executable. The self-executable count going to zero is done. A code review saying the fix looks right is not.
