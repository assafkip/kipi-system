---
id: gating-documents-built-for-external-release
kind: methodology
title: Gating Documents Built for External Release
date: 2026-11-04
---

When a document is assembled from internal work and then published outside the team, the usual automated checks tend to cover the shape of the document and the numbers in it, and nothing else. That leaves four gaps that recur. Close each one deliberately.

1) Add a positive claim check, not just negative and numeric ones.
Numeric traceability checks ("every figure resolves to a source row") and structural checks (headings, ordering, tense, placement) both pass on a sentence that contains no number and is simply untrue. Build an extraction step that enumerates every assertive sentence in the draft — especially absolute and categorical ones ("only", "never", "all", "everything", "in full", "per unit") — and requires each to be mapped to a specific supporting record or explicitly marked as unsupported. Treat an unmapped assertion as a blocking failure in the same way an unmapped figure is. Until this exists, a clean pipeline run must not be reported as "verified"; label it "shape and arithmetic verified" so no one over-reads the signal.

2) Carry handling metadata as a first-class field, not as tribal knowledge.
If source records capture who supplied an artifact but not its sensitivity, sharing restriction, or release status, then a restricted artifact and a publicly observable one are indistinguishable at assembly time. Add a required classification/handling field at the point material enters the system, default it to the most restrictive value when unknown, and propagate it through every derived artifact. The release gate then becomes mechanical: compute the maximum restriction across all contributing sources and refuse publication if it exceeds the intended audience. Reject records with an empty handling field rather than letting them default to permissive.

3) Derive external material from primary records, never from an internal summary.
Summaries compress, and compression is where scope inflation is introduced: a hedged, narrow finding becomes a broad, absolute one in the act of shortening it. Make the publication pipeline read from the underlying findings and evidence records, and forbid intermediate summary documents as inputs. Two follow-ons matter: when you discover an inflated claim in a published document, the same inflation almost certainly exists in the summary it was derived from and anywhere that summary was already distributed — so remediate upstream and notify downstream holders, not just the one artifact you noticed. And record provenance depth per claim, so a reviewer can see whether a sentence came from a record or from a paraphrase of a paraphrase.

4) Make attribution an explicit required element of the output template.
If credit and role description are not fields in the document specification, they will be written from whoever's perspective drafted the text, which systematically understates contributors outside the drafting team. Capture the agreed framing at the time it is agreed — who authors, who is named, in what role, with what verbs — store it as structured data alongside the work, and have the gate check the draft against it. Add a review step that asks, for each described contribution, whether the party who actually performed it would recognize the description. Inverted attribution is a correctness defect, not a courtesy issue, and should block release.

General rule: every gate you add encodes an assumption about what can go wrong. Periodically enumerate the failure classes your gates cannot see — untrue prose, missing metadata, lossy upstream inputs, unstated social commitments — and decide explicitly whether each is accepted or needs a new check. A passing suite should be described by what it actually proves, never as a blanket claim of correctness.
