---
id: carry-basis-and-scope-across-every-aggregation-boundary
kind: pattern
title: Carry basis and scope across every aggregation boundary
date: 2026-07-06
---

## The failure mode

When one layer computes aggregates and hands them to another layer that renders or acts on them, the aggregation step quietly discards two things the downstream layer needs to stay truthful:

1. **Per-item basis** — the reason each item was counted, its "for what." Collapsing N items into a total deletes why each one qualified.
2. **Cross-group links and scope** — which groups describe the same population, and at what granularity. Disjoint groups arrive with no join key and no scope tag.

A payload assembled as a flat bag of independently-computed aggregates — no links between groups, no provenance inside any group — forces the consumer to invent justification it does not have. The output is confident but baseless: a count with no reason, a recommendation whose precondition was silently dropped, two numbers compared across mismatched scopes.

## Why it's structural, not sloppiness

The consumer is faithfully rendering a fact that was already broken upstream. Rewording the consumer fixes nothing — the missing data was never in its hands. The defect lives in the shape of the handoff, so that's the only place a fix holds.

## How to prevent it

- **Treat the handoff payload as a contract, not a dump.** Enumerate what the consumer must be able to justify, and require every such claim to arrive with its basis attached.
- **Aggregate without discarding basis.** When you collapse N items into a count, carry the breakdown that explains the count (a per-reason tally), not just the total.
- **Tag every group with its scope and granularity** — which population it covers, at what level — so the consumer can tell whether two numbers are comparable before it compares them.
- **Link groups that describe the same entities.** Never hand over disjoint groups the consumer is expected to reconcile with no shared key.
- **Carry preconditions for downstream actions.** If a recommendation can only run when a field is present, ship the presence signal so the consumer suppresses the action instead of recommending something that can't execute.
- **Guard the boundary with a test.** Assert that every renderable claim traces to a field in the payload. A claim with no backing field is the bug — caught at the seam, before it reaches a reader.

## The one line

Every number a downstream layer will print or act on must arrive carrying its basis and its scope; an aggregate that drops either is a defect the renderer cannot recover from.
