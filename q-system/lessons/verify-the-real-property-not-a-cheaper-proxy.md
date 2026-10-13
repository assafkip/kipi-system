---
id: verify-the-real-property-not-a-cheaper-proxy
kind: methodology
title: Verify the real property, not a cheaper proxy
date: 2026-10-12
---

When a check, gate, or test is meant to guard a property, make sure what it executes actually observes that property rather than a nearby stand-in. Three failure modes recur, along with a fix for each.

1. Proxy binding. A name, comment, or heading states the claim (for example, 'this gate never rejects valid input'), but the code checks something cheaper: a hand-built sample, a file standing in for the behavior the file produces, or a helper invoked in isolation. Proxies are tempting because they are the nearest observable thing and cost one line, while the real property needs an end-to-end run. Fix: for each guard, write down the property in one sentence, then ask 'if the real path were unplugged, would this still pass?' If yes, rebind the check to the real artifact, or add a mutation check that deliberately breaks the real path and confirms the guard fails.

2. Fully synthetic fixtures. Suites rightly forbid live calls to non-deterministic or paid dependencies such as models and third-party APIs. The side effect is that every response in every test is hand-written, so nothing ever runs against output the real dependency produced. Fix: capture real responses once, store them as fixtures, and make the loader reject any fixture lacking a provenance record (source, capture date, how it was produced). Apply this to every external dependency, not only the ones that have already caused an incident. Add a periodic, budgeted, opt-in live run to detect drift between captured and current reality.

3. No floor for partial failure. When a step requires an answer from an unreliable dependency, define the minimum acceptable outcome explicitly. If some results are missing or degraded, fail loudly or fall back to a defined behavior instead of silently proceeding with fewer or empty inputs that still let the check pass. Assert on counts and non-emptiness of what was actually evaluated.

Review heuristic: for every gate, locate the line where the real artifact enters the check. If you cannot find it, the gate is decoration.
