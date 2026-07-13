---
id: a-gate-s-input-needs-a-production-producer-not-just-a-test-t
kind: pattern
title: A gate's input needs a production producer, not just a test that hand-feeds it
date: 2026-07-13
---

A validation gate that reads a field is only half a feature. If the only code that ever writes that field lives in the gate's own test suite, the gate never sees real backing data: in production the field is always empty, so a fail-closed gate rejects 100% of real inputs while every test stays green. The tests cannot catch this, because they construct the input themselves; a test that hand-feeds the value a component reads is structurally blind to the absence of a real producer.

How to apply:

1. When wiring any consumer of a field (a validator, gate, router, or formatter), verify the producer exists in production code before calling the work done. Run a repo-wide search for every write site of that field and exclude the test directory. If the only writers are tests, the contract is unimplemented, not enforced.
2. Treat every read-only field as a red flag during review: 'who populates this, on the real path?' is a question with a greppable answer. Demand the write site, not an assurance.
3. For fail-closed gates specifically, add at least one end-to-end test that runs the real production path from raw input to gate verdict, without constructing the gate's input by hand. That is the only test shape that can detect a missing producer.
4. If the same package has produced this defect class before, add a deterministic check (a script or CI step) that asserts each gated field has a non-test write site. Recurring classes deserve mechanical detection, not vigilance.

The general contract: a consumer without a production producer is dead wiring, and tests that supply the consumer's input verify the consumer's logic while hiding that the wiring is dead.
