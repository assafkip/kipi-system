# RCA: PR 841 (disk janitor) hit the 3-round review cap with a major still open

**Date:** 2026-11-18
**Trigger:** review cap reached on assafkip/kipi-system#841; round 4 verdict REQUEST CHANGES
**Surface-fix commit:** pending
**Structural-fix commit:** pending

## What happened

PR 841 versions disk_janitor.py and adds reclaim rules (ASK-4234). Review rounds 1 to 4 traded one
finding back and forth: round 1 said a mode-000 target errors on every run, the fix unlocked it, round 3
said the unlock defeats the git gate, the fix stopped unlocking git-gated targets, and round 4 found the
gate itself reads an unreadable checkout as clean. The PR capped with the real defect still in the code.

## Surface symptom

Round 4 review (`~/.config/kipi/pr-reviews/assafkip_kipi-system__pr-841-20261118-141614.md`): a worktree
with a mode-000 subdir holding unsaved work gave `git status` rc=0, empty stdout,
`Permission denied` on stderr. The janitor logged `{"kipi-worktrees": {"delete": 1}}`, exit 0.

## Surface root cause

`git_state()` in `q-system/.q-system/scripts/disk_janitor.py` returned "clean" on `rc == 0` with
empty stdout and never read stderr. A mode-000 top dir hid `.git` and returned "not-a-repo", which
also passes the gate.

## Structural root cause

### Root cause #1
type: implicit-contract
The git gate's contract was "clean means git saw the whole tree and found nothing". The code only
checked "git printed nothing". Nothing tested the gate with an input git cannot fully read.

### Root cause #2
type: process
Each fix round patched the step the reviewer named (the chmod in the delete path) instead of the
gate the delete trusts. Same class twice should have moved the fix to the gate after round 3.

## Verification

Ran `python3 -m pytest q-system/.q-system/tests/test_disk_janitor_reclaim.py -q`: before the fix
`test_unreadable_subdir_is_not_read_as_clean` failed (`AssertionError: 1 != 0`, the worktree was
partly deleted); after it, 18 passed. Mutants: dropping the stderr check or the access check each
turns exactly one test red.

## Contributing factors

- The fixture for git-gated cases only ever made the top dir unreadable, never a subdir.
- Each round reviewed a delta of a chmod line, which kept attention on the delete step.

## Fixes shipped

- Surface fix: `git_state()` returns "error" on any stderr and "unreadable" when the target cannot be
  read; consider() maps "unreadable" to a skip, so no delete error re-pages every run.
- Structural fix: red tests for both unreadable shapes pin the gate's contract, not the chmod.

## Recurrence

<!-- rca-recurrence-skip -->

## Action items

- [x] Gate returns error on stderr, skip on unreadable target, tests red then green: owner: Sana (ASK-3976) : code
- [ ] Re-review the combined PR from round 1 on a new PR number: owner: pr-review-agent.sh : process

## Lessons

- A gate that answers "clean" must prove it saw everything; empty output is not proof.
- When a reviewer finds the same class twice, fix the thing the failing step trusts.
