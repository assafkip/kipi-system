---
id: test-against-the-shape-production-actually-has-not-the-shape
kind: methodology
title: Test against the shape production actually has, not the shape you pictured
date: 2026-09-21
---

## The failure shape

A feature ships green and then does nothing on real data: no report, no counts, every finding dropped. Nothing crashed, so nothing alerted. Two causes usually sit together.

### Cause 1: the code and its tests share one wrong mental model of the data

The code was written against a simple picture of the records: flat, small, using the words from the spec. Production records are nested, much wider, and use different words. The tests were built from the same simple picture, so they agree with the code and both are wrong together. Common signs:

- The real shape is already written down somewhere the project owns, like a field allowlist, a schema file, or a taxonomy of evidence paths. The code that reads records ignores it.
- A test that says it reproduces the production case uses field names that appear in none of those declared shapes.
- Fixtures use made-up enum values ("suspicious", "real") that differ from the live values in spelling or case, or in the set of values itself.
- The code reads a value from one parent object when live records carry it under a different parent.
- Several docs give different counts for the same schema, and none of them was measured.
- The biggest cohort any test sends through the resolver has one or two rows, so a lookup that fails on most fields still passes.

### Cause 2: the safeguards exist but are not connected

A guard built after an earlier incident is behind an opt-in flag that nothing sets. A wrapper that adds a needed capability only works if the wrapped object has some method, and the object used in production does not have it. Each piece passes its own tests. None of them runs on the path users hit.

## The method

1. **Make the declared shape the only source of fixtures.** Generate or validate test records from the schema or allowlist the project already has. Add a test that fails if any field a fixture uses is missing from that schema.
2. **Pin the schema to reality.** Add a check, run against a sampled or captured real record, that fails if a field the code reads is absent in real data. Store the sample so the check can run offline.
3. **Read enum values from observed data, not the spec.** Collect the distinct live values once, commit them, and compare case-sensitively. When a value arrives that is not on the list, count it and surface it. Never let it quietly fall through to "no match".
4. **Resolve nested paths explicitly.** If the data is nested, the accessor takes dotted paths and fails loudly when a path cannot be resolved. A missing key is an error, not a zero.
5. **Test at production cardinality.** At least one test runs a realistic number of records and fields through the real resolver and asserts that most fields resolve, not only that the output is non-empty.
6. **Treat 'no output' as a failure.** If real input produces no report or drops every item, report that as its own failure with the reason, never as a clean empty result.
7. **Audit every guard for its live wiring.** For each safeguard, name the production entry point that turns it on. If it only runs when a flag is set, either set the flag in production config or delete the guard. If a wrapper depends on a capability, assert at startup that the production object has it.
8. **Reconcile conflicting shape descriptions.** When two docs disagree on the schema, measure the live data, then fix or delete the wrong ones so a single description remains.

## The check that would have caught it

A test that loads a real (sanitized) record, runs the real code path on it, and fails if the output is empty or if more than a small share of the fields the code asks for do not resolve. It uses the production wrapper, not a test double. If that test cannot be written because no real record is available, capturing one is the first task.
