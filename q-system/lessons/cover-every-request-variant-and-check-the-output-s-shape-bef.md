---
id: cover-every-request-variant-and-check-the-output-s-shape-bef
kind: methodology
title: Cover every request variant, and check the output's shape before calling it green
date: 2026-10-05
---

Two defects can ship together: a routing gap and a weak acceptance signal.

1. Routing gap. A dispatcher maps (request type, channel) to a producer. The table was built from one hand-written entry plus rows generated from a different list, so whole combinations had no route. Worse, the free-text classifier sent three phrasings of the same request to three different verdicts. The phrasing people actually use landed on the nearest wrong producer, which made a short reply into a full-length post.
   How to prevent it:
   - Generate the route table from the cross product of every request type and every channel. Do not hand-write the rows or inherit them from another list.
   - Add a test that fails on any cell with no route or more than one.
   - Keep a fixture of natural paraphrases per intent. Assert that all of them reach the same route, and that near-miss intents go elsewhere.
   - When no route matches, fail loudly. Never fall back to the closest producer.

2. Acceptance signal. The audit trail marked the run green because every gate it ran passed. None of those gates measured the property the user asked for, which was a short reply. A gate that cannot fail on the wrong output shape is decoration.
   How to prevent it:
   - For each request, name the one property that defines done, such as length, format or recipient, and assert it on the final artifact.
   - Run the gate against a known-wrong artifact, a long post for a reply request, and confirm it goes red.
   - Have the trail report which properties were checked. Do not let it say 'all gates passed' unless the user-visible property is among them.

If this class of defect has been fixed once and recurs, the earlier fix patched the symptom. Move the check into code that runs on every build, not into guidance.
