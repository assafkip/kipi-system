---
id: idempotent-verdict-jobs-guard-on-published-state-order-write
kind: pattern
title: Idempotent Verdict Jobs: Guard on Published State, Order Writes by Authority
date: 2026-10-31
---

## Problem shape

An automated job computes a judgement about a specific immutable revision (an approval/rejection, a pass/fail, a score) and publishes it to one or more external surfaces. If the job is killed partway through publishing, or if a supervisor misreads its liveness and relaunches it, the same revision can receive two independent judgements. Re-running a non-deterministic analysis is not harmless: the second verdict can contradict a first verdict that outside parties have already seen and acted on, which costs far more than the missing run.

## HOW

**1. Derive "already done" from the published artifact, never from the runner's own bookkeeping.**

Before doing any work, query the external surface for an existing verdict scoped to the *exact* revision identifier (content hash / commit id / immutable version), not to the branch, ticket, or parent object. If one exists, exit immediately with a distinct non-zero code and no side effects. Treat log files, temp files, PID files, and task-tracker state as advisory only: a process that dies between two writes leaves them indistinguishable from a process that never started. An empty log is not evidence that nothing happened.

**2. Provide one explicit escape hatch.**

The guard must be overridable by an explicit `--force` style flag so a human can deliberately re-judge. Default is refuse; override is loud and never inferred from heuristics.

**3. Order the publish steps so that an interrupt loses the cheapest thing.**

When a verdict fans out to multiple surfaces, rank them by authority and recoverability, then write in order: the surface that other automation and the guard in step 1 read from goes **first**; human-readable prose, summaries, and notifications go **last**. The invariant you want is that a kill between any two writes can only drop an artifact that is regenerable and non-binding, never the one that gates behavior. Writing the chatty artifact first inverts this: the kill then publishes a judgement with no machine-visible record that it happened, which is exactly the state that invites a contradicting re-run.

**4. Make the guard read the same surface the first write targets.**

If step 1 inspects surface A but step 3 writes surface B first, a crash after B still looks un-run. Point the guard at whichever surface is written first, or make the guard check all of them and treat any one hit as "already judged."

**5. Prefer a conditional/compare-and-set write where the API allows it.**

If the surface supports create-if-absent or write-if-version-matches, use it. A pre-flight read plus an unconditional write still has a race window when two runners start concurrently; a conditional write closes it and lets the loser exit cleanly.

## Test it

Build a fixture target that already carries a verdict on its head revision and assert that a fresh run exits non-zero, emits the "already judged" reason, and performs zero writes. Add a second fixture where a verdict exists on a *different* revision of the same target and assert the run proceeds normally — this is the case a branch-scoped guard gets wrong. Then simulate the interrupt: kill the job between the authoritative write and the prose write, and assert that a subsequent run refuses to start.

## Generalizes to

Any worker that publishes externally visible, consequential decisions: CI gates, deploy promotions, automated moderation, billing or payout events, outbound notifications. The two rules are the same everywhere — gate on the durable published fact keyed by the immutable input identity, and sequence side effects so the partial-failure state is safe rather than ambiguous.
