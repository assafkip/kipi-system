# RCA: PR #912 (ASK-5847) was approved at round 3 on a head that validate then failed, so the fix push sits past the review cap

**Date:** 2026-11-28
**Trigger:** validate run 46125461225 on head 44700899, after round 3 returned APPROVE WITH NITS. Reviews: `~/.config/kipi/pr-reviews/assafkip_kipi-system__pr-912-20261127-{232333,235257}.md` and the round-3 file.
**Surface-fix commit:** 03a8ccfe (on PR #912)
**Structural-fix commit:** pending (action items below)

## What happened

PR #912 changed linear-worker.sh in four places (Codex commit, no-verdict rounds, plan billing, timeout WIP). Three review rounds converged to APPROVE WITH NITS. The required `validate` check then went red on four neighbour suites that the change broke and that no local run covered. The fix needs a push, the push moves the head past the reviewed SHA, and the 3-round cap stops a fourth review, so the PR cannot merge on its own.

## Surface symptom

```
RED: test-failed rc=1: q-system/.q-system/scripts/test/test-severity-floor.sh
  FAIL: the rebased diff was not re-reviewed; a force-push nobody looked at ships under the OLD verdict
RED: test-failed rc=1: q-system/.q-system/scripts/test/test-worker-rework-prompt.sh
  FAIL codex prompt renders with an empty stderr
RED: test-failed rc=1: q-system/.q-system/scripts/test/test_cap_ladder.py
  FAIL worker: ladder_runner_for exists and the primary launch branches on it
RED: test-failed rc=1: q-system/.q-system/scripts/test/test-terminal-states.sh
  FAIL: REPRODUCER: a dead end added to kipi-dispatch.sh is CAUGHT as UNREGISTERED -- went RED but did not name the defect
```

## Surface root cause

- test-severity-floor read the ledger's `rounds` as proof a review ran; the PR made `rounds` count only verdict-writing runs, and that fixture's reviewer stub writes none.
- test-worker-rework-prompt renders the CODEX_PROMPT builder without the worker's functions; the PR put `$(codex_runner_note ...)` inside the builder string.
- test_cap_ladder.py pins the literal `if primary_run; then`; the PR split it into `primary_run; PRIMARY_RC=$?`.
- test-terminal-states: passes locally on the same branch (38/38); CI-only, not diagnosed at the time of writing.

## Structural root cause

### Root cause #1: the test budget picked neighbours by name, and 96 test files read linear-worker.sh

type: process

The brief allowed "the test files you touch, plus at most 1 neighbour". 96 test files name linear-worker.sh (measured 2026-11-28: `grep -rl linear-worker.sh q-system/.q-system/scripts/test q-system/.q-system/tests | wc -l` gave 96). Several pin literal lines of it. One neighbour by name cannot cover a file whose structure is pinned in 96 places, so the only full census was CI, which runs after the review rounds are spent.

### Root cause #2: the reviewer is shown a diff, never the required check

type: implicit-contract

Rounds 1 to 3 each reviewed the delta and returned findings about behaviour. None could see that validate was red, because validate takes about 18 minutes and the next round started before it finished. APPROVE landed on a head CI had not passed. The memory note "APPROVE is not a green check" (ASK-2036) records the same shape.

## Verification

- `bash q-system/.q-system/scripts/test/test-severity-floor.sh` on 03a8ccfe: rc=0.
- `bash q-system/.q-system/scripts/test/test-worker-rework-prompt.sh`: 20 passed, 0 failed.
- `python3 q-system/.q-system/scripts/test/test_cap_ladder.py`: the worker check passes; the only FAIL was the whole-file runtime bound (157s vs 120s) with test-severity-floor running beside it.
- CI on 03a8ccfe: see PR #912 checks.

## Contributing factors

- Literal-line pins (`if primary_run; then`) turn any refactor of a pinned line into a CI-only failure.
- The reviewer posts on a head before the required check finishes.

## Fixes shipped

- Surface fix: 03a8ccfe updates the three pins and moves the Codex note out of the builder string.
- Structural fix: pending.

## Action items

- [ ] Before the first review round of any linear-worker.sh change, run every suite that greps the lines the diff touches (find them with `grep -l` on each changed anchor), not one neighbour by name. owner: sana. type: process
- [ ] Start the review only after `validate` is green on the head, or have pr-review-agent.sh read statusCheckRollup and refuse APPROVE while a required check is red. owner: sana. type: gate
- [ ] Diagnose the CI-only test-terminal-states failure on PR #912 (passes locally). owner: sana. type: test
- [ ] PR #912 past the cap: cap-ladder.py takes it (its review cap marker is set). owner: cap-ladder.py. type: process

## Lessons

- A per-ticket test budget sized for a small file under-covers a 4600-line file that 96 test files read. Count the pins first.
- Three green review rounds say nothing about a required check that had not finished.
