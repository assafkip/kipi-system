---
id: exercise-a-structural-artifact-against-its-real-validator-an
kind: methodology
title: Exercise a structural artifact against its real validator, and don't let one layer's names become another's contract
date: 2026-07-06
---

Two failures compound when a schema, migration, config, or other structural artifact ships without being run against the system that will ultimately accept or reject it.

HOW to avoid the first (untested artifact): before any remote or production apply, run the artifact through the same kind of engine that will consume it — parse it, load it, or apply it against a throwaay/local instance in your test suite. Tests that only cover the human-facing outputs (rendered views, formatted reports) prove nothing about the machine-facing artifact. If a downstream system can reject the artifact, a local test must be able to reproduce that rejection. Absence of such a test means the first real check happens in production.

HOW to avoid the second (leaked contract): when a name travels from one layer to another (an external/client-facing field into an internal store, a display label into an identifier, a user string into a query), treat the two names as separate contracts that happen to share a value — not as one shared name. At each boundary, translate deliberately and validate the value against the receiving layer's rules: reserved words, length limits, character sets, uniqueness, casing. A name that is friendly and legal in the origin layer can be illegal in the destination. Put the translation and the check at the boundary so an origin-side rename can never silently violate a destination-side constraint.

The general rule: any artifact that another system will validate must be exercised against that validator before it ships, and any name crossing a layer boundary must be re-checked against the receiving layer's constraints rather than assumed compatible.
