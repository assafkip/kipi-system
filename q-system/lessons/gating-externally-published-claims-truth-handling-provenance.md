---
id: gating-externally-published-claims-truth-handling-provenance
kind: methodology
title: Gating externally published claims: truth, handling, provenance and credit
date: 2026-11-09
---

When a pipeline produces material for an outside audience (press briefs, public reports, disclosures), passing automated checks is easily mistaken for being correct. Treat four distinct failure surfaces separately.

1. Structural and numeric gates do not verify truth. Checks that confirm every number traces to a source row, or that headings, tense and placement match a template, say nothing about qualitative sentences that contain no numbers (for example, broad characterizations of method or scope). Add a claim-level review step. Break the draft into individual factual assertions, including unquantified ones, and require each to cite a specific finding or evidence item. If an assertion cannot be linked, it gets rewritten or removed. Report gate results narrowly ("numbers traced, structure valid") so that a green run is never read as "content verified."

2. Carry handling restrictions as data, end to end. Every evidence item should record not only who supplied it but also its sharing classification and release status (for example, a traffic-light-style marking, embargo, or permission to publish). Make the publication build fail closed when any referenced item is unclassified or restricted. Without this field, restricted material looks the same as public material once it is inside the pipeline.

3. Derive outward-facing material from primary findings, not from summaries. Each summarization step compresses, and compression is where qualifiers disappear and claims inflate ("partial" becomes "in full", "some" becomes "per unit"). Generate external text directly from the findings and evidence. If a summary was used and found wrong, also correct the summary and any copies already distributed to others.

4. Make attribution a required part of the output's shape. Include an explicit credit section that maps each key finding to whoever originated it, and check it against the agreed framing with partners before release. If credit is left implicit, a narrative can quietly invert who discovered what.

Checklist before release: every assertion is linked; every source is cleared for this audience; every claim was traced to primary findings; credit was mapped and confirmed with partners; and gate reports state exactly what they did and did not verify.
