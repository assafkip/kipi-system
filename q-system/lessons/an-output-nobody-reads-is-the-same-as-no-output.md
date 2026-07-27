---
id: an-output-nobody-reads-is-the-same-as-no-output
kind: pattern
title: An output nobody reads is the same as no output
date: 2026-07-27
---

Scheduled or chained work can produce nothing while every step looks healthy. There are two distinct shapes: the job died before producing, or it produced into a place nothing consumes. Handle them separately.

## Name the output the consumer actually reads
- Before choosing an output name or location, enumerate every consumer of that location. Grep for readers, not writers.
- If the consumer takes one exact path (no glob, no directory scan, no manifest), any other name is an orphan. Either write that exact path, or change the consumer to enumerate what is there.
- The highest-risk case is a variant of an existing artifact: a suffix, a topic tag, a `-v2`. It sits next to the real one, looks like it belongs, and is invisible to a single-path reader.
- Treat "one exact filename" as an implicit contract. Write it down next to the producer, or replace it with a discoverable convention.

## Make production and enqueue one step
- Delivery alarms watch queues, counters, and state records, not directories. An artifact that never entered a tracked queue can never trigger a zero-delivery alarm, no matter how good the alarm is.
- If a producer can create an artifact without registering it, that path will eventually be taken. Collapse create-and-register into a single operation so the untracked state is unreachable.
- Test it: remove the downstream trigger and confirm something turns red within one cycle. If nothing does, the artifact is unmonitored and its absence is undetectable.

## Prove the scheduled environment instead of assuming it
- Service managers, schedulers, and cron-like runners start with a minimal environment. Interactive shell profiles do not load, and tool directories under a user's home are usually absent from the search path.
- Any external tool invoked by bare name is a bet on that search path. Resolve it to an absolute path, or set the search path explicitly at the top of the runner.
- Verify from a stripped environment, not your own terminal: run the resolution check with an empty environment and only the minimal search path the scheduler actually provides. Your shell will pass a check the scheduler fails.
- Fail loudly and early. A runner whose tool is missing should exit non-zero naming the missing tool, not abort mid-way leaving no output and no error anyone reads.

## Sweep the class, not the instance
- When the same failure class recurs (a tool off the search path, a missing environment variable, a hardcoded consumer path), the reason is usually that the previous fix landed in one file while sibling runners kept the old shape.
- After fixing one, grep for every remaining call site of that shape and fix them in the same change. Then add a check that fails when a new bare invocation or new bespoke output name appears, so the class stays closed instead of being re-discovered later.
