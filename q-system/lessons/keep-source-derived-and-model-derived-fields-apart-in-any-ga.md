---
id: keep-source-derived-and-model-derived-fields-apart-in-any-ga
kind: pattern
title: Keep source-derived and model-derived fields apart in any gate that asks what the source said
date: 2026-10-05
---

A gate that answers 'did the source say X' breaks when it reads a record that mixes source-derived fields with model-derived ones and carries no marking of which is which.

The failure mechanism:
- The gate checks a combined record for a term. The record holds quoted source text next to text the model wrote while analyzing it.
- The analysis step is also asked to produce recommendations that address the party in question. Good analysis names that party.
- So the gate's negative branch is reachable only when the analyst forgets to mention the party. The safe state depends on an omission, and the better the analysis, the more often the gate flips.
- Early trips look like phrasing accidents. They are not. Each one was a forward-looking recommendation, not a claim about the source, which shows the mechanism and not a one-off.

The test that should have caught it encoded the defect as intended behavior. It put the term in a model-authored field, used a placeholder for the source excerpt, and asserted a positive result. A comment beside it stated the opposite rule, and the test is what ran. Every regression run confirmed the bug.

How to prevent it:
- Tag every field on an evidence record with its provenance: quoted from source, or written by the model. Make the tag part of the schema so a reader cannot miss it.
- Run any 'what did the source say' gate only over source-tagged fields. Never over a concatenation of record fields.
- Write the negative fixture first. Put the term in model-authored text only, leave the source text clean, and assert the gate returns negative.
- When a test and its explanatory comment disagree, treat that as a defect report, not noise. Read the assertion against the stated intent before trusting a green run.
- Check every gate for a dependency on the model's own output. If a model writes the text a gate reads, the gate measures the model's behavior, not the source.
