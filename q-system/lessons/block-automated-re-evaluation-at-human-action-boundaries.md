---
id: block-automated-re-evaluation-at-human-action-boundaries
kind: pattern
title: Block Automated Re-Evaluation at Human-Action Boundaries
date: 2026-11-01
---

When an automated loop re-checks a goal at the end of every turn, a goal whose next step requires a human-only action (granting a credential, approving a charge, flipping an access flag) cannot advance on its own. The checker keeps firing, the agent keeps restating the same blocked status, and the loop burns turns for as long as the human is unavailable.

HOW to implement the boundary marker:

1. Classify blockers. At the point where work stalls, decide whether the blocker is self-resolvable (retry, alternate path, different input) or requires an external principal. Only the second class gets a marker; otherwise you will mask real bugs.

2. Write a boundary marker when the blocker is external. Persist a small structured record outside the turn's memory containing: the exact command or action the human must perform, the precise identifier they must supply or approve, the reason it cannot be self-served, and a creation timestamp. Vagueness here is what forces a second round trip, so record the literal invocation, not a description of it.

3. Teach the checker three states instead of two. Extend the goal evaluator from satisfied/unsatisfied to satisfied, unsatisfied, and satisfied-pending-external. On a live marker it returns satisfied-pending, exits with a success status, and emits no feedback, so the loop does not re-trigger. Unsatisfied still triggers normally.

4. Define marker clearance explicitly. The marker is removed when the external action is confirmed (presence of the credential, a success probe against the gated operation, or an explicit clear command), never by the checker itself or by elapsed time alone. Optionally stamp a staleness horizon that converts the marker into a loud failure rather than silently resuming re-fire.

5. End the turn with the minimum the human needs: one line stating what is blocked and one line giving the exact action. Suppress all other restatement so a returning human sees a single actionable item instead of a wall of identical status updates.

6. Test both edges. Plant a marker and assert the checker exits zero and produces no feedback. Clear the marker and assert the checker fires again on the still-unsatisfied goal. Add a case for a malformed or partial marker and assert it is treated as unsatisfied rather than as a permanent mute.

7. Make the condition observable. Count re-evaluations per goal and alert when the same goal produces an identical blocked message more than a small number of times; that pattern is the signature of a missing boundary marker and is how you find the next one.
