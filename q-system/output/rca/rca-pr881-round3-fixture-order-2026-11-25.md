# RCA: PR #881 needed a third review round because a new test case broke the fixture the older fail-closed checks depend on

**Date:** 2026-11-25
**Trigger:** PR #881 (ASK-5705, branch ask-4969-dry-model-tracked-symlink) round 3 returned REQUEST CHANGES; the fix 4627960a landed after the 3-round cap, so no reviewer read it
**Surface-fix commit:** 4627960a
**Structural-fix commit:** none in code; process lesson below, the successor PR carries a full round-1 review

## What happened

Round 1 (APPROVE WITH NITS) and round 2 (APPROVE WITH NITS) raised minors. The round 2 fix added a new case to `test-kipi-update-dry-final-state.sh` that pins the post-rebase stand-in re-apply. That case committed a tracked `.claude` link to an outside directory into the shared `DIRECT_INSTANCE` fixture and never undid it. Round 3 found that every later dry run in the file then exited non-zero, so three later `if --dry-run; then fail` checks could not fail.

## Surface symptom

Reviewer A/B mutation, round 3 review: with the escaping-symlink refusal in the model walk turned into `continue`, the file at 2232fe5b printed `FAIL: dry run accepted a symlink that escapes the disposable model`, and at c0b925a6 printed `PASS: dry run is isolated, fail closed, and byte-equivalent to real state`. The guard this PR is built around could be deleted with the suite green.

## Surface root cause

The new case mutated a fixture shared with later cases (a tracked `.claude` link plus an advanced origin) and left it mutated. The checks after it are negative checks (fire only when a dry run succeeds), so a permanently failing dry run turned them vacuous.

## Structural root cause

### Root cause #1

The round 2 fix proved only its own mutant (delete the post-rebase re-apply, the new case goes red). It did not re-run the existing mutants of the file after adding a case to it. A test file whose later checks are negative checks needs its existing negative controls re-run whenever a case is inserted before them.

type: missing-test

### Root cause #2

The test file has one shared fixture and no per-case reset, so case order is part of its contract and nothing states it. Inserting a case in the middle is the natural edit, and it is the edit that breaks it.

type: implicit-contract

### Root cause #3

Round 2's minor about the tab-delimited stand-in map named only the key side. The fix took the finding's scope, so round 3 found the same delimiter class on the value side (a newline in the link target).

type: incomplete-spec

## Verification

Ran on head 4627960a, 2026-11-25, in the PR worktree:

- Refusal neutered (`kipi-update.sh` line 2704 `raise SystemExit(1)` -> `continue`), `bash q-system/.q-system/scripts/test/test-kipi-update-dry-final-state.sh`: `FAIL: dry run accepted a symlink that escapes the disposable model` (62 s). The control is red again.
- File restored with `git checkout -- kipi-update.sh`, same test: `PASS: dry run is isolated, fail closed, and byte-equivalent to real state` (66 s).

## Contributing factors

- Each test run is about 60 s here and the machine is short on swap, which pushes toward running one mutant per round instead of all of them.
- The cap closed the loop on the fix commit: 4627960a was never reviewed, so the PR could not merge on the reviewer status.

## Fixes shipped

- 4627960a: the tracked `.claude` case runs last in the file; `stood_in` refuses a link whose target holds a newline.
- Process: PR #881 is closed and its branch moves to a successor PR with a full round-1 review (first line `Resumes #881`, the form pr-review-agent.sh accepts; cap-ladder.py only takes `sana/ask-N` branches, so it would never pick this one up).

## Action items

- [x] Move the `.claude` stand-in case to the end of the file and re-run the neutered-refusal mutant (red) and the real run (green) — owner: sana — type: test
- [x] Refuse a newline in a stand-in link target — owner: sana — type: code
- [x] Successor PR from the same branch with a full round-1 review — owner: sana — type: process

## Lessons

- After adding a case to a test file that has negative checks, re-run every existing mutant of that file, not only the new one.
- A finding about a delimiter covers both sides of the record. Fix the class, not the side the finding named.
