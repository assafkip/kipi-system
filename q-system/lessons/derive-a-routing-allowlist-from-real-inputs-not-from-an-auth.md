---
id: derive-a-routing-allowlist-from-real-inputs-not-from-an-auth
kind: methodology
title: Derive a routing allowlist from real inputs, not from an author's imagination
date: 2026-07-06
---

When you replace a rigid rule that was over-blocking, watch for re-encoding the same rigidity one level lower. The classic recurrence: you tear out a hardcoded gate, then reintroduce a hand-authored enumeration (an allowlist of verbs, keywords, patterns) checked before a fallback default. That enumeration is a fresh cage. It encodes what you *guessed* the inputs would be, so any real input outside your guessed set silently falls through to the default lane and gets misrouted.

The altitude mistake is subtle: the first fix correctly inverts the wrong first principle, its gates go green, and everyone believes the class is closed. But the *mechanism* of the fix (an authored list) reproduces the original defect at a lower altitude. Green gates on the mechanism do not prove the mechanism is the right shape.

HOW to avoid it:

1. Before authoring any allowlist, get the actual distribution of real inputs the system receives (the ops-log, request history, transcript corpus). Derive the classifier's decision boundary from that observed data, not from a whiteboard list of what you expect.

2. Test the classifier against verbatim real inputs, not synthetic examples you wrote. Run the true classifier on the exact phrasings that will hit it in production. Two legitimate phrasings of the same intent routing to two different lanes is a signal the boundary is authored, not derived.

3. Make the default lane loud. A silent fallback that swallows anything unmatched is where authored-enumeration errors hide. Log or surface every input that lands on the default so the gap between your list and reality is visible, not absorbed.

4. When a recurrence keeps appearing under new surfaces, stop patching the symptom and audit the *shape* of your fixes. If each fix is another enumerated list, the pattern is your reflex to enumerate. Replace enumeration with derivation.

The test for a good fix is not 'does my list handle my examples' but 'is this boundary computed from the same distribution of inputs the live system will actually see.'
