---
id: prove-a-reimplementation-with-a-differential-replay-and-clas
kind: methodology
title: Prove a reimplementation with a differential replay, and classify every divergence by cause
date: 2026-07-06
---

When you rebuild or port a capability into a new system and need to know it still does the job, do not re-read the new code and reason about whether it *should* match. Run a differential replay: take a real, representative task, drive it through the old system and the new one under the same inputs and the same-capability dependencies, and diff the artifacts each produces.

How to run it:

1. Pick a real case, not a toy. Use inputs that exercised the original in production, so the replay tests the messy paths, not the happy one.
2. Hold everything constant except the system under test: same starting prompt/request, same external tools at the same capability tier, same data. A divergence only means something if the inputs were identical.
3. Diff at the artifact level, step by step. Build a table: for each observable output (each finding, value, intermediate result, decision point), record what each system produced and mark exact-match / new-system-better / gap. Assert on the produced artifact, not on the machinery that produced it.
4. Classify every divergence by cause before you judge it. Separate genuine defects in the new system from environmental limits (a rate limit, a missing credential, an unavailable service). An environmental gap is not a regression and must not be counted as one; a defect is. Tag each so the fix routes to the right place — code change vs. environment fix — and so 'we matched except where the environment blocked us' is a defensible claim, not a hand-wave.
5. Treat new-system-better as a first-class outcome, not noise. If the reimplementation reaches a result in fewer steps or surfaces something the original missed, that is signal about both systems worth recording.

The output is a per-step parity ledger with a cause tag on each mismatch. That ledger is the proof the port works — or the precise list of what to fix — in a way that reading the new code alongside the old never gives you.
