---
id: degrade-don-t-halt-when-a-fail-safe-gate-has-nothing-to-eval
kind: pattern
title: Degrade, don't halt, when a fail-safe gate has nothing to evaluate
date: 2026-10-19
---

Pattern: when a validation gate is enabled as a fail-safe because upstream classification produced nothing, do not let the gate's failure abort the whole run. That is the case where the strictest handling is least justified.

The failure mode: a pipeline has a per-item gate that normally degrades gracefully (marks the affected item as untestable and continues). A separate branch handles the case where the gate ran only as a default because nothing was classified. That branch reasons, "there is no item to degrade, so halt everything." The result is an inversion: the input with the least claim on the missing evidence gets the harshest outcome, and the user receives no output at all.

How to apply:
1. Audit every halt condition and ask: is the thing being demanded actually relevant to what the user asked for? If nothing was asserted that needs the evidence, a missing input is a coverage gap, not a fatal error.
2. Treat "nothing to degrade" as a signal to ship the remaining analysis with an explicit coverage note, not as a reason to discard it.
3. Look for an existing graceful path (an explicit untestable or skipped marker carrying item, reason and detail) and make sure every branch can reach it. A degradation mechanism that sits just past a hard stop is effectively dead code.
4. Keep missing-input reasons precise. Distinguish "the input was never provided" from "it was provided but not read", because asserting the former when the latter is true presents a guess as knowledge.
5. When a gate is opt-in by default or fail-safe, suppress observations that depend on the untestable evidence so the output does not narrate conclusions it cannot support.
6. Add a regression test with an input that classifies to an empty set and lacks the optional evidence. Assert that a report is still produced, with the coverage note.

Smell to watch for: a comment that honestly explains a halt with an unexamined premise ("nothing to degrade, so stop"). Whole-run halts should be reserved for cases where continuing would yield wrong output, not merely less complete output.
