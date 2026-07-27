---
id: prove-a-negative-with-a-live-probe
kind: methodology
title: Prove a negative with a live probe
date: 2026-07-27
---

A claim that something is broken, missing, empty, or unreachable is a measurement, not an inference. The positive side of this is well known (do not claim delivery because the job exited zero). The negative side is the same bug inverted: do not claim failure because an alarm, a status field, a dashboard tile, a log line, or a code read said so. Those are proxies. The subject is the thing itself.

How to apply:

1. Define the probe before writing the claim. The smallest call that touches the real subject and returns distinguishable results for works / broken / not-found. If you cannot name the probe, you do not yet have a finding, you have a suspicion.

2. Run it, then attach the receipt. The exact invocation, the raw result, and the time it ran, sitting next to the claim. Reading the implementation and reasoning that it must fail is not a probe. Neither is quoting a monitor.

3. Make the durable capture surface refuse unproven negatives. Wherever failures get written down for later (finding ledgers, defect queues, postmortems, backlog notes), the writer requires a probe field and rejects entries without one. A written convention will not hold, because an unprobed finding that cites real identifiers looks identical to a probed one at capture time. The check belongs in the code that accepts the record.

4. Never let a prior finding stand in as the probe. An earlier report is someone else's claim, not current evidence. Re-run against current state. This matters most when the original condition was transient or intermittent, since that is exactly the case where a stale negative reads as a standing one and gets copied forward.

5. Look for a known-good counterexample before concluding no working path exists. If any recent success on the same path is on record, the honest conclusion is intermittent, not broken, and the two demand different fixes.

6. Treat a negative as true only as of its probe time. If the record outlives the subject's rate of change, mark it stale and re-probe before anyone acts on it.

Failure signature to watch for: a confident "X is broken" or "X does not exist" whose entire support chain is another document, an old alert, or a code read, with no moment where anything actually ran.
