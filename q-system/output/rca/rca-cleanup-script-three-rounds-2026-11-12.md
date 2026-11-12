# RCA: PR #773 used all three review rounds and still failed its verdict

**Date:** 2026-11-12
**Trigger:** `kipi/reviewer-approved` failed on head c7313201; the reviewer refuses a 4th round (round cap 3 in `pr-review-agent.sh`).
**Surface-fix commit:** pending
**Structural-fix commit:** pending

## What happened

PR #773 added `cleanup-merged-refs.sh` (ASK-4650) with three batches: A and D delete remote branches, B removes worktrees. The recorded decision (RULE-2026-11-12-A in `decisions.md`) says the daily reaper owns tree removal. The script grew its own tree-removal batch anyway. Three review rounds each found defects in batch B that `worktree-reaper.py` had already solved and tested, and the third round ended in REQUEST CHANGES.

## Surface symptom

Round 3 verdict file (`pr-773.verdict.json`): `"verdict": "REQUEST CHANGES"`, `"round": 3`. Round 3 finding, major: "batch B removes a review tree whose <tree>.lock is held by a live pr-review-agent run, a state worktree-reaper.py:373 explicitly refuses". Round 3 also names the pattern: "the PR introduces a second remover of worktrees that the daily reaper already owns, and it does not take the claim mutex the reaper takes."

## Surface root cause

Batch B (`cleanup-merged-refs.sh`, the `if [ "$BATCH" = B ]` block) re-implemented the reaper's per-tree safety checks by hand in bash, and each round found one more check the copy lacked.

Findings by round, from the three review files:

| Round | Findings | In batch B | Already solved in `worktree-reaper.py` |
|-------|----------|-----------|----------------------------------------|
| 1 | 6 (2 major, 3 minor, 1 nit) | 2 majors | trailing-slash vs process census (`test_a_process_working_inside_keeps_the_tree`); status rewriting the index (`test_the_status_check_does_not_make_an_idle_tree_look_touched`) |
| 2 | 5 (4 minor, 1 nit) | 2 minors | live `<tree>.lock` (`_review_lock_held`, line 169); unchecked mtime read |
| 3 | 3 (1 major, 1 minor, 1 nit) | major + minor | live `<tree>.lock` again (reaper line 373); PR table cap |

Batch B holds 3 of the 3 majors across all rounds and 6 of 14 findings. Batch B is about 40 of the script's 161 lines.

## Structural root cause

### Root cause #1

The decision was recorded but nothing bound the script to it. The decision says trees belong to the reaper, and the script's own capability note says "Tree removal in steady state is worktree-reaper.py". No test or check failed when a second remover of the same trees appeared. Two writers of one resource (tree removal) means every safety rule the first writer learned has to be re-learned by the second, one review round at a time. The reaper's tests encode those rules (process census, lock mutex, index-refresh trap, census failure); the copy had none of them, so each round re-discovered one.

type: implicit-contract

### Root cause #2

The review rounds spent their budget on the cheap-to-find class. Round 1 and 2 found argument-parsing, help text and dry-run behaviour in the script. Round 3 states that the largest blast radius in the diff (a second remover of reaper-owned trees) was present in the first commit and unexamined until the cap. A round cap of 3 with findings that surface one at a time cannot converge on a design that carries a duplicate of a solved problem.

type: process

### Root cause #3

The batch B scope reason was real but small: the census found 31 finished trees that the reaper did not see. The reaper did not see them because three tree layouts were in no root. That gap was fixed in the same PR (`worktree-reaper.json` roots plus a root-coverage test). Once the roots were fixed, the reaper covered the 31 trees on its next daily pass, so batch B had no job left to do.

type: missing-test

## Verification

Evidence that the cause is the duplicate, not the author's care: every batch B major and the batch B minors map to a named reaper function or test that already existed on main. Commands run for this RCA:

- `grep -n "_review_lock_held\|GIT_OPTIONAL_LOCKS\|lsof" q-system/.q-system/scripts/worktree-reaper.py` showed the lock check at line 373, the census at line 102.
- `grep -n "def test_" q-system/.q-system/tests/test_worktree_reaper.py` showed the process, status, lock and failed-census tests listed in the table above.
- Fix verification is in the structural-fix commit: both test files rerun green and mutants for the touched decision points go red (recorded in the PR body).

## Contributing factors

- A decision with no executable pin: nothing fails when the script grows a tree remover.
- Findings arrive in a trickle (2 to 3 per round), so the cap runs out before the class is named.
- The reaper's rules live in its tests, not in a shared helper, so a second implementation cannot import them.
- A founder-run script avoids the 3am framing, which made the lock gap look lower risk each round.

## Fixes shipped

- Surface fix: pending. Add the lock and PR-cap checks to batch B (rejected: it would be a fourth copy of the reaper's rules).
- Structural fix: pending. Delete batch B and its tests so the script handles remote branches only (batches A and D). Trees have one owner, `com.kipi.worktree-reaper`. A test asserts the script refuses `--batch B` and never calls `git worktree remove`.

## Recurrence

- rca-wait-has-consumer-three-rounds-2026-11-09.md: that RCA's action items target a missing consumer for a wait; this one is a second implementer of an owned job. Different class, listed because both end with the round cap spent.

## Action items

- [ ] Delete batch B and its tests from `cleanup-merged-refs.sh` and `test_cleanup_merged_refs.py` — owner: sana — type: code
- [ ] Pin "the script never removes a worktree" with a test that fails if `git worktree remove` appears in the script — owner: sana — type: test
- [ ] Update the usage text and RULE-2026-11-12-A so the script's scope matches the decision — owner: sana — type: doc
- [ ] Review the first commit of any new remover or deleter against existing owners of the same resource before round 1 — owner: sana — type: process

## Lessons

- Before adding a second writer to a resource, grep for the first writer and read its tests. Its tests are the list of rules the copy will be asked to meet.
- A recorded decision that says "X owns Y" needs a test that fails when something else starts doing Y.
- When round 2 findings fall in a block that round 1 also hit, ask whether the block should exist, not whether it is correct yet.
