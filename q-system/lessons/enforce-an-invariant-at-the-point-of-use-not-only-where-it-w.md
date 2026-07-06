---
id: enforce-an-invariant-at-the-point-of-use-not-only-where-it-w
kind: pattern
title: Enforce an invariant at the point of use, not only where it was produced
date: 2026-07-06
---

## The failure mode

A consumer reads a value and relies on a property of it — freshness, sortedness, non-emptiness, a range bound, a completed prior step. That property holds only because some upstream stage enforces it (a filter, a gate, an assertion at the producer). The consumer never checks the property itself; it trusts that whatever it reads already satisfies it. The trust is never written down, because on the original wiring it was always true.

Then someone re-points the consumer at a different producer, or enables the consumer on a path where the upstream gate does not run, or the producer's own contract shifts. The invariant silently stops holding. Nothing fails, because nothing on the consuming side was ever checking. The bad value flows straight through to the output.

Three ingredients combine, and all three must be present:

1. **An implicit contract.** The consumer assumes a property it never states or tests. It held by accident of wiring, so it was never made explicit.
2. **A change that reuses the input without re-validating it.** A behavior change couples the consumer to an input whose invariant has changed, without asking whether the new input still meets the need.
3. **Data that cannot be checked downstream.** The value carries no field that would let any consumer verify the property on its own. The only enforcement lived upstream, so any reader outside that gate is flying blind.

## Why it's structural, not a one-off bug

Patching the specific broken output fixes one instance. The shape that produced it remains: every other consumer that trusts an upstream-only invariant is one re-wiring away from the same failure. And you cannot even add a downstream guard, because the data was stripped of the field the guard would need. The defect lives in the handoff shape, so that is where a durable fix has to go.

## How to prevent it

- **Write the invariant into the consumer's contract.** If a step needs its input to be fresh / sorted / non-empty / complete, state that as an acceptance condition of the step, not as a fact about how the input happens to be built today.
- **Carry the field that makes the invariant checkable.** If the property is 'recent enough,' the value must carry a timestamp. If it's 'this stage ran,' carry a completion marker. An aggregation or curation step that drops the verifying field makes the invariant unenforceable for every downstream reader — keep it.
- **Assert at the point of use, not only at the gate that produces it.** Upstream enforcement protects only the paths that flow through that gate. A consumer that can be reached by any other path re-checks the invariant itself, right before it acts on the value.
- **When a change re-points a consumer at a new input, re-validate the invariant explicitly.** Removing a guard or reusing an existing input is a contract change. Before shipping it, confirm the new input satisfies every property the consumer silently depended on.
- **Treat 'it was always true on the original wiring' as a warning, not a guarantee.** An invariant that has only ever held by construction is exactly the one that breaks unnoticed when the construction changes.

## The one line

A property a consumer depends on is only as durable as the check that lives where the consumer reads — an invariant enforced only at an upstream gate, on data that carries no way to verify it, breaks silently the first time anything reads around that gate.
