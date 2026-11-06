---
id: binary-gates-only-for-binary-rules
kind: pattern
title: Binary Gates Only for Binary Rules
date: 2026-11-06
---

## Principle

Automated quality checks come in two flavors, and conflating them stalls pipelines. Reserve hard pass/fail gates for rules that have an objectively verifiable answer. Route subjective judgments into advisory feedback that the author or generator revises against.

## How to classify a check

Ask: could two competent reviewers, given the same artifact and the same rule, disagree on the verdict?

- **No disagreement possible → blocking gate.** The rule reduces to a detectable presence or absence: a forbidden term appears, a required field is missing, a claim has no source in the provided inputs, a numeric value falls outside a declared range.
- **Disagreement possible → advisory signal.** The rule asks about tone, style, voice, elegance, persuasiveness, or "fit." These are gradients, not lines.

Write the rule down and try to state its failure condition as a single testable predicate. If you cannot do it without using a word like "appropriate," "natural," "clear," or "on-brand," it is not a gate.

## How to implement each tier

**Blocking tier.** Keep each rule narrow and independently evaluable. One check, one predicate. Emit the exact rule that failed and the offending span so the fix is mechanical. Failure here means the artifact cannot ship.

**Advisory tier.** Return structured guidance instead of a verdict: a score or qualitative note, the dimension being judged, and a concrete suggested revision. Feed this back as input to a revision step. Allow the artifact to proceed after a bounded number of revision rounds even if the advisory signal is still imperfect.

## Operational safeguards

Instrument rejection counts per rule. A single check that accumulates a large backlog of rejected artifacts with no successful passes is not enforcing standards; it is a misclassified subjective rule wearing a gate's clothing. Set a threshold and alert on it.

When a gate blocks, log which specific predicate fired. Aggregate rejection reasons that cluster around taste rather than fact are the signal to demote that check to advisory.

Always cap revision loops. An advisory signal that never reaches satisfaction must eventually yield to a human reviewer or a ship-with-warning path, otherwise it becomes a gate by exhaustion.

## Why this matters

Subjective criteria enforced as binary gates produce near-total rejection, because there is no deterministic edit that satisfies an undefined target. Throughput collapses while the apparent cause looks like poor artifact quality rather than a mis-specified check. Separating the tiers makes the real constraint visible and keeps the pipeline moving.
