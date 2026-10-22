---
id: test-against-the-real-shape-of-your-data-and-wire-guards-ont
kind: methodology
title: Test against the real shape of your data, and wire guards onto the live path
date: 2026-10-05
---

Two failures combined to let a defect reach production undetected, and both generalize.

1. The code's mental model of the data was simpler than reality, and the tests inherited that model.
- Production records were nested, wide, and used value vocabularies the code never saw. The code and its fixtures assumed flat, small, hand-written shapes.
- A test labelled as reproducing the production shape used field names that existed in no schema. Fixtures used enum values the live system never emits. The largest cohort in any test was two items.
- Hardcoded value sets in logic (verdict labels, field locations) had drifted from live values, and several schema descriptions in the repo disagreed with each other and with the live data.
- The real shape was already declared as data in config the code owned, but the logic read none of it.
- Fix pattern: derive fixtures from the declared schema or sampled real records. Add a test asserting every fixture field exists in the schema, and every schema field the logic reads exists in real records. Treat enum literals in code as suspect until checked against live values. Test at realistic cohort sizes, not the smallest that passes.

2. Safeguards were built but left one connection short of the live path.
- A shape-validation guard shipped behind an opt-in flag that nothing ever set, so it never ran in production.
- A wrapper that adds a limit to bulk reads required a capability on the wrapped component, and the component actually used in production lacked it, so the protection silently did not apply.
- Fix pattern: for every guard, name the caller on the production path that invokes it. Default guards to on and make opting out the explicit act. Add a test that builds the real production wiring and asserts the guard is active, rather than testing the guard in isolation.

General check: a feature is not done when the code exists. It is done when a test through the production entry point shows it firing against realistically shaped data.
