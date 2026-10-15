---
id: put-the-decision-on-the-surface-where-the-work-happens-not-o
kind: methodology
title: Put the decision on the surface where the work happens, not only in the deliverable
date: 2026-10-05
---

When a computation exists only inside the step that generates a customer-facing artifact, the artifact becomes the first place anyone sees the result. Reviewers then decide after the output already exists. Slowness or timeouts in that step stay invisible, because nobody's job depends on that screen.

Three checks:

- Map every call site of the expensive computation. If the only aggregate-level caller is the output generator, reviewers have no view of the aggregate, so generation is doing the real work and review is happening afterward.
- Ask who waits on each screen. A screen nobody waits on can fail silently for a long time. Failures there carry no signal about how much the work matters.
- Do not fix this by making generation faster alone. Speed leaves the ordering wrong. Move or expose the computation so reviewers see it before the artifact is built, then have generation read the stored result.

A related trap: a retry or refinement loop whose cost is capped in money but not in elapsed time. Give every loop a wall-clock budget alongside its spend cap.

When a static audit and your documentation disagree about whether code is reachable, check how the call is written (aliased imports, module-qualified calls) before deleting anything. A tool that matches names can miss calls that go through an alias.
