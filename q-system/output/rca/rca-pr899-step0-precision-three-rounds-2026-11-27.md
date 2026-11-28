# RCA: PR #899 (ASK-5802 step 0) hit the 3-round cap on one finding class, step-0 precision

**Date:** 2026-11-27
**Trigger:** pr-review-agent.sh round 3 on PR #899 (head b125e486): REQUEST CHANGES, one major, the same class as the majors in rounds 1 and 2.
**Surface-fix commit:** b125e486 (the "to/into/onto" and "make" narrowing; the round 3 review refutes it)
**Structural-fix commit:** pending (the next ladder rung)

## What happened

PR #899 fixed the structural cause of #893's cap (rca-ask5802-three-rounds-2026-11-27.md): rung 0 now only decides, its cancel goes through `apply_decision` and `--issue` is a filter on the guarded loop. Rounds 1 to 3 accepted all of that. All three rounds also raised one major: step 0 cancels enhancement tickets unattended. Round 1 got it deferred to ASK-5805, round 2 raised it again, round 2's fix added a keyword carve-out, and round 3 broke that carve-out with the next phrasing.

## Surface symptom

`~/.config/kipi/pr-reviews/assafkip_kipi-system__pr-899-20261127-053337.md`:

```
major|Step 0 still cancels enhancement tickets unattended: the new carve-out keys on the literal word "to", so the same title with "for"/"in"/"so" is canceled while true duplicate builds containing "to" now pass|q-system/.q-system/scripts/ticket_step0.py:120
```

## Surface root cause

`ticket_step0.py` `build_proposal_of()` decides "this title proposes building file F" from free-text keywords: a `KNOWN_BUILT` phrase key (`deadman`, `handoff`, `morning brief`), a build verb at the start, and, since b125e486, no `to|into|onto` in the title. English has more ways to say "add Y to X" than a word list can hold.

## Structural root cause

### Root cause #1
type: code-defect

An unattended destructive action (Linear cancel plus PR close) is driven by a keyword classifier over free text. Precision then depends on the word list, and every round finds a phrasing the list misses. This is the "N patches = a single authority" pattern: the authority is a phrase list, so the fix arrives one phrase per round.

### Root cause #2
type: process

The finding was deferred to ASK-5805 in round 1 because the brief scoped precision out. A deferral the reviewer still rates blocking costs a round. Round 2 patched it locally instead of changing what the stop keys on.

## Verification

- Ran the five round-1 titles on the old and new rule: old rc=3 (stop), new rc=0. Round 3 then reproduced new false stops with "for/in/so" phrasings on b125e486. The patch moved the boundary and did not remove it.
- Real-ticket measurement, unchanged across rounds: step 0 stops 0 of 2,999 open tickets (the previous agent's count). So the risk lives in future tickets, not today's board.
- **Known-answer case:** `add risk-scored auto-merge for low-risk PRs` must stop, and does: rc=3 on b125e486 (run 2026-11-27). So the zero above comes from the board, not from a dead check.

## Contributing factors

- The KNOWN_BUILT keys are generic substrings. They were written to give the `/improve` skill a hint, and they were never sized to drive a cancel.
- All three suites share one STOP fixture (round 3 minor), so a rule that over-fits one title stays green.

## Fixes shipped

- b125e486 narrowed the stop. Round 3 shows the narrowing is incomplete.

## Action items

- [ ] Next ladder rung on ASK-5802 (cap-ladder rung 2, other runner): key the stop on FILE IDENTITY, not phrases. Stop only when the title names the cited file by path or stem (for example `review-tier.py` or `review-tier`) as the object of a build verb. A phrase-key match alone is advisory and never cancels. Red test first: the round 1 and round 3 titles must pass, and "add review-tier.py" must stop.
- [ ] Same rung: the round 3 minors (docstring states the real rule; a second STOP fixture; the unclosed-PR note when a round-cap marker survives; test_cap_ladder.py runtime, split the step-0 case).
- [ ] ASK-5805: first-key masking in improve_ground.py (fails open).

## Lessons

- An unattended destructive action needs an identity match, never a phrase match. Keywords are fine for advice and wrong for a cancel.
- A deferral the reviewer still calls blocking is not a deferral. Decide in the same round: fix structurally, or change the action so the finding no longer applies.
