---
id: scope-approval-to-the-artifact-not-the-plan
kind: pattern
title: Scope Approval to the Artifact, Not the Plan
date: 2026-11-06
---

**Pattern: approval is scoped to the exact artifact shown, never to the plan it came from.**

When work moves through stages — an outline, then a draft, then an executed action — each stage needs its own approval. A yes at an earlier stage is consent to *that* stage's content only. Carrying it forward silently converts "this direction looks right" into "ship this exact output," and the gap is invisible until the output is already live.

**How to apply it**

1. **Name the approval object explicitly.** When you request a yes, state what is being approved in a form the approver can point at: "approve this list of planned items" versus "approve these three finished items as written." Never ask an unqualified "looks good?"
2. **Disambiguate on receipt, not on use.** If a yes arrives and more than one artifact is in play, ask which one before acting: "confirming — is that approval of the plan, or of the drafts I sent after it?" Ask at the moment of ambiguity; by the time you are executing, asking costs more than it saves.
3. **Treat stage transitions as approval-invalidating.** The moment a concrete artifact exists that did not exist when approval was given, the prior approval no longer covers the irreversible step. Re-request.
4. **Gate the irreversible step on artifact-level consent.** Queuing, publishing, sending, merging, or deploying requires a yes that referenced the exact bytes going out. Plan-level consent authorizes drafting, not release.
5. **Record what was shown.** Keep the approved artifact alongside the approval so "approved" can be verified against content rather than recalled from memory. If you cannot point to what was on screen when the yes was given, you do not have an approval for it.

**Boundary condition**

This only binds once a concrete artifact exists. Approving a direction, a scope, or a set of intentions before anything concrete is produced is a legitimate and sufficient approval for proceeding to produce it. The rule is not "approve more often" — it is "do not let consent migrate across a stage boundary it was never given at."

**Failure signature to watch for**

A count mismatch is the tell: approval was given for N planned items, and N finished items now exist, so the numbers line up and the substitution feels safe. Matching counts are not matching artifacts.
