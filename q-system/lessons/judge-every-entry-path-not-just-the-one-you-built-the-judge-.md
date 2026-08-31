---
id: judge-every-entry-path-not-just-the-one-you-built-the-judge-
kind: pattern
title: Judge every entry path, not just the one you built the judge for
date: 2026-08-31
---

# Pattern

A system can have real quality evaluation and still ship unjudged output, because the evaluator was attached to one entry path and the path people actually use is a different one. Nobody removed the check. It was never wired there.

## The shape

- Quality evaluation (a critic, a reviewer, a fidelity or style scorer) is attached to a specific execution path, usually the one that existed when the evaluator was written.
- A second path is added later for convenience, speed, or a different input type. It reuses the pipeline but not the evaluation stage.
- The second path becomes the default, because it is the easier one to invoke.
- Acceptance on that path collapses to whatever structural signals survive: the job exited zero, the schema validated, the required checks are green. None of those look at whether the output is any good.
- Output that is structurally clean and substantively wrong ships repeatedly, and each run looks like a success in the trail.

## Why it survives review

The evaluator exists, so a reader auditing the system finds it and concludes quality is covered. The gap is not a missing component, it is a missing edge between a component and a path. Reading the code inventory will not surface it. Only tracing each entry path end to end will.

A second reason it survives: the failure repeats identically across reviews. Restating the same finding feels like diligence, so the finding gets re-recorded instead of fixed. A defect that appears in three consecutive reviews unchanged is not an open finding, it is an accepted one.

## How to find it

1. Enumerate every way work enters the system. Include the ad hoc path, the manual invocation, the convenience wrapper, the retry path, and the one used only during development.
2. For each path, list the stages that actually run. Do not read the design document. Read the dispatcher, or instrument the run and see which stages log.
3. Mark which paths reach the quality evaluation stage. The unmarked ones are the finding.
4. Rank by traffic, not by design intent. The unjudged path with the most runs is the real problem.

## How to fix it

- Move the evaluation stage from the path to the chokepoint every path passes through, so a new path inherits it rather than opting into it.
- Where a chokepoint does not exist, make the absence of a quality verdict an explicit failure rather than a silent pass. An output with no verdict attached is unaccepted, not accepted.
- Separate the two signals in whatever record the run leaves behind. Structural validity and quality verdict are different fields. Collapsing them into one "passed" is what let the gap hide.
- Prove the fix by running the judge and watching it fail on a deliberately bad output on that path. An evaluator that has never returned a negative verdict on that path is not yet known to be connected.

## The test that would have caught it

Generate a batch through the path in question, hand it deliberately degraded content, and confirm the run is rejected. If the run passes, the judge is not on that path, regardless of what the configuration says.

## Generalization

Any stage that enforces quality rather than structure is at risk of this. Access control, cost limits, safety filters, and provenance capture all fail the same way: wired to the original path, absent from the one that grew around it.
