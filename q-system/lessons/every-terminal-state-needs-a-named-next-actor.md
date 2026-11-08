---
id: every-terminal-state-needs-a-named-next-actor
kind: pattern
title: Every Terminal State Needs a Named Next Actor
date: 2026-11-07
---

## Problem shape

Automated pipelines accumulate retry caps and bail-out branches: max attempts, max convergence rounds, max rebase tries, unmergeable states, review stalemates. Each cap is added for a good reason: it stops an infinite loop that burns resources and desensitizes everyone to alerts. But a cap only answers "may the loop stop?" It does not answer "who acts next?"

The default answer engineers reach for is a notification plus a tracking record: emit an alert, open a ticket, apply a label. That feels like a handoff. It is not one, because nothing is subscribed to the label and no process is accountable for draining the queue. Work ends in a state that is neither failed nor done, and the records that document it are themselves never picked up. The failure is silent and compounding: throughput looks fine because nothing is erroring, while a growing fraction of work is parked.

## Why it persists

Three reinforcing causes:

1. **Manual review is treated as a tier in the escalation ladder when it has no capacity budget.** If no one has committed hours per week to draining the parked queue, routing to a human is routing to nowhere. The ladder has a rung that does not bear weight.
2. **The policy exists but is not enforced at the point of writing.** Teams often already have a written rule that unattended deferral is a defect. Rules in documents do not fail builds. Each new cap site is written by someone solving a loop problem, not auditing a handoff contract.
3. **The capability exists but is not wired.** Frequently the fallback mechanism, an alternate executor, a different strategy, a reset path, is already implemented and reachable. Nothing selects on the state that should trigger it. Code presence is mistaken for code coverage.

## The pattern

Treat "next actor" as a required field on every exit, enforced mechanically.

**1. Enumerate exits as data, not prose.** Build a machine-readable registry of every terminal state the system can reach. One row per state, with: the state identifier, the code site that emits it, the consumer that selects on it, and the action that consumer takes. Prose documentation of loop exits will not stay in sync and cannot be queried.

**2. Make the consumer field mandatory and typed.** A consumer must be an automated process that polls or subscribes to the state, not a notification channel, a label, or a role name. "Alert sent" is a side effect, not a consumer. Reject rows whose consumer is a person, a team, or empty.

**3. Fail CI on unconsumed states.** Write a check that cross-references emitted states against registered consumers in both directions: every state a code path can emit must have a consumer, and every registered consumer must select on a state something actually emits. Scan for the phrases that signal defective deferral, variants of "needs review," "someone should look," "resolve manually", in exit messages and in the registry. A grep-based lint on exit-site strings catches most new violations at authoring time. This converts the written policy into a gate.

**4. Require at least one automated alternate attempt before any human notification.** When a strategy exhausts its retries, the next step is a *different* strategy, not a page: a different executor, a reduced-scope variant, a fresh environment, a decomposition of the work into smaller units, or a rollback to a known-good point. Retrying the same approach harder is what the cap correctly prevented; trying a different approach is what the cap was never meant to prevent. Caps should bound strategy repetition, not strategy diversity.

**5. Give every terminal state a scheduled sweep with a deadline.** Even with a consumer wired, add a time-based process that re-examines parked items and escalates by age. Define an explicit maximum dwell time per state. Anything exceeding it is a monitored defect with a visible count, not a quiet backlog entry.

**6. Make the parked set a first-class metric.** Publish the count of items in each non-done state, broken down by age. Success is not "zero errors"; it is "zero items parked beyond their dwell limit." Without this number, the problem is invisible by construction, because parked work emits nothing.

## Auditing an existing system

Go cap by cap. For each retry limit, round limit, timeout, and early return, ask: what reads this outcome? Then verify by searching for a reader that selects on exactly that state or field. Classify the gaps: capability missing, capability present but unwired, or consumer present but never scheduled. The unwired ones are the cheapest fixes and usually the majority.

## Generalization

The underlying rule applies well beyond pipelines: any state machine with an exit that routes to unbudgeted attention has a leak. Queues with no drain owner, error branches that only log, feature flags with no removal trigger, and deprecation warnings with no enforcement date are the same defect. The discipline is to make "who or what consumes this, and by when" a mandatory, testable property of every terminal state, and to prefer an automated alternate attempt over a notification whenever one exists.
