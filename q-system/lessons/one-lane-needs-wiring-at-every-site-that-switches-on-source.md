---
id: one-lane-needs-wiring-at-every-site-that-switches-on-source
kind: pattern
title: One lane needs wiring at every site that switches on source
date: 2026-08-11
---

A new input lane was added to a content pipeline and produced nothing, three times in a row, for three different reasons. It was first placed in the CLI entry point, which no scheduled path calls, so it ran zero times and said nothing. Moved to the real builder, every candidate was then refused by the provenance check, whose label mapper knew three source prefixes and not the new one: 83 rejections reading "this text is not vouched". With provenance resolving, all of it was refused again, 87 rejections carrying the identical message, because the function that decides whether raw material must be written into a post also switched on source prefix and had the same three-entry list. The material was being handed to the checks verbatim and refused as though a human had typed it.

How to apply:

1. Before adding a lane, find every site that branches on where a candidate came from, and list them. In a mature pipeline the source prefix is load-bearing in more places than the author of any one of them remembers: routing, provenance, formatting, dedup, telemetry. Grep for the existing prefixes rather than for the concept, because each site names them as literals.

2. Expect the failure message to describe the wrong layer. Two of the three failures above reported a vouching problem, which was a true statement about the symptom and pointed nowhere near the missing branch. When a message blames a check you have not touched, ask whether the thing it is checking ever got built.

3. Treat "produced zero" as a distinct failure from "produced badly". Zero output means a wire, not a quality problem, and it will not be improved by tuning. Every hour spent on the material while the count is zero is wasted.

4. Prove the lane end to end with an artifact, not with a source grep. That a call exists in a file says nothing about whether the live path reaches it, and each of the three failures above passed a grep for its own wiring. The only sufficient evidence is one finished output that could not have come from anywhere else.

5. When a routing function documents that it dispatches by source and not by inspection, read that as a warning about itself. A design that is correct precisely because it refuses to look at content has no way to notice an unfamiliar source; it will silently pick the default branch, and the default is usually "do nothing".

6. Count the sites afterwards and write the number down. One lane needing three separate edits is a fact about the codebase's shape, and the next lane will need the same three.
