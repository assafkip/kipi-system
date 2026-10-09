---
id: make-empty-results-distinguish-nothing-found-from-everything
kind: pattern
title: Make empty results distinguish 'nothing found' from 'everything rejected'
date: 2026-10-05
---

Pattern: when a pipeline generates candidates, filters them, and reports the survivors, a zero-survivor report must say why it is zero.

Three failure layers tend to stack.

1. The proof vocabulary cannot express the most common finding. If candidates must carry machine-checkable evidence, check what kinds of claims the vocabulary can support. A vocabulary built around counting things that are present has no way to prove that something is absent: a check that never ran, a field never populated, a trace that does not exist. Handle only the degenerate absence (the whole result set is empty) and the common case, a populated set with one missing field, has no valid proof. The producer then either picks a proof that fails verification or drops the claim. Fix: list the claim shapes the domain actually produces, and make sure each has a verifiable derivation, absence included.

2. The report collapses two states into one string. A line such as 'no results' renders the same whether the generator found nothing or found several items that the verifier rejected. The audit data that tells them apart exists but the renderer never reads it. Fix: the consumer reads the audit record and prints counts at each stage (emitted, verified, rejected, kept), with the top rejection reasons. An empty result must prove it is empty, not broken, at the point where a person reads it.

3. Nothing watches the keep rate. A stage that emits N and keeps 0 records those numbers, and no threshold, alert or test reads them. Fix: set an expected keep-rate floor, log or alert when a run falls under it, and add a test that feeds in all-rejected input and asserts the report is visibly different from the no-input report.

General check: for every filter stage, ask what the output looks like when it drops everything, and whether a reader could tell that from a stage that never had input. If the answer is no, the system does correct work, discards it, and reports a shape that looks normal.
