---
id: prove-delivery-with-receipts-not-proxies
kind: pattern
title: Prove delivery with receipts, not proxies
date: 2026-07-27
---

A channel can exit 0, keep a fresh heartbeat, and still deliver nothing. Every green signal in that setup is a proxy for delivery, not delivery itself. The fix is to make a receipt the only thing that counts as live.

## The failure shape

- Something is declared working (a status note, a prior session, a passing run).
- The job runs, exits 0, updates a timestamp.
- Zero units are actually delivered.
- No monitor fires, because every monitor watches a proxy: process liveness, exit code, "a request was sent", a stored claim.
- A human discovers the outage by looking.

## Why proxies fail

A proxy sits upstream of the thing you care about. An exit code proves a code path finished, not that the far side accepted anything. A heartbeat proves the scheduler ran. A "sent" log proves a call left the process. None of them survive an empty input set, a silently dropped payload, a query that filters to zero, or a credential that authenticates but authorizes nothing.

## The pattern

1. **Define a receipt per channel.** An identifier returned by the receiving side that could not exist unless delivery happened: a remote-assigned id, a stored row with a foreign key, a count read back from the destination. A local log line is not a receipt.
2. **Keep a registry of every delivery channel.** One row each: name, owner, expected cadence, minimum expected volume per window, receipt shape.
3. **Run one reconciler over the registry on a schedule.** For each channel it compares receipts observed in the window against the declared minimum and alerts on zero or under-floor. The reconciler is the single alerting path; channels do not each invent their own.
4. **Add an arming gate.** A channel is not "live" until it has produced at least one real receipt. Until then its state is "armed, unproven", and claiming it live is a hard error. This closes the "it was reported working" hole at the source.
5. **Make zero distinguishable from broken.** A run that legitimately had nothing to deliver records an explicit empty-with-reason receipt. A run that delivered nothing for any other reason is a failure.

## Fix the class, not the instance

When the same shape appears on a third channel, stop patching instances. The tell that you have a class: different proximate causes, identical surface (green everywhere, zero output, human-discovered). The class fix is registry plus one reconciler plus a gate that new channels pass through, so new channels inherit the monitoring instead of re-earning it.

## Checks that prove it works

- Break one channel deliberately (revoke its credential, point it at a dead endpoint) and confirm the reconciler alerts within one window.
- Add a new channel without registering it and confirm the arming gate refuses to mark it live.
- Confirm at least one alert has fired from a real failure, not only from the injected test.
