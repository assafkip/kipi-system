# RCA: PR #893 (ASK-5802 step 0) hit the 3-round review cap with REQUEST CHANGES every round

**Date:** 2026-11-27
**Trigger:** pr-review-agent.sh round 3 verdict REQUEST CHANGES on PR #893; cap-ladder rung 1 closed it, opened PR #899, and its rung 1 RCA came back empty (known failure ASK-5322).
**Surface-fix commit:** pending
**Structural-fix commit:** pending

## What happened

ASK-5802 adds step 0: improve_ground decides whether a ticket should exist before the worker builds it and before cap-ladder rung 1. The decision itself (`ticket_step0.py`) was sound by round 2. What failed review three times was the action taken on a stop. The cancel was written as new code inside `rung_zero`, and a new `--rung0` entry point ran it outside the nightly loop. Every round found a new partial-failure or guard gap in that hand-built cancel.

## Surface symptom

Round 3 findings (`~/.config/kipi/pr-reviews/assafkip_kipi-system__pr-893-20261127-021012.md`):

```
major|--rung0 skips the nightly loop's lane_hold and live() guards ... closes a lane's own PR on sana/<id> and cancels the ticket|cap-ladder.py:1147
major|Rung 0 closes the lane PR before posting the reason ...|cap-ladder.py:1112|nonblocking
major|The reason comment is posted before the cancel with no dedupe ...|cap-ladder.py:1116|nonblocking
minor|step0_canceled is claimed once and no production code ever clears it|cap-ladder.py:1121
minor|A step-0 release ... still counts toward --limit|cap-ladder.py:1078
```

Round 2 (`...pr-893-20261127-013628.md`) had already found three findings on the same four-line write sequence: dropped progress rc, PR left open, lock message.

## Surface root cause

`cap-ladder.py` at 2a4207b8:

- `rung_zero` lines 1111-1122 call `close_pr`, `run(SYNC progress)`, `lin("state", canceled)`, `claim-flag`, `clear_caps` directly. The ladder already has this exact sequence in `apply_decision`'s CLOSE branch (lines 957-991), used by rung 4.
- `rung0_now` lines 1127-1163 is a second loop over one issue. It checks `owned_open` and `find_caps` only. The nightly loop in `main()` (lines 1351-1388) also checks the 20-hour handled memory, DEAD_TYPES, the dispatch slug, `lane_hold` (ASK-4395) and `live()`. `--rung0` had none of those.

## Structural root cause

### Root cause #1
type: code-defect

A parallel path. The ladder has one CLOSE (`apply_decision`) and one guarded loop (`main`). Step 0 added a second CLOSE and a second loop. Each round's fix patched the copy (reorder the writes, add an rc check, add a PR close), and each patch created a new partial-failure state the reviewer then found. The guards the copy lacked are the ones the original loop collected over ASK-4395 and earlier scars. Copying the action without copying its guards is the defect class; rounds 2 and 3 are the same class.

### Root cause #2
type: process

The fix was reviewed line by line, not as a sequence. Round 3's reviewer said it directly: "on a multi-write sequence, review the sequence, not the lines." The author answered each finding with a local patch instead of asking why the sequence existed twice. The `--rung0` path was added in round 2 to remove the 04:40 wait (founder ruling 2026-11-27), which was right in goal but was built as a new entry point instead of a filter on the existing one.

### Root cause #3
type: missing-test

The tests for rung 0 asserted on `writes(env)` and the ledger, never on the `gh` log, and no test ran `--rung0` against a live lane marker or a live run. So the guard gap was invisible to the green suite.

## Verification

Claim checked against code, not taken from the diagnosis comment:

- Ran `sed -n 954,991p cap-ladder.py`: `apply_decision` CLOSE = `close_pr` (if pr) then `lin state canceled` then progress then `clear_caps`. Ran `sed -n 1088,1163p`: `rung_zero` repeats it in another order, `rung0_now` has no `lane_hold`/`live` call. Confirmed.
- Round 3's own repro (`g1.py`): nightly path with a lane marker wrote `[]` to Linear; `--rung0` on the same state closed PR #10 and canceled ASK-1. Confirmed by the review log.

Fix verification is recorded on PR #899: the red tests listed under Action items, then green.

## Contributing factors

- The founder's no-wait ruling (2026-11-27) arrived mid-PR and was met with a new flag in the same round as other fixes.
- Rung 1 RCA came back empty (ASK-5322), so the ladder supplied no diagnosis; the previous agent's Linear comment was the only one.

## Fixes shipped

- Pending on PR #899 (branch `sana/ask-5802`): rung 0 as a decision, the cancel through `apply_decision`, `--issue` in place of `--rung0`.

## Action items

- [ ] Sana (PR #899): `rung_zero` decides only; it returns a CLOSE decision or a release verdict, and writes nothing to Linear or GitHub.
- [ ] Sana (PR #899): the cancel goes through `apply_decision` CLOSE in `climb()`, with the step-0 reason as the comment.
- [ ] Sana (PR #899): drop `--rung0`; add `--issue` to `main()` so the worker runs the same guarded loop for one ticket now. Red test: a live lane marker and a live run both stop `--issue` from closing the PR.
- [ ] Sana (PR #899): a step-0 release does not count toward `--limit`; `step0_canceled` is cleared when step 0 passes again.

## Lessons

- A second caller of a guarded action calls the guarded action. It never re-implements it; the guards are part of the action.
- Removing a clock wait means running the same loop earlier, not building a second loop.
