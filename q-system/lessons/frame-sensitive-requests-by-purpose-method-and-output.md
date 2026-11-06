---
id: frame-sensitive-requests-by-purpose-method-and-output
kind: pattern
title: Frame Sensitive Requests by Purpose, Method, and Output
date: 2026-11-03
---

When asking an assistant or a reviewer to work on material that looks risky in isolation, do not send a bare verb like "analyze this" or "build this." Bare verbs force the responder to guess intent, and the safe guess is refusal. Instead, state three things up front:

1. Purpose — why the work is being done and whose interest it serves (e.g. protecting a system you operate, verifying a claim, documenting an incident).
2. Method — what will actually be done, stated narrowly and verifiably. Prefer methods that are inspection-only over methods that execute, mutate, or deploy. Say so explicitly: read-only, offline, no execution, no network calls.
3. Output — the concrete artifact you want back, and keep it the minimum that serves the purpose. An artifact that is useful defensively but useless offensively is the strongest framing available.

HOW TO APPLY

- Write the three fields as one or two leading sentences, before the payload or target. Do not bury them after the request.
- Make the method claim falsifiable. "Static inspection, nothing is run" can be checked against what you then ask for; "I'll be careful" cannot.
- Choose the output so it answers the purpose and nothing more. Asking for detection signatures, a risk summary, or a list of affected components is narrower than asking for a full working reproduction.
- If you find yourself unable to state a legitimate purpose plainly, treat that as a signal about the request, not a prompt to reword it.

WHAT THIS DOES NOT DO

This is a technique for removing ambiguity, not a formula for unlocking refusals. Some work is out of bounds on its own terms — executing untrusted material in a live environment, producing something whose only use is to cause harm, or defeating safeguards. Adding a defensive-sounding preamble to those does not change what they are, and responders are right to decline regardless of framing. The pattern earns its value only when the underlying request was already legitimate and merely looked ambiguous.

WHY IT WORKS

Risk assessment of a request is driven mostly by intent and blast radius, both of which are invisible in a one-word verb. Supplying them converts a judgement call into a scoped, reviewable task. The same habit improves requests to human colleagues, change-approval boards, and security teams, and it doubles as a self-check: a request that cannot survive being written this way usually needs rethinking rather than rephrasing.
