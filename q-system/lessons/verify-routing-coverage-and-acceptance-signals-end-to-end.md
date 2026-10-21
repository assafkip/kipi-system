---
id: verify-routing-coverage-and-acceptance-signals-end-to-end
kind: methodology
title: Verify routing coverage and acceptance signals end to end
date: 2026-10-19
---

When a request-to-producer router handles several artifact types, two failure modes tend to recur together: an incomplete route table, and an acceptance signal that reports success without checking the artifact's fit.

1. Route coverage is a matrix, not a list. Build the routing table from the full cross product of (artifact kind) x (destination), and for each cell make the outcome explicit: a working producer, or a deliberate refusal. Do not let one hand-written special case stand in for a whole family. When a kind exists for only one destination, other destinations silently fall through to the nearest-looking producer or to an error. Add a test that enumerates every cell and fails on any gap, so a new destination or kind cannot ship half-wired.

2. Classify by intent, not by exact phrasing. Take the several ways a person would naturally ask for the same thing, including casual, terse, and ambiguous wording, and assert that they all resolve to the same route. If paraphrases of one request produce different verdicts, the classifier is keyed to vocabulary rather than meaning. Treat the most natural phrasing as the primary regression case. Where the request is ambiguous, ask or fail loudly instead of defaulting to the largest or most familiar producer.

3. Acceptance gates must check the properties the requester cares about. A pipeline that checks only generic hygiene (formatting, banned terms, structure) can pass an artifact of the wrong type or size. Add gates for the requested form: length bounds, format, and whether it is a standalone piece or a response within a context. Make the final report state which checks actually ran and which were not applicable, and never summarize the result as passing when the decisive check is absent.

4. Reproduce before fixing. Run the failing inputs through the router and record the exact outputs. Reports of a bug are often less severe than the measured behavior, and the reproduction shows the real shape of the gap.

5. Treat recurrence as a signal. If the same class of defect has appeared before, a one-off patch is insufficient. Convert the lesson into a structural check, such as a coverage test or a gate, so that it fails mechanically next time instead of relying on memory.
