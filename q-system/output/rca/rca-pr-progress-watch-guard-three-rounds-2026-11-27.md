# RCA: PR 904 (ASK-5842) hit the 3-round cap with its guard regex still wrong

**Date:** 2026-11-27
**Trigger:** review round 3 on PR 904 returned REQUEST CHANGES with one major finding, at the cap
**Surface-fix commit:** pending (one character class, below)
**Structural-fix commit:** pending

## What happened

PR 904 adds `pr-progress-watch.sh` (a PR watcher that wakes on a stall) and `pr-progress-watch-guard.py` (a PreToolUse Bash guard that refuses a `gh pr view` plus `sleep` loop). Three review rounds ran. Rounds 1 and 2 each found a real defect in the guard's loop regex, and the round 2 fix introduced the round 3 defect. The cap stopped the PR with `kipi/reviewer-approved=failure` on head 895cc13a.

## Surface symptom

Round 3 finding, run through the guard's real entry point:

```
exit 0 -> ALLOWED | for ((i=0; i<60; i++)); do gh pr view 904 --json state; sleep 60; done
exit 0 -> ALLOWED | while s=$(gh pr view 904 --json state); [ x ]; do ... sleep ...; done
exit 2 -> blocked | while true; do gh pr view 903 --json state; sleep 300; done
```

Both allowed shapes were refused at the sha reviewed in round 2.

## Surface root cause

`LOOP_RE` in `pr-progress-watch-guard.py:37` is `\b(while|until|for)\b[^;]*?[;\n]\s*do\b`. The `[^;]` class cannot cross a semicolon, so the first `;` after the loop word must be the one before `do`. A C-style `for` header or a `while cmd; test; do` header has an earlier `;` and no longer matches.

## Structural root cause

### Root cause #1

The regex was edited three times (`\b(while|until|for)\b`, then `[^\n]*?\bdo\b`, then `[^;]*?[;\n]\s*do\b`) and each time tested only against the shape the previous review had named. The suite had no table of loop headers, so no edit was measured against the whole set of shapes the guard exists to refuse.

type: missing-test

### Root cause #2

The guard's contract ("refuse any shell loop that polls a PR with a sleep") was held as a regex over free text. Each fix to one false positive or false negative moved the boundary and nothing pinned the rest of it. Three rounds on one regex is the signature of a property enforced by a pattern that has no reference set.

type: implicit-contract

## Verification

Reviewer round 3 ran the old and new regex on the same strings and proposed the fix `\b(while|until|for)\b[^\n]*?[;\n]\s*do\b`, with these results on 8 shapes: C-style for, while-list, one-line loop, multi-line while, multi-line for all match; the English `for` one-shot, a plain `gh pr view` and `sleep; echo` do not match. This RCA did not run that fix. It is the first action below, and the fresh agent must run it before trusting it.

## Contributing factors

- Review rounds read the delta from round 2 on (founder rule), so a regression against shapes reviewed in round 1 only surfaced because the reviewer re-ran old inputs. The author did not.
- The test file's guard cases were written as 1 block and 1 allow plus mutants for decision points, which is what the ticket asked for. A regex that classifies free text needs a table, not 2 cases.
- Rounds 1 and 2 each also had real watcher defects (stderr folded into JSON, reason order, empty args), so the guard regex got one fix per round instead of a design pass.

## Fixes shipped

- Surface fix: pending. Change `[^;]*?` to `[^\n]*?` in `LOOP_RE`.
- Structural fix: pending. Replace the 2-case guard test with a table of loop shapes (one-line, multi-line, C-style for, while with a condition list, until, English prose, plain call, sleep with no gh), each with its expected exit, and make every regex edit run the whole table.

## Action items

- [ ] Fresh Sana agent: apply `[^\n]*?[;\n]\s*do\b` to `LOOP_RE`, run the table test, push to sana/ask-5842, request one delta review on the new head — owner: fresh Sana agent on ASK-5842 — type: code
- [ ] Add the loop-shape table test (at least 8 shapes, expected exit each) to `test_pr_progress_watch.py` before the regex change, show it red on head 895cc13a, then green — owner: fresh Sana agent on ASK-5842 — type: test
- [ ] Correct the comment at `pr-progress-watch-guard.py:35` so it describes the regex that ships — owner: fresh Sana agent on ASK-5842 — type: doc
- [ ] After merge, run `bash q-system/.q-system/scripts/pr-progress-watch.sh <open pr> --stall-min 1 --deadline-min 2` against a real open PR once to prove the live `gh` JSON shape — owner: fresh Sana agent on ASK-5842 — type: process

## Lessons

- A regex that classifies free text needs a reference table of shapes before the first edit, not a case per review finding.
- When a fix changes a pattern, re-run every input any earlier round named, not only the new one.
- Three rounds on one pattern means design the table first; the fix is then one line.
