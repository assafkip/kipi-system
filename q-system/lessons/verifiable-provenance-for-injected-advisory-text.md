---
id: verifiable-provenance-for-injected-advisory-text
kind: pattern
title: Verifiable Provenance for Injected Advisory Text
date: 2026-10-31
---

When a system injects generated or third-party text into an automated agent's input stream, treat that text as a distinct trust class and make the class verifiable by the receiver, not merely asserted in prose.

HOW:

1) Separate the channels. Reserve the channel that carries deterministic, first-party control messages (refusals, policy denials, exit diagnostics) exclusively for that purpose. Deliver advisory, model-authored, or externally sourced content on a different channel, field, or envelope. A receiver that cannot distinguish the two must assume the worse case — "untrusted" — which silently destroys the authority of your legitimate control messages and, worse, tends to surface as a security escalation from the receiver rather than as a quiet bug.

2) Make provenance checkable, not declarative. A banner saying "this is a proposal from another system, not a measurement" is a claim that any writer to the same channel can forge. Attach something the receiver can test: a per-run nonce issued by the component that owns the channel, a signature over the payload with a key only the emitter holds, a structured envelope with a monotonic sequence number, or a side lookup the receiver consults to confirm the message was actually produced. Design so that absence of the proof is a hard failure, not a warning.

3) Label at the boundary in a machine-readable field. Put the trust class in the envelope the receiver parses, not in free text inside the body. Then write the receiver's handling rules against that field: content classed as advisory may inform but never instruct — it cannot change plans, grant permissions, widen scope, or trigger execution.

4) Pin the negative case in tests. Tests asserting "the advisory arrives" and "it degrades gracefully when the producer is unavailable" do not cover the threat. Add a case that writes forged content onto the same channel and asserts rejection; add a case that strips or corrupts the proof and asserts rejection. If no test distinguishes a genuine message from an impostor, the boundary is documentation, not a control.

5) Match the context you analyze to the context you address. When one component computes an assessment from captured state and a different component consumes it, verify the captured state actually belongs to the consumer. Shared or inherited transcripts, logs, buffers, and fixed-size history tails routinely contain a parent's or coordinator's state rather than the child's. Symptoms: advice that diagnoses the wrong actor, recommendations referencing work the recipient never performed, or "you are blocked on X" where X belongs to someone else. Fixes: stamp every context capture with the identity of the actor it was collected for; have the consumer assert that identity matches itself and discard loudly on mismatch; and when the history source is a shared stream, filter to the consumer's own records before sending instead of taking an arbitrary tail.

6) Fail closed and visibly. If provenance or addressing cannot be verified, drop the content and emit a first-party message on the trusted channel explaining the drop. Silently forwarding unverifiable text is how an advisory feature becomes an injection vector.

7) Gate the design, not just the code. Before shipping any feature that injects text into an autonomous consumer's context, answer three questions in the design and encode each answer as a test: who else can write to this channel; what can the receiver verify without trusting the sender; and whose state was this computed from.
