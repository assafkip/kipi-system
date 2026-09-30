---
id: calibrate-a-gate-against-the-corpus-it-claims-to-encode
kind: methodology
title: Calibrate a gate against the corpus it claims to encode
date: 2026-08-31
---

A gate that encodes a standard has one obligation before it blocks anything: the reference examples of that standard have to pass it. Skip that and you ship a filter that rejects the thing it was built to protect.

## The shape of the failure

Three independent causes stack, and each one is easy to miss alone.

**1. A rule written for one input class ends up judging every input class.**

The rule is correct for the supply it was designed against. Then a second and third caller start using the same evaluation entry point, with no argument saying which lane the input came from. Now a constraint that is right for machine-mined or third-party material is applied to material the author wrote themselves, where it is simply wrong. The bug is not the rule. The bug is that the shared entry point takes no lane parameter, so every caller silently inherits the strictest assumptions of the first one.

**2. Nothing asserts that the reference corpus clears the blocking tier.**

Rules get swept against the corpus once, at authoring time. Then new rules are added, or existing rules start applying to a new lane, and nobody re-sweeps. The gate drifts into rejecting a large share of the very examples it was distilled from, and no test goes red, because no test exists that runs the corpus through the blocking tier.

**3. Advisory rules that fire on nearly the whole corpus are still training signal.**

Demoting a rule from blocking to warning removes the refusal. It does not remove the pressure. Whoever reads the output, human or agent, edits toward clearing the warning. A warning that fires on almost every real example is not a soft signal, it is a slow rewrite of the standard, applied without anyone deciding to change it.

## How to build so it cannot hide

**Make the lane explicit at the call boundary.** Any shared evaluator that serves more than one supply takes a required lane argument. No default. A caller that does not know its own lane is a defect surfaced at the call site instead of a wrong verdict downstream.

**Write the calibration test before the gate ships.** Feed the reference corpus through the blocking tier and assert a floor: the canonical examples pass. This test is the only thing that can catch a gate inverting on its own subject matter, and it must be able to go red. Confirm it does by mutating one rule to be over-broad and watching it fail.

**Re-run calibration when scope changes, not only when rules change.** Adding a caller to an existing evaluator is a scope change and needs the same sweep as adding a rule. Scope changes are the ones that get skipped, because the rule text did not move.

**Audit advisory rules by fire rate, not by severity label.** Any rule firing on a large majority of the reference corpus is a finding regardless of tier. Either the rule is wrong, or the corpus is no longer the reference. Decide which. Leaving it as a permanent warning picks the first option by default and hides the choice.

## The general rule

A validator built from a body of work owes that body of work a passing grade. If it cannot produce one, the validator is describing a different standard than the one it was named for, and every downstream consumer is now being steered toward that different standard without a decision ever being recorded.
