---
id: give-validation-gates-a-category-for-judgment-derived-values
kind: pattern
title: Give validation gates a category for judgment-derived values, and degrade to caveats instead of dropping findings
date: 2026-07-13
---

A validation gate built to block one class of fabricated output can silently destroy the system's entire value if its allowed categories only cover machine-computable cases.

The failure shape: a contract enumerates the ways a value may be derived (e.g., only values traceable to a deterministic query or computation). But the system's core output is produced by judgment: reading unstructured input, correlating signals, estimating. Judgment-derived values fit none of the enumerated categories, so the gate rejects every one of them. The gate is not broken; it is faithfully enforcing a contract that contradicts the product. Result: an empty report that looks like a clean pass.

Two checks when designing any provenance or anti-fabrication contract:

1. Enumerate derivation kinds against the product's actual output taxonomy, not against what code can verify. If the system legitimately produces estimated or interpreted values, the contract needs an explicit category for them (e.g., 'analyst estimate', 'model-derived, unverified') with its own handling rules. A closed enum that omits a legitimate derivation kind is a structural ban on that kind of output.

2. Choose the failure mode deliberately: rejection-to-empty versus surface-with-caveat. For a tool whose job is to surface findings for a human to evaluate, dropping an unverifiable value should drop only the value's certainty, not the whole observation. Emit the finding with an explicit unverified/estimate marker and let the human weigh it. Reserve hard rejection for cases where the value itself is the deliverable and a wrong one is worse than none.

Regression test for this class of bug: run the full pipeline on realistic input and assert the output is non-empty and contains at least one judgment-derived finding carrying its caveat marker. A gate change that zeroes the output should fail loudly, because 'empty' and 'compliant' are different states.
