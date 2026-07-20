---
id: monitor-the-capability-you-need-not-a-proxy-for-liveness
kind: pattern
title: Monitor the capability you need, not a proxy for liveness
date: 2026-07-20
---

A recurring job can keep waking on schedule and still be incapable of doing the one thing it exists to do. When that happens, three latent gaps usually turn a transient hiccup into a silent, prolonged outage. Design against all three.

1) Monitor the outcome, not the heartbeat. A liveness stamp that fires before the real work proves only that the process woke up. If the health monitor reads that stamp, it will report green through every failed cycle. Instrument the actual capability: stamp success AFTER the load-bearing step, or emit a separate signal the monitor can distinguish from mere wakefulness. Ask of every monitor: can this stay green while the job produces nothing? If yes, it is watching the wrong signal.

2) Treat a silently expiring grant as a single point of failure. Any permission, token, or session that can lapse between runs on an external event (a reload, a refresh, an auto-update) and requires a human to re-establish will eventually lapse unattended. Either make re-acquisition automatic and part of the run, or detect the lapse and alert loudly on the first failed cycle rather than aborting quietly.

3) A mandated single driver needs a detectable failure, since it has no fallback. When policy or safety forbids redundancy, the sanctioned path becomes load-bearing with nothing behind it. Compensate on the detection side: when the one path cannot proceed, that condition must surface immediately and visibly, not degrade into a clean-looking no-op.

General rule: distinguish 'the job ran' from 'the job succeeded,' and wire monitoring, permissions, and alerting to the second. A cycle that produces nothing must be as loud as a crash.
