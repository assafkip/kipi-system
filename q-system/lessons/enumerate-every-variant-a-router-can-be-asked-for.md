---
id: enumerate-every-variant-a-router-can-be-asked-for
kind: pattern
title: Enumerate every variant a router can be asked for
date: 2026-09-07
---

When a dispatch table covers one axis by enumeration and the other axis by hand-written special cases, coverage is accidental. The enumerated axis (targets, channels, backends) gets every row generated; the variant axis (the sub-kind of the thing being produced: original vs reply, create vs amend, full vs partial) gets one hardcoded entry for whichever case someone needed first. Every other combination then either errors out or, worse, falls through to the default variant and produces a plausible artifact of the wrong kind.

How to work it:

1. Write the routing axes down as a grid before reading the code. One axis per independent dimension of the request. Enumerate the full cross product, not the rows that exist.
2. Print the resolved route for every cell. A cell that errors is visible and cheap. A cell that silently resolves to the default-variant producer is the dangerous one, and only a printed grid shows the difference.
3. Make the variant a first-class field derived from the same enumeration as the other axis, not a list of exceptions. If a variant cannot be generated for a target, make that an explicit declared gap that fails loudly, not an absent row.
4. Test the classifier that fills those fields with the phrasings people actually use, not the canonical vocabulary the code was written against. Collect several natural phrasings of one request and assert they all resolve to the same cell. Divergent verdicts across paraphrases of one intent is a defect, not user error.
5. Make the acceptance check assert the KIND of the produced artifact, not that a producer ran without error. A gate that only verifies "something was generated and passed the style checks" reports green on a correct-looking artifact of the wrong type. Add a check that can fail on kind: length band, required structural marker, or the target field echoed back and compared.

The recurring failure shape: the request type most people actually make is the one with no enumerated row, because the enumeration was built from the producer's inventory rather than from the space of things that can be asked for. Build the grid from the request space, then prove each cell resolves where you claim.
