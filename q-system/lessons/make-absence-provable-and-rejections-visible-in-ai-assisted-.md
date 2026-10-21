---
id: make-absence-provable-and-rejections-visible-in-ai-assisted-
kind: pattern
title: Make absence provable and rejections visible in AI-assisted pipelines
date: 2026-10-19
---

When a pipeline has an AI stage that proposes findings and a verifier that accepts or rejects them, three failures tend to compound into a report that looks clean while the system is actually broken.

1. Give the proof vocabulary a way to express absence. If the verifier only supports claims of the form 'N things are present', the most valuable observations (a check that never ran, a field never populated, a step with no trace) cannot be proven. The author must then pick a proof type that will fail or stay silent. Audit the allowed proof types against the most common real finding shapes in your domain, and add an explicit absence derivation that handles partial emptiness (rows exist but a field is empty), not just the case where the whole result set is empty.

2. Distinguish 'nothing found' from 'everything rejected' at the point of consumption. If the final report renders the same placeholder for an empty list regardless of cause, a rejected-everything run looks identical to a genuinely clean run. Have the renderer read the audit record of what was emitted and rejected, and print a different message, with counts and reasons, when candidates existed but none survived. Rule: an empty result must prove it is empty, not broken.

3. Measure and alarm on the keep rate. Record emitted versus kept per run, then act on it: set a threshold, raise a visible warning or non-zero status when the rate is anomalously low (for example zero kept from several emitted), and add a test asserting that a total-rejection run is surfaced differently from a clean run. A metric nobody reads is not a control.

General heuristic: whenever a system does correct work, discards it, and then reports a shape that reads as normal, treat it as a defect class. Check for it at every filter stage, not just one.
