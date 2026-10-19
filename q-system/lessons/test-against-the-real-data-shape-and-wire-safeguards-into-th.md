---
id: test-against-the-real-data-shape-and-wire-safeguards-into-th
kind: methodology
title: Test against the real data shape, and wire safeguards into the live path
date: 2026-10-19
---

When a feature returns nothing on production data while passing its tests, two failure modes are often combined.

1. Tests and code share a simplified picture of the data. The code and fixtures assume flat, small, idealized records, while production holds nested, larger, messier ones. The real shape is often already declared somewhere as data, such as a schema, allowlist, or taxonomy, but the logic that uses it never reads those declarations. As a result, tests built from the same simplified picture confirm the wrong assumption. Warning signs: a test claiming to mirror production uses field names found in no schema; the largest dataset in any test is tiny; enumerated values in code (such as verdict labels) differ from what production emits; fields are read from one location while production stores them in another; several documents describing the same schema disagree on counts.

 How to apply: (a) make the declared schema the single source of truth, and have both code and fixtures derive from it or be validated against it; (b) add checks that every field a fixture or the code references exists in a sample of real records; (c) include nested paths, realistic cardinality, and the real value vocabularies in fixtures; (d) periodically diff the descriptions of the schema against each other and against live data; (e) when an earlier decision predicted this failure, turn it into an enforced check, not a note.

2. Safeguards were built but never connected to the live path. A validation guard sat behind an opt-in flag that nothing set, so it never ran in production. A wrapper capability depended on a prerequisite that the actual production wrapper did not provide, so it silently did nothing. Warning signs: a fix shipped after an incident but has no evidence of executing in production.

 How to apply: (a) default protective guards to on, or fail loudly when they are off; (b) after shipping a guard, verify it by observing it run in the real environment, such as through a log line, metric, or end-to-end test through the real wrapper stack; (c) test composed layers as they are assembled in production, not in isolation; (d) check that each decorator or adapter has the interfaces its dependents require, and raise an error when one is missing instead of degrading silently; (e) track 'built but not wired' as an explicit item in incident follow-up.
