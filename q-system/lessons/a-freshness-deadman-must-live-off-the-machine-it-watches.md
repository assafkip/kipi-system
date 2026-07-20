---
id: a-freshness-deadman-must-live-off-the-machine-it-watches
kind: pattern
title: A freshness deadman must live off the machine it watches
date: 2026-07-20
---

A job wired to a calendar-style scheduler (fire-at-06:00 style triggers) will silently skip its run whenever the host is unavailable at the scheduled instant — powered off, asleep, logged out. Most such schedulers do NOT queue a catch-up on next wake; the occurrence is simply lost. No line of the job executes, so no in-run guard (auth checks, input-floor checks, freshness assertions, on-failure alerts) can fire, because those all live inside a run that never happened.

The trap: any watcher that runs ON the same host is structurally blind to this failure mode. When the host is down, the watcher is down too. A monitor co-located with the thing it monitors cannot detect the host being off — the exact case where the job also fails to run.

How to build the guard:

1. Put the deadman on a SEPARATE, always-on host (or a hosted cron / uptime service). It must be able to run while the monitored host is dark.

2. Monitor the OUTCOME, not the process. Check the freshness of the delivered artifact (last-produced timestamp, output row, published file), not whether the job process is alive. Absence of a fresh deliverable is the signal. This catches both 'host was off' and 'ran but produced nothing' with one check.

3. Set an explicit staleness threshold (e.g. no new deliverable within one expected cycle + slack) and alert on breach through a channel that also does not depend on the monitored host.

4. Classify the failure correctly when it fires: 'host unavailable at schedule time' is an environmental cause, not a code defect. The code is unchanged; treat it as an availability problem (add catch-up-on-wake, move to an always-on runner, or accept-and-detect via this deadman).

Rule of thumb: every scheduled deliverable needs one independent observer that asks 'did the thing that should exist by now actually appear?' — running somewhere that stays up when the producer goes down.
