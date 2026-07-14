---
id: verify-the-artifact-against-the-design-not-that-the-machinery-ran
kind: methodology
title: Verify the artifact against the design, not just that the machinery ran
date: 2026-07-14
---

The most common way a shipped automation is wrong-but-green: the builder verifies
that the mechanism RUNS (no error, output reaches the destination, no crash) and
treats that as done, without checking that the OUTPUT matches the design intent.
The machinery working and the artifact being correct are different claims. A
scheduler that places posts without erroring can still place them on the wrong
days; a generator that produces valid output can still ignore the cadence,
frequency, ordering, or spread the spec required. "It scheduled without erroring"
is not "it scheduled per the design." The gap hides because the happy-path test
and the design-conformance test look superficially similar.

How to build it safely:

1. Write the acceptance check against the ARTIFACT and the SPEC, not the run. Do
   not assert "the call returned 200" or "N items were produced." Assert the
   properties the design actually requires: the schedule matches the stated
   cadence, the spread is per-day-correct, the frequency per channel is within its
   configured bounds, the ordering honors the plan. If the spec says "at most one
   per day, spread across days," the test computes the per-day counts of the
   produced schedule and fails if any day exceeds the cap. Test the output's shape
   against the intent, every time.

2. Make the governing value machine-readable before you rely on it. A correctness
   rule that lives only in prose (a research doc, a strategy note) cannot be
   honored by code and cannot be asserted in a test. If a cadence, frequency,
   offset, threshold, or ordering governs whether the output is right, encode it
   as config the mechanism reads and the test checks. Prose the code never loads is
   a spec the machine cannot follow.

3. Read the design canon before wiring, not after the incident. The intent is
   often already written down (a spec, a strategy doc, a prior decision). Wiring a
   mechanism without first reading what the output is supposed to look like is how
   a builder substitutes a plausible-but-wrong behavior ("pack into the next free
   slot") for the specified one ("honor the per-channel cadence"). The canon that
   would have prevented the miss frequently already exists.

4. A captured gap is not a shipped-safe gap. If pre-ship you notice and write down
   a known shortfall, that item must be resolved or explicitly accepted BEFORE
   flipping to live — not carried past the go-live in the same breath. Capturing a
   defect and then overriding it with "ship it" defeats the capture; the write-down
   only helps if it gates the ship.

The durable rule: proving the machinery ran is not proving the artifact is right.
Encode the governing spec as machine-readable config, assert the produced output
against that spec (not against "it ran"), read the design canon before wiring, and
never ship past a gap you have already written down.
