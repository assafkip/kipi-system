---
id: test-against-real-data-shape-and-wire-safeguards-into-the-li
kind: methodology
title: Test Against Real Data Shape and Wire Safeguards Into the Live Path
date: 2026-10-12
---

When a feature works in tests but yields nothing on real data, suspect two linked failures.

1. Tests and code share a simplified mental model of the data. The code and its fixtures assume a flat, small, idealized structure, while production data is nested, larger, and uses different field locations and enumerated values. Tests built from the same simplified model pass while proving nothing. Typical symptoms: fixtures use field names or value literals that appear in no authoritative schema; cohorts in tests are tiny compared with production; several schema descriptions in the repo disagree with each other and with the live system; logic reads fields from one location while real records store them elsewhere; and a declared schema or taxonomy exists as data but the consuming code never reads it.

How to prevent it:
- Make one machine-readable schema the single source of truth, and have both the logic and the fixtures derive from it.
- Add automated checks that every field and enum value used in code and fixtures exists in that schema, and that the schema matches a sample of real records.
- Build at least one test from a sanitized, real-shaped record, including nesting depth, realistic value vocabularies, and realistic cohort sizes.
- Treat a test labelled as reproducing production shape as a claim, and verify it against the real schema.
- When an earlier decision warned about testing against a distorted surface, convert that warning into an enforced gate rather than leaving it as prose.

2. Safeguards were built but never connected to the live path. A validation guard and a resource-limiting wrapper were each written after an earlier incident, yet one is opt-in behind a flag that is never set, and the other depends on a capability that the production wrapper does not provide. They pass their own tests and do nothing in production.

How to prevent it:
- Make protective checks default-on, with an explicit opt-out rather than an opt-in.
- Where a decorator or wrapper requires an interface from what it wraps, enforce that requirement at construction time so a mismatch fails loudly rather than silently skipping.
- Add an end-to-end test or startup assertion that proves each safeguard is active on the real production code path.
- After any incident, confirm that the fix is reachable from the real entry point, not only that it exists and is unit-tested.
- Audit for flags that are defined but never set in any deployment configuration.
