---
id: never-chain-a-backlog-drainer-behind-a-producer
kind: pattern
title: Never chain a backlog drainer behind a producer
date: 2026-08-17
---

## The shape

A scheduled chain runs stages in order: fetch, transform, then deliver. The delivery stage is where pending work leaves the system. Many orchestrators skip a stage whose upstream produced zero items, so on every tick with no new input the whole tail of the chain silently does not run. Runs still report success, because nothing failed. Nothing ran.

The surface bug is a per-stage flag (emit-empty / always-output / run-on-empty). The structural bug is that a stage which drains a queue was made conditional on new arrivals.

## The distinction to make

For each stage, ask: what is its input set?

- **Producer-scoped:** operates only on the items the previous stage just emitted. Chaining is correct. No new items, nothing to do.
- **State-scoped:** operates on everything currently matching a pending condition (unsent, unreconciled, unpublished, retry-eligible). Its input comes from stored state, not from the upstream stage. Chaining it is a category error.

A state-scoped stage placed downstream of a producer inherits a guarantee it was never meant to have: "pending work leaves within one interval" quietly becomes "pending work leaves within one interval, provided unrelated new input arrived." Corrections, backfills, manual releases, and retries are exactly the items that arrive without new upstream traffic, so they are exactly the items that stall.

## How to build it

1. **Give state-scoped stages their own trigger.** Separate schedule, separate entry point. It queries pending state directly and runs whether or not anything upstream fired. Coupling to a producer is optional optimization, never the only path.
2. **If a chain must stay intact, make empty a value, not a halt.** Set the emit-on-empty flag on every upstream stage so an empty batch still propagates and downstream stages still evaluate their own conditions.
3. **Alarm on the stage, not the chain.** Track last-successful-execution per stage and alert when a stage exceeds its expected interval. A chain-level success signal cannot see a stage that never started.
4. **Add a staleness check on the pending set.** Alert on `oldest pending item age > N intervals`. This is the check that fails for the right reason: it goes red whether the cause is a skipped stage, a stuck flag, or a bad filter.

## Test that can actually fail

Run the chain on a tick with zero new upstream items and at least one item already sitting in the pending state. Assert the item leaves. A test that seeds new upstream input alongside the pending item passes for the wrong reason: it exercises the producer path and never the drain path.

## Detecting it in an existing system

Compare per-stage last-execution timestamps against the chain's last-execution timestamp. A stage whose own last run is hours behind the chain's is being skipped. Then check whether that stage's query reads stored pending state; if it does, it was miswired from the start.
