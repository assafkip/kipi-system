---
id: make-every-request-shape-routable-and-verify-output-against-
kind: methodology
title: Make Every Request Shape Routable, and Verify Output Against the Request
date: 2026-10-12
---

When a system routes requests to producers (generators, handlers, workflows), two failures tend to hide each other: a missing route that silently falls through to a wrong-but-plausible one, and an acceptance signal that checks process rather than fit.

1. Enumerate the routing matrix, not the happy path. List every (intent x channel) pair the system claims to support, such as original vs reply, long vs short, per destination. Generate that matrix from the same registry the router uses, and assert each cell resolves to exactly one route. Missing cells must fail loudly in a test. Do not let them fall back to a nearby producer. Routes registered from a single hand-written special case, while the rest are generated from a list of defaults, are a smell: the generated families will cover only one intent variant and the gap goes unnoticed.

2. Test the classifier with natural phrasings. Write a table of the ways real users ask for the same thing (different verbs, nouns, word order, with and without the channel named) and require identical routing for equivalent phrasings. If three phrasings of one request give three different verdicts, the classifier is keying on incidental words. Common phrasing must never land on the most general producer by default. Prefer an explicit 'unrouted, ask or refuse' result over a silent best guess.

3. Make the output contract part of the request. A short reply, a comment, or a one-liner has constraints (length, form, no standalone framing) that differ from a full artifact. Derive those constraints from the resolved route and check the produced artifact against them, not just against generic quality gates.

4. Do not report green from gates that cannot see the defect. Before saying something passed, ask whether the checks that ran could have failed for this defect. A pass on generic style or format checks says nothing about whether the artifact is the right kind of thing. State exactly what was verified and what was not. Add a fit-for-intent check, such as comparing artifact shape to the requested shape, so wrong-kind output is a hard failure.

5. Treat a repeat as a process failure. If the same class of defect recurs, the earlier fix was too narrow. Fix the class by adding the matrix test and the fit check, and do not patch the single phrasing that was reported.
