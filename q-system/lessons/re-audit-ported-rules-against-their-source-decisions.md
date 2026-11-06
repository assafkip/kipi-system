---
id: re-audit-ported-rules-against-their-source-decisions
kind: methodology
title: Re-Audit Ported Rules Against Their Source Decisions
date: 2026-11-06
---

## Problem

When a set of rules, constraints, or configurations is copied into a new context — a new environment, a new pipeline stage, a merged ruleset, a rewritten implementation — the copy is usually treated as equivalent to the original. It rarely is. Rules drift during the move: thresholds tighten, defaults change meaning under new surroundings, and individual decisions vanish without leaving a gap that anyone notices.

The failure is silent because the ported set looks complete and self-consistent. Nothing in it points back at what is missing.

## How To Do It

1. **Recover the decision list, not the rule list.** Before comparing anything, assemble the set of original decisions the rules were meant to encode — each one as a standalone statement of intent with its reason. Pull these from the authoritative source (original specs, review notes, issue history, prior approvals), not from the rules themselves. Rules are an implementation of decisions; auditing rules against rules only proves the copy was faithful to a possibly-wrong original.

2. **Walk the decision list one item at a time.** For each decision, ask three separate questions:
   - Is it represented in the new set at all?
   - Is it represented at the same strictness — not looser, and importantly not tighter?
   - Does it still mean the same thing given the new context's defaults and surrounding behavior?

   Record an explicit verdict per decision. An unexamined decision must be visibly unexamined, not absent.

3. **Treat tightening as a defect, equal to loosening.** Reviewers instinctively hunt for weakened constraints and wave through stricter ones. A rule that became stricter in transit is an unapproved change: it rejects cases someone deliberately chose to allow, and it will surface later as an unexplained failure with no owner.

4. **Diff in the direction that reveals omissions.** Comparing new-to-old shows what was added or altered. Comparing old-to-new shows what disappeared. Omissions are the most expensive class of drift and only the second direction finds them, so make old-to-new the mandatory pass.

5. **Re-derive context-dependent rules instead of translating them.** Any rule whose effect depends on its surroundings — ordering, inherited defaults, fallbacks, units, scope of application — cannot be checked by comparing text. Reconstruct what it does in the new context from scratch and compare behavior to the original decision's intent.

6. **Leave the audit behind as an artifact.** Produce a table mapping each original decision to its location and verdict in the new set. This is what makes the next port cheap: the following engineer inherits the decision list rather than reverse-engineering it from rules again.

## When To Apply

Run this whenever two rulesets merge, whenever one is copied into a new lane, whenever a ruleset is reimplemented on a different mechanism, and whenever rules move between environments with different defaults. The trigger is the act of copying, not the apparent size of the change — small ports drift as readily as large ones and get audited less.

## Why It Works

Rules are lossy encodings of decisions. Copying preserves the encoding while quietly changing what the encoding resolves to, and it cannot preserve anything that was dropped. Auditing against the decisions rather than the prior rules restores the information the copy could not carry.

## Cost Note

A full decision-by-decision walk is slower than a text diff and this is the point of friction where the practice gets skipped. Scope it by auditing every decision once, at port time, rather than sampling; the sampled subset reliably excludes the omission, which is the finding that justified the audit.
