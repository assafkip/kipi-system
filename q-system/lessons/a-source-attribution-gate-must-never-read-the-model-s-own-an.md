---
id: a-source-attribution-gate-must-never-read-the-model-s-own-an
kind: pattern
title: A source-attribution gate must never read the model's own analysis
date: 2026-09-14
---

## The failure shape

A gate is meant to answer a question about the SOURCE: did the input material itself say X? It gets implemented against a record that mixes two kinds of fields. Some are quoted from the source. Others are written by the model: summaries, pattern labels, recommendations. Nothing on the record says which field is which. No provenance marker, no split between quoted text and written analysis, no schema that would make the mix-up visible. The rule that certain fields are the source exists only in the head of whoever wrote the gate.

The gate scans the whole record, so the model's analysis can trip it.

## Why it is worse than an occasional false positive

Look at what the analysis step is asked to produce. If the prompt asks the model to write recommendations aimed at a party, good analysis names that party. The gate then fires on exactly the output you want. Its safe branch, "the source did not say X", is only reachable when the analyst leaves something out. A safe state that depends on an omission is not a safe state.

You can tell this is the mechanism, and not an unlucky phrasing, by reading the past trips. Real source attributions read like a claim about the source. If every trip instead reads like forward-looking advice ("if this shows up in your system, escalate", "you cannot directly do Y"), the gate is reacting to the analysis.

## How the test suite hides it

The usual fixture for this defect puts the trigger term in a model-authored field, puts a meaningless placeholder in the quoted-source field, and asserts the gate says YES. A comment nearby states the real contract ("only when the source literally says it"). The comment and the assertion disagree, and only the assertion runs. From then on, every regression run confirms the bug as intended behavior.

## How to build it so this cannot hide

- **Give every field a provenance type at ingestion.** Mark each one source-quoted or model-authored, in the schema, not in a convention. A gate about the source takes only the source-quoted fields as input. Ideally it cannot see the others at all.
- **Keep the source text and the analysis in separate structures.** If both live in one untyped dict, sooner or later something will read the wrong one.
- **Write the negative fixture first.** Put the trigger term only in model-authored fields, put neutral text in the source field, and assert NO. Then the mirror case: trigger in the source field, empty analysis, assert YES. The first fixture is the one that catches this class of defect.
- **Check the gate against realistic good output.** Run it on analysis that does exactly what the prompt asks. If the gate fires, its safe branch depends on the model under-performing.
- **Read fixtures against the comment above them.** When a test's inputs contradict its own stated contract, the test is the defect, not the documentation.
- **Audit past trips by their shape.** Sort them into "claim about the source" and "advice written by the analyst". Any trip in the second group is proof the gate reads the wrong layer.

## The general rule

A check about where something came from has to read only material that came from there. If the model that writes the analysis can also write the gate's trigger, the gate is measuring how the model writes.
