---
id: gating-derived-documents-for-release
kind: methodology
title: Gating Derived Documents for Release
date: 2026-11-06
---

When a document is assembled from upstream records and then sent outside the team, the usual automated gates check the wrong class of error. Numeric traceability, schema, section order and tone checks all pass on a document that contains confidently worded false statements, leaks restricted material, or misattributes who did the work. Treat outbound documents as a distinct artifact class with its own gates.

How to do it:

1. Add an assertion-level check alongside numeric checks. Enumerate every sentence that makes a factual claim, including claims with no number in them (absolutes, negations, scope statements, capability claims such as "only ever did X" or "never touched Y"). For each, require a pointer to a specific supporting record, or mark it as unsupported. A document is not verified until the unsupported list is empty. Numeric-traceability gates are necessary but structurally blind to unquantified claims, so never let a clean numeric run stand in for truth.

2. Watch for claim inflation at compression boundaries. Qualifiers like "in full", "all", "every", "per device", "always" are usually introduced by a summarizing step rather than present in the source. Flag these words and require each to be re-derived from the primary record.

3. Derive from primary records, not from an intermediate summary. Pipelines that read a prior digest inherit every error in it and add their own. Point the generation step at the underlying findings and raw evidence. When you discover an error in a derived document, check the intermediate it came from — the same defect is almost certainly still sitting there, and it may already have shipped elsewhere.

4. Carry handling metadata as a required field through every transformation. If upstream records store provenance (who supplied an item) but not its sensitivity or release status, restricted material becomes indistinguishable from public material at assembly time. Add an explicit classification and release-status field, default it to the most restrictive value, and make the outbound gate fail closed on any item that is unlabeled or not cleared for the intended audience.

5. Make attribution part of the document's required shape, not prose left to the author. Record for each finding which party produced it, then check the finished document against that record so contribution is not silently re-framed. Where an external party has stated how they want to be represented, capture that as an explicit requirement in the artifact's definition of done rather than leaving it in call notes.

6. Re-run the full gate set on the final outbound artifact rather than only on its inputs, and require a human reviewer who did not write it to sign off on the assertion list, the handling labels and the attribution map.

General principle: gates that only check shape, syntax and numbers produce a false sense of verification. For any artifact that leaves the organization, add gates for the three things shape checks cannot see — whether each claim is true, whether each input is cleared for the audience, and whether credit matches reality.
