---
id: rewrite-rule-sets-whole-don-t-stack-patches
kind: methodology
title: Rewrite Rule Sets Whole, Don't Stack Patches
date: 2026-11-06
---

## When to use
Apply when a set of written rules, constraints, or instructions has accumulated feedback across multiple rounds and is starting to read as a pile of patches rather than a coherent whole.

## How
1. Stop editing incrementally. Before touching the text, collect the complete feedback history — every round of correction, not just the latest one. Without the full history you cannot tell which existing rule each piece of feedback is actually about.
2. Map each piece of feedback onto an existing rule. For every item, identify which current line it modifies, contradicts, or refines. Feedback that seems to need a new rule is usually a sharper statement of an old one.
3. Rewrite in place. Edit the existing lines so each one absorbs the feedback aimed at it. Hold the line count fixed as a working constraint; if you cannot express a correction without adding a line, that is a signal two rules are tangled and should be re-split, not appended to.
4. Read the result end to end as a single document. The test is whether it sounds like one authored set, not a changelog with sediment layers.
5. Replace the old version wholesale rather than shipping a diff of additions.

## Why
Appended rules carry their history in their structure: later lines exist to qualify earlier ones, so readers must reconstruct the argument's chronology to apply the set correctly. Rewriting in place collapses that chronology into the current intent. Fixing the line count forces consolidation instead of accretion, which is what keeps the set readable as it matures.

## Limits
This only works with the full feedback history in hand. A single mid-stream correction, applied before later rounds arrive, has no choice but to stack — you lack the information to know which rule it truly belongs to. Treat mid-stream additions as temporary and schedule a whole rewrite once the feedback stream settles. Also avoid whole rewrites when the rule set is under concurrent edit by others, or when its revision trail must be auditable; in those cases, patch and consolidate at a planned checkpoint instead.
