---
id: a-shared-input-channel-needs-a-source-check-before-routing
kind: pattern
title: A shared input channel needs a source check before routing
date: 2026-08-31
---

## The failure shape

A handler sits at a trigger point that fires once per message on a channel, and treats every payload as if a human typed it. The channel actually carries several kinds of traffic: human input, machine-generated notifications from background work, system-injected reminders, and expansions of shortcuts or macros. All of them arrive with the same role or event type. None of them carries a field saying which is which.

The handler then classifies on content. Any machine-generated text that happens to contain the words the classifier keys on gets routed as if the human had asked for it. A status report reads as a request. An answer to a status question reads as feedback on the previous output.

## Why this is not bad luck

The instinct after such a misfire is to call it a rare string collision and patch the pattern. That reading is wrong, and the way to find out is to count.

Measure the real composition of the channel over its own history: how many messages carry a machine envelope, an injected block, or an expansion marker, versus how many are actual human input. When that fraction is large, the handler was misreading a steady stream of messages the whole time and the visible misfires are simply the subset where the content matched. The rate was always there. The pattern match only decided when it surfaced.

That number also changes the fix. A one-in-a-thousand collision might justify a tighter regex. A one-in-four misread does not; it says the contract is wrong.

## The underlying defect

The assumption "this input is human speech" is a contract that was never true and was never checked. The channel promised only "a message arrived," and the handler read something stronger into it. Content matching cannot repair that, because the machine traffic is made of the same words as the human traffic. No pattern separates the two reliably when both talk about the same subjects.

## How to build so this cannot hide

**1. Establish provenance before semantics.** The first branch in the handler answers "where did this come from," not "what does it mean." If provenance cannot be established, the correct move is to do nothing, not to guess.

**2. Prefer a structural marker over content.** Machine-injected traffic almost always carries a stable envelope, wrapper, prefix, or metadata field that human input does not. Detect that shape and exit early. It is the one signal that does not drift with wording.

**3. Default to inert.** For a handler that takes an action based on classifying its input, unknown provenance means skip. The cost of a missed classification on a genuine human message is one lost convenience. The cost of acting on machine chatter is a wrong action taken silently, repeatedly, with no one asking for it.

**4. Log the classification, not just the action.** Recording what the handler decided each message was makes the base rate visible without waiting for a misfire loud enough to notice. Silent misreads only become countable if something wrote them down.

**5. Write the check as an executable, not a comment.** A note saying "this only applies to human input" enforces nothing. The early exit on a machine envelope is the enforcement.

## The general rule

**When a channel carries more than one kind of traffic under one event type, a consumer that acts on content must first prove provenance.** If the payload has no field distinguishing sender kind, that absence is the defect to fix at the boundary, not a gap to paper over with better matching downstream. And when a handler misfires on such a channel, count the traffic before deciding it was rare. The rate usually says the misread was routine and the visible failure was just the first one that matched.
