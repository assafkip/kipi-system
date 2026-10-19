---
id: validate-the-instrument-on-a-partial-run-and-apply-constrain
kind: methodology
title: Validate the instrument on a partial run, and apply constraints at the right layer
date: 2026-10-19
---

Two lessons from a long batch extraction job that produced implausible results and failed its own known-answer controls.

1. Apply a constraint at the layer it was meant for. A requirement like 'only use data already on the page, no click-through' can be over-applied. The intent was to avoid simulating a user journey to a final destination. It was wrongly extended to forbid resolving a link-shortener to its target, which is a single redirect response from the shortening service itself, not a visit to the destination. Since the identifier you're extracting usually lives only in that resolved URL (the shortener exists to hide it), the over-broad reading made the extraction structurally unable to find what it was looking for. Fix: when a constraint is written down, restate its intent separately from its literal wording, and ask which concrete behavior it is meant to exclude. Distinguish a bounded, single-hop resolution (do not auto-follow further) from a full traversal. Document the boundary explicitly (for example, 'exactly one redirect hop, no further following') so it is not reinterpreted later.

2. Run known-answer controls early, on partial output, not only at the end. The job had positive controls (items that must be found) but computed them only in the final summary step, after hours of work. The controls existed, but never gated anything. Fix: treat controls as a gate, not a report.
   - Before the full run, execute the pipeline on a tiny sample that includes the control items and confirm they are detected.
   - During the run, check controls against partial results at checkpoints (or run control items first) and abort on failure.
   - Add cheap plausibility checks (counts of extracted identifiers per item, rate of empty results, distribution sanity) and halt when they fall outside expected bounds.
   - Make the summary step callable on partial data so these checks are possible mid-run.

General rule: a control that is only evaluated after the expensive work is finished validates the result but cannot save the run. Point the instrument at a known answer first, and make failure stop the job early.
