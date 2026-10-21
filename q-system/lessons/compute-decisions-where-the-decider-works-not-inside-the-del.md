---
id: compute-decisions-where-the-decider-works-not-inside-the-del
kind: methodology
title: Compute decisions where the decider works, not inside the deliverable
date: 2026-10-19
---

When a quality or risk check runs only while generating an external-facing artifact, the artifact has become the computation instead of a rendering of a reviewed result. Symptoms: every internal view shows one item at a time, the aggregate check exists only in the customer-facing output, and the reviewer learns the outcome after the deliverable already exists. Two consequences follow. First, making the generator faster does not fix the design, because the reviewer is still deciding after the output is produced. Second, failures such as timeouts can go unnoticed for a long time, because nobody needs that screen to do their job, so no one is waiting on it.

How to apply it:
1. Audit where each aggregate computation actually runs. List every call site and mark which are reviewer-facing and which are output-facing. If the only aggregate call sites are output generation or tuning tools, you have a gap.
2. Move or expose the computation as a first-class internal surface (a group-level view) that the reviewer uses before any deliverable is produced. Make the deliverable read the already-computed result.
3. Treat placeholder phases as debt with a stated reason. If a stage is stubbed because its inputs do not exist yet (a field-name mismatch, or a metric not stored anywhere), track that as the blocker and verify the inputs end to end before wiring the stage in.
4. Bound any iterative or looping work by wall-clock time as well as by cost. A budget expressed only in money or tokens leaves latency unbounded, so add an explicit time limit and a defined behavior when it is hit (partial result, resumable job, or clear failure).
5. When documentation and an automated audit disagree, for example a static check flags code as unreachable, verify against the real call path before deleting. Aliased or module-qualified imports commonly produce false positives in reachability tools.

Signal to look for: a feature nobody complains about being slow is often a feature nobody depends on, which is a hint that the real workflow is happening somewhere else.
