---
id: when-the-goal-becomes-match-this-reference-measure-the-shape
kind: methodology
title: When the goal becomes "match this reference", measure the shape
date: 2026-10-12
---

## The failure shape

A generator is retargeted: the new goal is for its output to resemble a reference set that was analysed and characterised. Each round, more guidance about the reference is added to the generation step. The output keeps coming out in a different shape than the reference, and nobody can say by how much, because nothing ever compares the two.

Four independent mechanisms produce this, and fixing one leaves the other three running.

## 1. Old constraints outrank the new goal

The pipeline already carries rules from earlier goals: validators that reject certain forms, instructions injected into every request, option lists with entries excluded. When the goal changes, those rules do not. An approval to relax them applies to the wording of the new guidance while the enforcing code keeps rejecting the exact move the reference set relies on.

How to handle it: when a target changes, enumerate every place a constraint is enforced for the old target, not just the place the new guidance is written. For each constraint, state whether it still holds under the new target, is relaxed, or is now inverted. A relaxation that lives only in prose while a check still rejects the form is not a relaxation. The check is the rule.

## 2. The input decides the shape, and style guidance cannot override it

If every item fed to the generator is a finished, closed artifact of one kind, the output takes the shape that kind implies, whatever the style guidance says. A closed case in produces a case report out. If the reference set is mostly built from a different kind of starting material, matching it requires changing what goes in, not layering more instructions on top of the same input.

How to handle it: before adding another round of style guidance, characterise the input population by kind and compare it to what the reference set appears to start from. If the distributions differ, the gap is an intake gap. Repeated style guidance that never changes the input is the signal that this is being missed.

## 3. The measurement exists but is never compared

Often the instrument that characterised the reference set already runs on new output and its result is stored. What is missing is the comparison: output distribution against reference distribution, on the same axes, every round. Without it, rounds get judged by proxy counts that are cheap to compute and blind to shape: banned-phrase hits, validator passes, individual defect tallies. Those can all improve while the output stays in the wrong shape.

How to handle it: make the per-round check a distribution diff on the reference's own axes, reported as the target rate next to the current rate per axis. Proxy counts stay as guards against regressions; they do not stand in for the comparison. If an axis reads zero where the reference reads a substantial share, that is a mechanical block somewhere, not a tuning problem.

## 4. Rounds chase the latest note

Each round addresses the most recent piece of feedback and nothing else, so earlier findings quietly reopen and the same class of miss returns under a new surface.

How to handle it: hold feedback in an accumulating record the pipeline reads, with every ruling still in force, and re-check all of it each round rather than only the newest item.

## The order to work in

Measure output against the reference first, before changing anything. An axis reading zero points to an enforced constraint. An axis off by a large multiple points to the input population. An axis drifting between rounds points to the accumulation gap. Adding guidance is the last move, not the first, and it only works on the axes the other three mechanisms are not holding shut.

## Smells

Style guidance has been added several times with no measured change. The reference set was characterised once, at the start, and never used as a per-round instrument. A relaxation was approved verbally. Round summaries report counts in a unit the goal is not expressed in.
