---
id: match-a-rival-s-economics-by-killing-waste-not-changing-your
kind: pattern
title: Match a rival's economics by killing waste, not changing your model
date: 2026-07-06
---

When a competing system is cheaper or faster, split the gap into two parts before you act: structural cost you can only touch by changing your whole model, and waste you can remove while keeping everything essential intact. Most of the gap is usually waste. In session-based or agent-based systems the recurring waste is: cold-starting an expensive resource on every operation, letting a watchdog kill and restart that resource mid-run, and spawning more workers than the work needs.

Close it this way:

1. Hold ONE warm, long-lived instance of the expensive resource per session and reuse it across turns, instead of booting it per operation. First access pays the cold cost; every later access reuses the warm instance.
2. Make concurrent first-access share the single warm instance rather than each booting its own. Pair reuse with an idle reaper and a hard cap on spawned workers so the warm pool cannot leak or grow unbounded.
3. Remove self-inflicted restarts (mid-run kills, aggressive watchdogs) that discard a warm resource you already paid to start.
4. Keep your differentiating layer and your billing/interface model unchanged. You are buying parity on the wasteful axis, not doing a rewrite. Reframe the goal explicitly as 'kill the waste,' not 'switch the cost model' — it keeps scope honest.

Prove it per mechanism, never as one aggregate claim. Give each increment its own measurement: boot count stays at one across N turns; cold-vs-warm latency on first tool use; worker-spawn count down by a stated margin; no leaked or zombie instances after the reaper runs; the differentiating features still serve unchanged. 'It should be faster now' is an assertion. A measured before/after on each mechanism is the evidence.
