# RCA: PR #693 round 4 failed after the round-3 RCA, on the same class

**Date:** 2026-11-09
**Trigger:** round 4 of the fleet reviewer on kipi-system PR #693 (ASK-4099) was REQUEST CHANGES at head 5160fe29, delta 4a412268..5160fe29. That is past the 3-round cap, so per iteration-speed rule 6 a fresh Sana agent (sana-4099c) writes this before round 5.
**Author:** sana-4099c.
**Inputs read:** the round-4 review (`~/.config/kipi/pr-reviews/assafkip_kipi-system__pr-693-20261108-192137.md`), the round 1 to 3 reviews in the same folder, the round-3 RCA on this branch (`rca-pr-owner-update-branch-three-rounds-2026-11-09.md`), and sana-4099b's handoff comment on ASK-4099 (2026-11-09 03:32Z).

## What happened

The round-3 RCA named two root causes. #1: a failed write of pr-owner's own was routed into the red table, whose end is a close. #2: tests were built from each finding's one input, not the input class. Round 4 (sana-4099b) fixed #1 for every write. It held them, filed one alert per PR and head, and asked them again. Round 4's reviewer confirmed that fix for every gh write. The same review then found three defects, all inside the new "held" machinery for Linear:

| # | Severity | Finding | Reviewer's reproducer |
|---|---|---|---|
| 1 | major | A rework whose requeue fails while its progress note posts re-posts that note every hour. The 48h close is unreachable. | 6 hourly runs: 6 progress notes, 6 requeues, strike `noted: false`. At parent 4a412268 the same input gives 1 note. |
| 2 | minor | The held alert is deduped on PR + head, whatever write failed. A second, different failure at that head files nothing. | update fails (alert on ASK-9001), merge fails at the same head: "is filed at this head already". |
| 3 | minor | The docstring says a note Linear does not take is asked again. On the close path it never is. The alert says "its close-requeue did not take" when the close took. | Close with Linear refusing every write: the note is tried once and dropped. |

## Surface symptom

Finding 1 is a regression on a live path. Main posts that note once. 5160fe29 posts it every hour, and Linear comments cannot be deleted. The producer is live today: any red `sana/` PR whose ticket is started and whose requeue Linear refuses (422 on a state move) while comments still post.

## Surface root cause

`ticket_note()` returns one bool for two Linear writes: `return not lost, lost + "note posted"`. When the requeue fails and the note posts, that bool is `False`. Round 4 stored it as `strike["noted"]`, and `decide()` reads `noted is False` as "the note did not land, ask it again". It is read before the 48h age check, so the close ladder is unreachable.

## Structural root cause

### Root cause #1
type: other (a return value got a second reader that changed its meaning)

At 4a412268, `ticket_note()`'s bool had one reader: the run's exit code. "False" meant "this run had a failure", and for that reader a failed requeue is a failure. Round 4 gave the same bool a second reader, `strike.noted`, which needs "did the resume line land". The producer was not changed, so one value now carried two questions. When the requeue fails and the note posts, the two answers differ (failure: yes; note landed: yes) and the bool can only hold one.

Evidence:
- `git show 4a412268:.../pr-owner.py` line 1173: `noted, what = ticket_note(ticket, line); return noted, ...`. The bool goes to the exit code only.
- 5160fe29 line 1252: `noted, what = ticket_note(ticket, line); if noted: strike.update({... "noted": True})`. The same bool is now state that `decide()` reads at line 1011.

All three findings have this shape: one action was modelled as one write.
- A rework is three writes: the PR comment, the requeue, and the note. A requeue that moves posts the resume line itself, so it is the note too.
- A close-requeue is three writes: the close, the requeue, and the note.
- Finding 1: two Linear writes, one bool.
- Finding 2: the alert key is the PR, not the write that failed.
- Finding 3: the docstring gives every write one property ("asked again"), but the close path's note cannot have it. The PR is closed, so it leaves the open list and is never decided again.

### Root cause #2
type: missing-test

The round-3 RCA's lesson was "a failure, a permanent failure and a recovery for each write". Round 4 applied it per action, not per write. G4 (test-pr-owner-contract.py at 5160fe29, line 1343) sets `LS_RC` with both `requeue` and `progress` failing. That is one point of a four-point class: requeue fails alone, note fails alone, both fail, both land. The asymmetric points were never run. sana-4099b's handoff says the same: "the round-4 tests were built from the input I chose (both Linear halves fail), not from the input class". The lesson was written down and still not applied, because "each write" was never listed. Nothing forced the writes to be enumerated before the tests were written.

## Verification

Red rows written first (scenario H, test-pr-owner-contract.py), run against the unchanged pr-owner.py at 5160fe29:

```
$ python3 q-system/.q-system/scripts/test/test-pr-owner-contract.py
FAIL [P53] a requeue that fails while its note posts: ... got (1, 6, 6, [2, 2, 2, 2, 2, 2], 1, (False, 1794171600)),
     want (1, 1, 1, [2, 0, 0, 0, 0, 0], 1, (True, 1794171600))
FAIL [P53] ... so the close ladder is reachable: open at hour 47, closed at hour 49: got ([], []), want ([], ['close'])
FAIL [P53] both halves fail, then the note posts while the requeue still fails, then Linear recovers: ...
FAIL [P52] ... one alert per failed write: ... got [1, 0, 0, 0, 0], want [1, 1, 0, 0, 0]
FAIL [P52] a review that crashes, then a rework comment GitHub refuses, at one head: ... got ([1, 0, 0], ...), want ([1, 1, 0], ...)
FAIL [P52] one rework at one head: the comment fails, then the requeue fails: ... got ([1, 0, 0], [2, 2, 2]), want ([1, 1, 0], [2, 2, 0])
FAIL [P54] a close whose note does not land: ... carrying the resume line ...: got (..., False, ...), want (..., True, ...)
FAIL [P54] ... the alert names the write that did not take (the note), not the close: got (True, False), want (False, True)
54 promises, 162 assertions
FAIL: 10 check(s)
```

This reproduces finding 1 exactly as the reviewer measured it: 6 notes and 6 requeues in 6 hours, and the strike stuck at `noted: false`. Finding 2 is reproduced on three chains (H2, H5, H6), finding 3 on H7. Two class rows pass on the old code (a Backlog ticket's note alone, and a requeue that moves). Those paths were already right, and the rows are kept to guard them.

One row was blind on the first try. H2 counted `progress` calls only and passed on the old code: at hour 2 the old code asked again and the now-working requeue posted the resume line itself. That is a second note, and the row did not count it. The row now lists every Linear write per hour. This is root cause #1 again, in a test: a requeue that moves is a note.

## Contributing factors

- New state late in a capped cycle. Round 4 added `strike.noted` and the `held` map in round 4 of a 3-round cap. The new state is where all three findings live.
- The round-4 reviewer's process note: three rounds went to update-branch, a path with no live producer (no fleet repo has strict protection, so BEHIND is never emitted). The live path, a red `sana/` PR whose Linear note half-fails, took the regression.

## Fixes (the next commit on this branch)

sana-4099c ships these on sana/ask-4099 in the commit after this one, before round 5:
- Surface fix: `ticket_note()` returns `(requeued, noted, what)`. The 48h start once `noted` is true. A requeue that failed while its note landed counts one failure, so the run exits 2 and one alert is filed. It is never asked again, because each ask would post the note again.
- Structural fix: each write gets its own result and its own alert. `act()` names the write that did not take (merge, update-branch, review, comment, close, requeue, note, or "requeue and note"). `held_alert()` dedups on PR, head, action and that write. A second different failure at one head files its own alert, and a retry of the same failure files none.
- Finding 3: the docstring now lists what is asked again and what is not. The note after a close is not, since a closed PR leaves the open list. That alert names the ticket, carries the resume line, and names the write that did not take.
- Tests built from the class, listed before they were written: scenario H in test-pr-owner-contract.py. Requeue fails alone, the note fails alone, both fail then recover, the requeue moves, two failed writes across actions at one head, two failed writes within one action, and a close whose note fails.

## Action items

- [ ] `ticket_note()` returns the requeue and the note as two results; the 48h start on the note. Red first: H1 and H2 fail on 5160fe29. Owner: sana-4099c. Type: code + test
- [ ] Held alert keyed per PR, head, action and failed write. Red first: H2, H5 and H6 fail on 5160fe29. Owner: sana-4099c. Type: code + test
- [ ] Docstring true for the close path; the alert carries the resume line and names the failed write. Red first: H7 fails on 5160fe29. Owner: sana-4099c. Type: doc + code + test
- [ ] Negative self-test: a mutant that restores `return not lost` (one bool) turns H1 red. Owner: sana-4099c. Type: test
- [ ] Round 5, delta only, `KIPI_REVIEW_MAX_ROUNDS=5`, from the pinned checkout. Owner: sana-4099c, after the PR comment. Type: process
- [ ] On APPROVE at the head with validate green: merge pinned to that head commit, reinstall com.kipi.pr-owner from a fresh origin/main tree, dry run, kickstart, read the log. Owner: sana-4099c. Type: process

## Lessons

- When a value gets a new reader, check that it still means one thing. A bool that meant "the run failed" cannot also mean "the note landed".
- "For each write" means list the writes first. A rework is three writes, not one. Enumerate them in the test file's comment before writing a row, and give each one its own failure, recovery and mixed rows.
