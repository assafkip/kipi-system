---
id: a-gate-is-only-real-if-production-writes-what-it-reads
kind: pattern
title: A gate is only real if production writes what it reads
date: 2026-07-20
---

When a validation gate passes or fails based on a field, attribute, or backing record, confirm that some production code path actually produces that input. A gate whose consumer is wired but whose producer is not will not behave as "unverified." It collapses to a constant verdict on every real item, most often fail-closed, because the input is always absent. The redacted output or blanket rejection is the symptom; the missing producer is the disease.

Why this hides: the gate's own tests construct inputs that already carry the backing field, then assert the gate reacts correctly to it. A test that hand-feeds the field cannot observe that nothing outside the test ever feeds it. So the suite stays green at every commit while the live system is fully broken. Green tests here prove the gate reads the field correctly, not that anything writes it.

How to apply:

1. For every gate input, run a producer/consumer census. Grep the codebase for the backing key across all source, then exclude test files and the gate's own module. If the only writers left are tests, the contract is unfulfilled.

2. Treat producer-writes and consumer-reads as two halves of one contract. Wiring the reader without the writer is an incomplete change, not a working feature.

3. Add at least one test that exercises the real production path end to end and asserts the backing field is present on genuine output. Do not let every assertion run on hand-built fixtures that pre-populate the field.

4. When a gate rejects or redacts everything, suspect a missing producer before suspecting the data. A 100% failure rate is rarely a real signal; it is usually an input that is never populated.

5. If you see the same failure shape recur across a codebase, stop patching instances and encode a check: no gate ships until its input has a non-test producer.
