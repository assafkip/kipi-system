---
id: preflight-the-contention-alarm-the-silent-no-op
kind: pattern
title: Preflight the contention, alarm the silent no-op
date: 2026-07-06
---

When a scheduled or background job depends on a resource that only one client can hold at a time (a device, a session, a profile lock, a single-writer file, an exclusive API slot), do two things the runtime will not do for you.

1) Move the exclusivity contract into your own preflight. A lock that lives inside the shared resource protects the resource, not your job — your job just fails when it loses the race. Before doing expensive work, actively check whether the resource is free and serialize against other holders (acquire a lease, test the lock, or coordinate through a shared claim). Assume a human or another process may own it at the exact moment you fire; design for contention, not for the clear-desk case.

2) Make a do-nothing outcome loud. A run that wakes, discovers it cannot proceed, and exits is indistinguishable from a run that never fired — unless the difference is surfaced somewhere watched. Writing the reason to a log that nothing monitors is the same as swallowing it. Emit an explicit signal on the no-op path (a heartbeat that records success vs. skipped-due-to-contention, an alert, a metric that a monitor reads) so 'ran and accomplished nothing' cannot masquerade as 'ran fine.'

The cheap, wrong version is to spend the full job budget just to learn the resource was busy, then bury that discovery. The right version checks availability first and treats a silent skip as a reportable event.
