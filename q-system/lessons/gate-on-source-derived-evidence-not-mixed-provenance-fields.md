---
id: gate-on-source-derived-evidence-not-mixed-provenance-fields
kind: pattern
title: Gate on source-derived evidence, not mixed-provenance fields
date: 2026-10-19
---

When a decision gate must answer a question about what the source material said (for example, whether an input explicitly mentioned some entity), it must read only fields that are verbatim from the source. If it reads a record that mixes source-quoted fields with model-written analysis, the gate can be flipped by the model's own output, and the safe branch is reached only when the model omits a term.

How to apply:

1. Identify the question the gate answers and classify every field it reads as source-derived or model-derived. Treat any text the model authored (summaries, patterns, recommendations, rationales) as untrusted for source-fact questions.

2. Make provenance explicit in the data model. Tag each evidence item with its origin (quoted source vs. generated analysis), or store them in separate structures or types, so a reader cannot accidentally mix them. Do not rely on a convention that exists only in people's heads.

3. Check whether the prompt or task naturally induces the model to produce the trigger term. If good output would mention the term anyway (for example, when asked to write recommendations for a particular audience), any gate keyed on that term in model output is broken by design. Look for gates whose safe state depends on something being omitted.

4. Restrict the gate to the source-derived channel. Match against the quoted source text, ideally with the match location or excerpt recorded, so the decision can be audited.

5. Write tests that cover the negative case: the term appears in model-authored fields but not in the source, and the gate must return false. Also cover the positive case where the term appears in the source. Make sure fixtures do not use placeholder values that hide which field carries the signal.

6. Audit existing tests against the stated intent in comments and docs. When a test and its documented requirement disagree, the test is what runs and will keep confirming the defect. Treat a test that asserts the buggy behavior as a finding in its own right.

7. When the failure recurs in different phrasings, stop patching individual cases and fix the mechanism. Repeated near-misses that all share a cause, such as forward-looking recommendations that mention the entity, indicate a structural flaw rather than a one-off wording issue.

Rule of thumb: a gate about what the source said must only be able to see what the source said.
