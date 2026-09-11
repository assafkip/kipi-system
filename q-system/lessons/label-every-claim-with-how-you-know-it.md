---
id: label-every-claim-with-how-you-know-it
kind: methodology
title: Label every claim with how you know it
date: 2026-08-10
---

When you report a finding, each claim carries one of three tags before it leaves your hands: MEASURED (you ran something and read the result), READ (it is written in an artifact you opened, quoted verbatim), or INFERRED (you reasoned to it). Anything you cannot tag is not a claim yet; it is a guess wearing declarative grammar.

How to apply it:

1. Draft the finding, then pass over it once and tag every sentence that asserts a fact about the system, a count, an accuracy, a state, or a cause. Untagged sentences get rewritten or cut.

2. For each MEASURED claim, name the command or query and paste the actual output next to the number. If you cannot reproduce the number in the next thirty seconds, it is not MEASURED. A number you computed for one purpose does not become a measurement of a different property just because it is nearby. Counting how many items match a shape is not the same as measuring how many were extracted correctly; those are different quantities and they need different runs.

3. For each READ claim, quote the source line rather than paraphrasing its conclusion. Paraphrase is where a stated negative silently flips to a positive. When a source concludes something is NOT happening, the paraphrase that reaches the reader must still contain the negation.

4. For each INFERRED claim, write the word explicitly in the delivered text: "inferred", "likely", "not yet measured". Hedge language is not weakness here; it is the only signal the reader gets about which claims are load-bearing.

5. Reconcile any number that appears more than once. If a figure shows up in a summary, a spec, and a decision record, run one check that all three trace to the same computation. Divergent copies of the same number mean at least one is fabricated, and the one that reached the decision record is the expensive one.

6. Before a finding is used as the basis for a decision, an external message, or a build spec, re-derive its top claims from scratch rather than re-reading your own summary. Re-reading confirms what you wrote; re-deriving tests it.

The failure mode this prevents: inferences delivered in settled, observational grammar, where the only detector is the person receiving them. That does not scale, and it burns the credibility of the claims that are actually measured. When the same reviewer has had to correct you more than once on this, the fix is not more care; it is a pass that happens every time, on every claim, before delivery.
