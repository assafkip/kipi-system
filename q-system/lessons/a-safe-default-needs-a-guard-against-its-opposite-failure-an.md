---
id: a-safe-default-needs-a-guard-against-its-opposite-failure-an
kind: pattern
title: A safe default needs a guard against its opposite failure, and the tier that gates correctness must be visible
date: 2026-07-06
---

When you make one outcome the silent default to prevent a costly mistake (a privacy-preserving mode, a fail-closed setting, a conservative fallback), you have not removed risk — you have moved it to the opposite failure. Defaulting to 'reveal nothing' prevents over-disclosure but silently produces under-delivery. Defaulting to 'block' prevents a bad write but silently drops legitimate ones. When the two failure modes carry asymmetric cost depending on WHO the recipient is, a one-sided default is a latent defect, not a safe choice.

How to build it safely:

1. For every safe default you add, name the opposite failure it now enables and ask whether a guard exists on THAT side. A default that only protects against direction A while nothing asserts against direction B is half a design. Add the missing assertion: at the point where the output leaves the system, require the operation to confirm the value that governs correctness matches what the recipient is entitled to — do not let it inherit the safe default by silence.

2. Recognize when the cost of the two failures is asymmetric and recipient-dependent. The same default that is correct for an external or untrusted recipient can be wrong for the party who actually owns the data or paid for the real result. If the default risk lands on the wrong party, either flip the default for that recipient class or force an explicit choice at the boundary — never let one global default serve two populations with opposite needs.

3. Surface any computed value that gates correctness. A field that decides whether the output is real, complete, redacted, or a stand-in, but is computed internally and never shown, cannot be checked by a human on either end. Print it to the operator at the moment of handoff, and label it loudly inside the artifact itself so the recipient can tell at a glance which tier they received. An invisible gate is an unverifiable gate.

4. Prefer a hard gate over a hopeful default at any delivery boundary. Make the step that sends the artifact choose the tier explicitly and fail if it was not chosen, rather than letting an unset value fall through to whatever the safe default happens to be. 'It defaults to the safe thing' is exactly how the wrong thing ships silently.

The durable rule: a safe default that guards only one direction of an asymmetric, recipient-dependent failure is a silent trap; pair it with an assertion on the opposite side, force an explicit tier choice at the output boundary, and make the correctness-gating value visible to both the sender and the receiver.
