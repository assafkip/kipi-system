---
id: gate-a-catch-up-job-to-the-slot-it-rescues
kind: pattern
title: A catch-up job must be gated to the slot it rescues, not fire around the clock
date: 2026-07-14
---

A fixed-time scheduled job (one that runs at a specific hour) silently does nothing if the host is asleep or off at that exact minute, and most schedulers do not retry a missed clock-time fire on wake. The reflex is to add a catch-up twin that re-runs the same job on wake and every N minutes, so a missed slot self-heals. That reflex is half a design. A catch-up with no gate on WHEN it may produce the deliverable will fire right after midnight, build the day's output hours before its intended slot, and the primary fixed-time job then finds the work already done and never runs. The safety net silently becomes the schedule, and the deliverable ships at the wrong time every day.

How to build it safely:

1. Gate the catch-up to the slot it rescues. It may only produce the deliverable at or after the intended time, and only when that slot was actually missed. Before the intended hour it must no-op. A catch-up that runs eagerly at any hour is not a catch-up, it is a second, worse schedule that always wins the race.

2. Prefer detection over eager reproduction for the miss you actually fear. The failure a catch-up guards against (host down at the slot) is better caught by an OFF-host alarm that reads the public artifact and pings when a period passes with no delivery. An on-host catch-up cannot fire when the host is off, which is the exact case; an off-host watcher can. Make the alarm the primary fix and the on-host catch-up, if you keep one, the gated secondary.

3. Timing is a separate invariant from idempotency; assert both. A done-marker written only after a confirmed result stops double-delivery, but it does not stop the catch-up from winning the race to produce at the wrong time. Idempotency answers "did it ship twice"; the gate answers "did it ship when it should have."

The durable rule: a catch-up for a fixed-time job must run only at or after the intended slot and only on a real miss; an ungated every-N-minutes twin becomes the de-facto schedule and produces the deliverable at the wrong time. Detect the miss off-host; reproduce it on-host only inside the window it belongs to.
