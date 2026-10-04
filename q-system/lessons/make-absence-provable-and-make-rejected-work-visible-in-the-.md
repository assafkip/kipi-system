---
id: make-absence-provable-and-make-rejected-work-visible-in-the-
kind: pattern
title: Make absence provable, and make rejected work visible in the report
date: 2026-10-04
---

Three linked defects can combine so that every automated finding is discarded while the final report reads like a clean, normal result.

1. Give your evidence vocabulary a way to express absence. If findings must be backed by a fixed set of proof types, check that the set covers the most common real finding in your domain. Proof types built around counting things that exist leave no way to claim that a field is never populated, a check never ran, or a step left no trace. Covering only the degenerate case (the whole query returned nothing) is not enough. The common case is a populated result with one empty field. When no proof type fits, the producer either picks one that will fail verification or drops the claim.

2. Keep 'nothing found' and 'everything found was rejected' as separate report states. If the empty-result message is rendered from the ranked list alone, it reads the same whether the producer found nothing or found five things that all failed verification. The audit data holds the difference, so the report must read it. Empty has to be distinguishable from broken at the point where the result is consumed. Show the counts (emitted, kept, rejected) and the rejection reasons when the kept list is empty but the emitted list is not.

3. Measure and alarm on the keep rate. A pipeline that records 'emitted: N, kept: 0' and has nothing that reads it will fail silently. Add a threshold on kept/emitted, a signal someone actually watches when it trips, and a test that asserts the alarm fires on an all-rejected run.

Check for the shared shape: the system does correct work, throws it away at a gate, and reports an outcome indistinguishable from a healthy one. Any gate that can discard everything needs a visible, tested path for that case.
