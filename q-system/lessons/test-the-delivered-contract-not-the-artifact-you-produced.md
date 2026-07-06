---
id: test-the-delivered-contract-not-the-artifact-you-produced
kind: methodology
title: Test the delivered contract, not the artifact you produced
date: 2026-07-06
---

When you ship something across a boundary you don't control (a server, a platform surface, a client), the thing that matters is what the far side actually observes, not what you generated on your side. A produced artifact can be correct in content and still fail because the delivery layer strips, rewrites, or overrides the metadata the consumer contracts on.

Two failure modes travel together here.

First, the implicit-contract trap: you assume a platform surface honors a behavior it never promised. If that surface already misbehaved once on a related path, treat that as evidence about the surface, not a one-off. Reusing it on a new path inherits the same risk. Re-verify the contract on every path that rides the shared surface; a prior scar on one path is a warning about all of them.

Second, the wrong-layer test: a selftest that inspects the generated source proves the content exists, not that the consumer receives it correctly. Proving an output string was built says nothing about the runtime contract the far side enforces (headers, status, encoding, negotiated type).

How to apply:
- Identify the exact observable the consumer contracts on at the boundary (the header, status, type, or shape it keys behavior off of), and write the test against that observable, fetched live from the deployed path.
- Assert on the response the consumer actually gets, not on the artifact you produced upstream of delivery.
- When you reuse a surface that failed before, make the re-check mandatory for the new path; do not let familiarity substitute for verification.
- If you cannot exercise the live boundary in a test, treat the contract as unproven and flag it, rather than inferring success from source-level checks.
