---
id: test-the-user-s-exact-phrasing-against-every-route-and-don-t
kind: methodology
title: Test the user's exact phrasing against every route, and don't let a green trail stand in for the output
date: 2026-10-04
---

Two failures can hide behind a passing pipeline: a routing table that covers only the cases its author imagined, and an acceptance signal that records process success instead of what the user received.

Defect 1: a router built from a few hand-written entries plus generated rows. Generated rows covered one variant (create new content). The sibling variant (respond to existing content) existed for one channel and was missing for the rest. Asking for the same thing in three natural phrasings produced three different verdicts: an error, a wrong route, and no route. The most common phrasing landed on the wrong producer, so the user got a long original post when they asked for a short reply.

How to prevent it:
- Build the route table as a full matrix (every intent x every channel), then assert that each cell resolves to exactly one route or to an explicit, tested refusal. A missing cell fails the test.
- Write the classifier tests from the words users actually type, with several phrasings per intent, not from your internal labels.
- When you add a new variant for one channel, enumerate the others in the same change. A sibling that works for one channel and errors for the rest is the signature of this bug.
- Treat 'no single route' errors as a signal that the table has holes, not as acceptable edge cases.

Defect 2: the trail reported success. The checks that ran were real, but they validated properties the wrong output could still satisfy (format, tone, banned words, wiring present). None checked the property the user cared about, which was that the output was the right kind of thing at the right size.

How to prevent it:
- Add an acceptance check that observes the user-visible property: output type, length bound, and target surface. Fail the run when the output does not match the request.
- Report 'green' only for the checks that ran, and name what was not checked. Never summarize a partial trail as passing.
- Before telling a user something passed, compare the delivered artifact to the original request. Passing gates describe the process, not the result.
- When a defect recurs, treat the recurrence as evidence that the first fix addressed a symptom. Look for the missing structural check, and make it a script or test rather than a note.
