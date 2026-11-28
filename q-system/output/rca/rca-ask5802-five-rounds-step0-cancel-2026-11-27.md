# RCA: ASK-5802 step 0 ran five review rounds on one finding class across PR #893, #899 and #903

**Date:** 2026-11-27
**Trigger:** pr-review-agent.sh round 4 on PR #903 (head 70c2c4a3): REQUEST CHANGES, one major, the same class as every major since PR #893 round 1. Review cap reached; a fresh Sana agent takes over (iteration-speed.md rule 6).
**Surface-fix commit:** 70c2c4a3 (identity-only stop; the round 4 review refutes it)
**Structural-fix commit:** pending (this rung: step 0 labels, it never cancels)

## What happened

Step 0 asks "should this ticket exist" before the worker builds it. Since PR #893 a stop ended in cap-ladder.py rung 0 canceling the Linear ticket and closing its PR, unattended. Every round after that tuned which titles stop. Round by round the matcher was a phrase key, then a build verb, then a verb minus "to/into/onto", then "the title names the cited file". Every version canceled some real ticket. Round 4 showed the newest one cancels "morning-brief.py crashes on an empty ledger" and "add Y to review-tier.py".

## Surface symptom

`~/.config/kipi/pr-reviews/assafkip_kipi-system__pr-903-20261127-143639.md`:

```
major|Step 0 dropped the build-verb test, so broken-thing reports and "add Y to <cited file>" enhancements are canceled unattended whenever the title names one of the six cited files|q-system/.q-system/scripts/ticket_step0.py:113
```

Repro in that review: six real-shaped bug titles give `exit=3 decision=stop` on 70c2c4a3 and `exit=0` on 9a0b8c6a.

## Surface root cause

`ticket_step0.py` `title_names_cited_file()` stops on any title that contains a cited file's name. The repo's own title convention is `<script>: do X` and `<script>.py crashes on Y`, so naming the file is the normal shape of a bug or an enhancement, not of a duplicate build.

## Structural root cause

### Root cause #1
type: design-defect

An irreversible unattended action (cancel the ticket, close the PR) is gated on a text matcher over free English. A matcher has false positives at any setting. With a reversible action a false positive costs a click; with an irreversible one it costs live work. So every precision fix only moves the false positives to a new phrasing, and the reviewer finds them each round. Five rounds tuned the matcher. None changed the action, which was the lever.

### Root cause #2
type: process

The two earlier RCAs both named the matcher as the problem and prescribed a better matcher (rca-ask5802-three-rounds-2026-11-27.md: route the cancel through one CLOSE; rca-pr899-step0-precision-three-rounds-2026-11-27.md: "key the stop on file identity"). Neither asked whether the stop had to be a cancel. The round 3 review on #899 and round 4 on #903 both said it in their process notes: make the outcome non-destructive. That advice arrived twice before it was taken.

### Root cause #3
type: test-gap

The fixture list of "must pass" titles named files that were not the cited file. So the identity-only rule passed every fixture while it regressed the round 1 and round 2 cases. The fixtures tested the old rule's boundary, not the new one's.

## Verification

- Ran: `python3 -I bugreports.py` against 70c2c4a3 and 9a0b8c6a in the round 4 review. Got: 6 of 6 bug titles stop on 70c2c4a3, 0 of 6 on 9a0b8c6a. The newest matcher is less precise on this class than the one before it.
- The real board, measured by the previous agent: 0 of 2,999 open tickets stop. The harm is in tickets not yet filed, so a better matcher cannot be shown safe on today's data either.
- **Known-answer case:** in that same review, 70c2c4a3 stops `morning-brief.py crashes on an empty ledger` (exit 3). That is the false stop the round named, so the repro does fire.
- After this rung, the check that holds the design: a stop adds the label `step0:already-built` and a comment and never calls a cancel. test_ticket_step0.py, test-worker-step0.sh and test_cap_ladder.py pin that no `state canceled` op and no PR close happen on a step-0 match.

## Contributing factors

- The KNOWN_BUILT keys in improve_ground.py are hints written for pasted outside ideas, not cancel criteria (ASK-5805 owns their precision).
- `live()` keyed on a fixed list of writer scripts and missed `kipi review <n> ... --issue ASK-n` (round 4 minor 2).
- The docstring "Measured 2026-11-27" block kept describing a rule that had been replaced (round 4 minor 3).

## Fixes shipped

- 70c2c4a3 kept: writer-only `live()` keyed by PID, the own-chain filter, `pending_close` so a failed CLOSE retries as decided. The round 4 review confirmed each.

## Action items

- [ ] Sana, this rung on ASK-5802: step 0 never cancels and never closes a PR. A KNOWN_BUILT match adds `step0:already-built` and one comment naming the cited file; the worker's ready() skips the label; cap-ladder rung 0 does the same and spends no rung. Removing the label lets the ticket through (ledger flag `step0_labelled`). Tests: match labels and does not cancel, removed label passes, no match passes, 1 mutant per decision point.
- [ ] Sana, same rung: `live()` counts `kipi review ... --issue ASK-n`; the docstring states the new rule.
- [ ] ASK-5805 (fleet worker): first-key masking and key precision in improve_ground.py. Advisory only now, since nothing irreversible rides on it.

## Lessons

- When an unattended action is irreversible and its trigger is a text match, change the action before tuning the match. A reversible label with a named consumer makes any false positive cheap.
- When a reviewer's process note names the structural move twice, that is the finding. Take it in the next commit.
