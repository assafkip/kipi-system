---
id: keep-source-derived-and-model-derived-fields-separate-in-gat
kind: pattern
title: Keep Source-Derived and Model-Derived Fields Separate in Gates
date: 2026-10-12
---

When a decision gate asks a question about the source material (for example, 'did the source mention X?'), it must read only fields that are guaranteed to come from the source. If the gate reads a record that mixes quoted source text with model-written analysis, the model's own output can flip the gate, and the gate becomes correlated with how good the analysis is rather than with what the source said.

How to apply:

1. Tag provenance on every evidence field. Give each field or row an explicit origin marker (such as 'source_quote' versus 'model_authored') or split them into separate structures. Do not rely on readers knowing which fields are which.

2. Make gates consume only the provenance they claim to test. A gate about the source should accept only source-quoted fields, ideally enforced by type or schema so that passing a mixed record fails loudly.

3. Look for self-triggering loops. If the model is instructed to address a particular audience or entity in its output, good output will naturally mention that entity. Any check keyed on that mention will fire from the model's own text. Ask: does the safe outcome only occur when the model omits something it was told to include? If so, the design is fragile.

4. Write tests that match the stated intent, not the current behavior. Include a negative case where the entity appears only in model-authored text and the source is silent, and assert the gate returns false. Where a code comment states the rule, derive the test from that comment, and treat any disagreement between comment and test as a defect to resolve.

5. Audit existing tests for fixtures that encode the bug as expected behavior. A test that has passed for a long time may have been confirming the defect on every run. Use placeholder or minimal values in fixtures sparingly, since they can hide which field actually drove the result.

6. Treat repeated incidents as evidence of a mechanism. When several separate failures each look like a different phrasing accident, check whether they share a structural cause, such as a gate reading a field the model controls, before patching individual cases or adding phrase exclusions.

Result: provenance becomes part of the data contract instead of tribal knowledge, gates about the source cannot be influenced by generated text, and tests protect the intended behavior.
