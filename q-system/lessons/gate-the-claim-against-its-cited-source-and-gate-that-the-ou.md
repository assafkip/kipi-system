---
id: gate-the-claim-against-its-cited-source-and-gate-that-the-ou
kind: methodology
title: Gate the claim against its cited source, and gate that the output answers the question
date: 2026-07-06
---

When a generated artifact (a report, a finding, a summary) cites specific records to justify a specific claim, and separately is supposed to respond to a specific question, two implicit contracts hide in that structure. Both routinely go unverified, because the checks you already have validate the wrong layer.

The failure shape:

1. A field in your source data is read for AGGREGATE stats but never re-read for the SPECIFIC records a claim names. Your validators check numeric totals, evidence presence, formatting — the machinery — while the per-item assertion ("these records had outcome X") is free to contradict the very records it cites. A generator can state the opposite of what the data says and pass every gate.

2. "Answer the question" is enforced at the INPUT (you rank or prompt by the asked concern) but never at the OUTPUT. Better input framing does not force the surfaced result to actually resolve the original question. The artifact can lead with an incidental, high-signal-but-off-topic finding and still look complete.

3. A dimension that is always strong or attention-grabbing gets promoted to the headline regardless of whether it matches the TYPE of thing that was asked. High signal is not the same as relevant signal.

How to close all three:

- For every claim that names specific records, add a gate that re-reads THOSE records' relevant field and asserts the claim's field-level assertion matches. Do not assume an aggregate check covers it — aggregates and per-item narratives read the same field for different purposes; one being validated says nothing about the other.
- Encode the implicit contract ("the stated outcome matches the cited records") as an explicit, testable assertion. If it was never written down as a check, assume a generator will violate it.
- Add an OUTPUT gate: the artifact's lead answer must map to the TYPE of the original question. Check that the thing surfaced first is the same class as the thing asked, not merely something true and loud.
- Treat "this dimension is always the most impressive" as a smell, not a default headline. Route the headline by the question's type, in code, not by which signal scored highest.

General rule: a suite of gates that pass is evidence only about what those gates measure. Before trusting a generated artifact, name each implicit contract it relies on — claim-matches-cited-source, output-answers-input, headline-matches-question-type — and confirm each has a check that reads the exact thing the claim is about. An unencoded contract is an unmet one.
