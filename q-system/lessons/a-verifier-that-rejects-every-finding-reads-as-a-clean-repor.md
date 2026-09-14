---
id: a-verifier-that-rejects-every-finding-reads-as-a-clean-repor
kind: pattern
title: A verifier that rejects every finding reads as a clean report
date: 2026-09-14
---

When a system generates candidate findings and a verification stage keeps or rejects each one, three defects can combine. The result is a report that reads as 'nothing found' while every real finding was thrown away.

The three defects:

1. The proof vocabulary cannot express the claim the domain produces most often. Verifiers tend to be built around counting things that are present, like rows that matched or values over a threshold. In investigation, audit and monitoring work, the most valuable observations are usually absences: a check that never ran, a field that is never filled in, an expected step missing from a trace. Often the only absence-shaped proof covers just the degenerate case where the whole query came back empty. The common case, where rows exist but a field inside them is empty, then has no proof it can use. The generator either picks a proof type that will fail verification or drops the claim. Either way, the most valuable kind of finding never gets through.

2. 'All rejected' renders the same as 'none found'. When the kept list is empty, the report prints one fixed 'no findings' string. It never reads the audit record that knows how many findings were proposed and why each one was rejected.

3. Nothing reads the keep rate. Proposed and kept counts are recorded, but no threshold, alarm or test uses them. A verifier that rejects everything looks the same as one that works.

HOW:

1. Before building the verifier, list the claim shapes the domain actually produces. Take them from real past findings, not from what is easy to prove. For each shape, confirm a proof type exists that can express it. Absence claims need their own proof types, for example 'field blank across a populated set', 'expected event missing from a trace', or 'check configured but never executed'. Each one carries its denominator: the rows or sessions that were examined.

2. Test the vocabulary against a known-true past finding of each shape. If a true finding cannot pass verification, the verifier is incomplete, not strict.

3. Make the report read the audit record. Render three visibly different states: nothing proposed; findings proposed and all rejected, with counts and rejection reasons; findings kept. Only print the empty-findings string when the proposal count is zero.

4. Treat the keep rate as a health metric. Record proposed and kept counts per run. Alarm when kept is zero while proposed is not, or when the rate stays below a floor across several runs in a row. A breakdown of rejections by reason shows whether one claim shape is failing every time.

5. Add an end-to-end test that sends a known-true absence-shaped finding through the whole pipeline and asserts it appears in the final report. Then make the verifier reject everything on purpose and assert that the report shows the all-rejected state, not a clean one.

The general rule: an empty result from a filter can only be trusted if two things hold. The output tells 'nothing to filter' apart from 'filtered everything', and the filter is able to accept the kind of claim the domain cares about most.
