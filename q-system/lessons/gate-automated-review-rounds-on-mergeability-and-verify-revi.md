---
id: gate-automated-review-rounds-on-mergeability-and-verify-revi
kind: methodology
title: Gate automated review rounds on mergeability and verify reviewer-suggested fixes
date: 2026-11-09
---

When an automated or semi-automated review loop has a fixed cap on rounds, three failure modes can combine so that an approved change cannot be merged and no rounds are left.

1. Check mergeability before spending a review round. If the loop reviews a head that conflicts with its target branch, any approval of that head is worthless: resolving the conflict produces a new head, and the approval does not carry over. Before each round, query the change's merge state (conflicted, behind, blocked by checks). If it is not mergeable, rebase or resolve first, or stop and report. Do not run a review that can only produce an unusable approval. A conflicted head should not count against the cap.

2. Make the interaction between the round cap and your follow-up rules explicit. If the cap counts every round, including approvals, and another rule says every minor finding attached to an approval must be fixed or explicitly rejected, then an approval in the final round leaves an unstated contract: any further fix has to go through the escalation or override path. Write this down where both rules live. Better, design the cap so it counts only rounds that request changes, or reserve one round for applying fixes after an approval. Review your process rules in pairs and look for combinations that leave no legal next step.

3. Verify a reviewer's suggested fix against the real producer before applying it. A reviewer may propose treating a signal as a benign fact, such as 'no record found' or 'missing data', and changing behavior on that basis. Before you adopt the reviewer's fix shape, read the code that produces the signal and find every consumer of it. Check whether the producer is documented to fail closed, and whether a non-zero exit or error status already triggers alerts elsewhere. Reinterpreting a fail-closed error as a normal empty result silently inverts the safety behavior. The reviewer's next round may catch it, but that costs a round you may not have.

Checklist for capped review loops:
- Gate each round on a mergeable head.
- Exclude rounds lost to an unmergeable head from the cap, or fail fast on them.
- Document how the cap interacts with rules that require post-approval fixes.
- Treat reviewer fix suggestions as hypotheses, and confirm them against the producer's contract and its downstream consumers before applying them.
