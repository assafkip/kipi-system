---
id: test-against-the-real-shape-of-production-data-and-wire-safe
kind: methodology
title: Test against the real shape of production data, and wire safeguards into the live path
date: 2026-10-04
---

Two independent failures combined to leave a feature broken on real data while every test passed.

Failure 1: the code and its tests shared a simplified model of the data. Production records were nested, large, and used different field names and enumerated values than the fixtures. Tests built from flat, small, hand-written samples confirmed the code against the author's assumptions, not against reality. Signs of this: a test labelled as reproducing the production shape that uses fields appearing in no schema; the largest cohort in any test being tiny; enum literals in code that match no live value; fields read from one location when the live record stores them in another; several schema descriptions that disagree with each other and with the live data. The team had even recorded the risk in advance (flattening nested data tests against a misshapen surface) and still did not act on it.

Failure 2: safeguards that would have caught or fixed the problem were built but never connected to the live path. A shape validator sat behind an opt-in environment flag that no environment ever set. A bulk-read wrapper required a capability on the wrapped component that the real production wrapper did not provide, so it silently did nothing. Code existed, tests passed, and production never ran it.

How to apply:
- Derive fixtures from sampled real records, or from a schema that is itself checked against real records. Add a test that every field a fixture or code path names exists in a real record.
- Include realistic scale and nesting in at least one test: cohort sizes, depth, and the true enum values.
- When several descriptions of the same schema exist, pick one source of truth and add a check that the others agree with it.
- Treat a recorded risk as a work item with an owner and a test, not a note.
- For every guard, ask what turns it on in production and what the production object must supply for it to engage. Default it on, or make it fail loudly when its precondition is missing.
- Prove the guard fires through the real entry point, with a negative case that shows it blocking bad input.
