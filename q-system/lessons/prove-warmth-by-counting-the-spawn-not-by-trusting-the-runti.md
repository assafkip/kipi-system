---
id: prove-warmth-by-counting-the-spawn-not-by-trusting-the-runti
kind: methodology
title: Prove warmth by counting the spawn, not by trusting the runtime
date: 2026-07-06
---

When a design depends on a runtime keeping some expensive resource warm across calls (a subprocess, connection, model, or cache surviving between invocations), do not read the runtime's docs and assume the behavior. Prove it with a spike that measures the one event that defines warmth.

The measurement discipline:

1. Instrument the actual boundary event. Warmth means the resource was created once and reused. So count creation events directly: wrap the real thing with a thin shim that logs one line per spawn/open, then exec's or delegates to the real thing. The shim is transparent to behavior and authoritative about count. A log of spawn events is ground truth; inference from timing or from the absence of errors is not.

2. Drive more than one call. Warmth is a claim about the second-and-later invocation. A single call can never distinguish 'kept warm' from 'freshly spawned each time' because both spawn exactly once. Run at least two real invocations that each should exercise the resource.

3. Bind the verdict to the count with three states, not two. Define pass/fail as a numeric threshold on the observed count before you look: count == 1 across N calls is the warm result; count > N-worth-of-respawns is the cold result. Critically, add a third state for count == 0 or any call that skipped the resource entirely — that is INCONCLUSIVE, not a pass. Zero observations means the path you meant to measure did not run; a two-valued verdict silently reports that as success.

4. On the cold result, the default is abort, not proceed-anyway. If the spike proves the resource is not kept warm, the build-on-the-assumption plan is dead. State the fallback explicitly (a different runtime, an externally managed long-lived service) rather than quietly continuing on the disproven premise.

The trap this closes: a spike that concludes GO from a green-looking run where the instrumented path never actually fired. Make the absence of the observation its own loud verdict, so a spike that measured nothing cannot masquerade as a spike that measured success.
