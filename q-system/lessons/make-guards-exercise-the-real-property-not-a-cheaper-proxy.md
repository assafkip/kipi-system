---
id: make-guards-exercise-the-real-property-not-a-cheaper-proxy
kind: methodology
title: Make guards exercise the real property, not a cheaper proxy
date: 2026-10-19
---

Problem: a gate, test, or labeled output claims to protect some property, but what actually executes checks a nearby, cheaper stand-in. The claim lives only in a docstring, a name, or a heading, while the check passes even when the guarded thing is disconnected or broken. Proxies arise naturally: the author checks whatever is closest at hand (a sibling function, an inline-built sample, a file standing in for the behavior it produces) because observing the real property needs an end-to-end run and the proxy costs one line.

How to apply:
1. For each guard, write the property in one sentence, then ask: if the thing it protects were unplugged, would this guard still pass? If yes, it is bound to a proxy. Fix or relabel it.
2. Feed gates real inputs of the kind they will see in production, not samples built inline by the author. If the check can only pass on synthetic data, it proves nothing about real data.
3. When a label (name, heading, docstring) promises something, make the executable assert that same thing, or rename the label to describe what is truly checked. Prose must not carry a property the code does not enforce.
4. Avoid pinning an artifact (a file, a hash) as a stand-in for the behavior it produces; test the behavior, or add a check that links the artifact to the behavior.
5. Test suites that correctly forbid live calls to non-deterministic or paid dependencies leave a blind spot: every dependency response in every test is hand-written, so nothing ever runs against real output. Close it with recorded fixtures captured from the real dependency, and make the loader refuse any fixture lacking a provenance record (source, capture time, how it was produced). Hand-typed shapes drift from reality; provenance-gated captures cannot.
6. Apply a proven mechanism everywhere it fits. If one integration already enforces provenance-checked fixtures, audit the other integrations for the same gap rather than leaving the fix local.
7. Partial failure needs a floor: where a real answer from a dependency is required, define the minimum acceptable outcome and fail loudly when it is not met, instead of letting a degraded or empty result pass as success.
