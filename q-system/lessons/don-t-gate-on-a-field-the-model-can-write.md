---
id: don-t-gate-on-a-field-the-model-can-write
kind: pattern
title: Don't gate on a field the model can write
date: 2026-10-04
---

A gate meant to answer a question about the source (did the input name us, contain X, cite Y) fails silently when it reads a record that mixes source-derived fields with model-authored fields and nothing marks which is which.

The mechanism: the downstream task asks the model to write analysis that addresses the very entity the gate looks for. Good output therefore mentions that entity. The gate's negative branch is reachable only when the model omits something it was asked to include. The safe state depends on an omission, so the gate trips on ordinary, correct behavior and the failure recurs under different phrasings. Repeated trips on forward-looking recommendations, not on claims about the source, are the signature of a mechanism defect rather than a one-off wording accident.

The defect stayed hidden because the contract existed only in a reader's head. There was no provenance tag on each evidence row, no separation between quoted source text and written analysis, and no schema that made the mix visible.

A test then locked the bug in. Its fixture put the trigger string in a model-authored field, with a placeholder in the source field, and asserted the gate fires. A comment two lines above stated the opposite intent. The test and the comment disagreed, and the test is what runs, so every regression run re-confirmed the defect as correct behavior.

How to apply:
- For every gate, list the fields it reads and label each as source-derived or model-derived. If you cannot label them, the contract is implicit.
- Add a provenance field to each record, or split quoted source from generated analysis into separate structures. Gate only on the source side.
- Build the negative case into the suite: a fixture where the model-authored text contains the trigger and the source does not must return false. Run it and watch it fail before the fix.
- When a test and its explanatory comment disagree, treat that as a bug report and resolve it before trusting either.
- Ask of any gate whether its safe branch depends on the model leaving something out. If yes, the gate is reading the wrong signal.
