# RCA: three Codex rounds on PR #627 each found a new way for two runs to own one review tree

**Date:** 2026-11-07
**Trigger:** the 3-round Codex cap (iteration-speed rule 6) on kipi-system PR #627, ASK-3930
**Surface-fix commit:** 265f668b
**Structural-fix commit:** 265f668b

## What happened

PR #627 makes the review-tree reaper archive a finished tree's unique files and then remove the tree. Round 1 found that nothing kept a starting review out of a tree while the reaper archived and removed it, so the reaper was made to hold the per-tree lock. Rounds 2 and 3 then each found an interleave where two processes both believed they held that lock. Each fix moved the race instead of removing it, so round 3 did not return a clean verdict and the loop stops here.

## Surface symptom

Codex verdicts on the lock, in order (session scratchpad, review-3930-r1/r2/r3.txt):

- r1 high, pr-review-agent.sh:1331: "Nothing excludes writers between archive creation and forced removal." Fixed in a1e3d3c4: the reaper takes the tree lock with its own noclobber create plus stale reclaim.
- r2 high, :1277: "Stale-lock removal can delete a newly acquired live lock." Two callers read the same dead PID, both remove and recreate. Fixed in 344b340f: a mkdir mutex `$lock.claim` around reclaim, the holder re-read inside it, and a mutex older than two minutes cleared by age.
- r3 high, :614: "Expiration checks and removes the mutex by pathname, so a delayed contender can delete another caller's fresh mutex." A and B both judge `.claim` expired; A removes and recreates it; B's delayed `rmdir` removes A's fresh mutex; both read the dead holder and both return 0.

## Surface root cause

pr-review-agent.sh line 614 at 344b340f:

    if [ -n "$(find "$m" -maxdepth 0 -mmin +2 2>/dev/null)" ]; then rmdir "$m" 2>/dev/null; continue; fi

The expiry is judged on one read and the removal acts on a pathname later. Nothing proves the directory being removed is the one that was judged expired.

## Structural root cause

### Root cause #1
type: code-defect

The lock is a userspace protocol (a PID in a file, liveness by `kill -0`, a mutex judged by age). Any userspace lock that must survive a crashed holder needs a reclaim step, and a reclaim decided on a read and executed by pathname is a check-then-act. Round 2 put a userspace mutex around the reclaim, so the mutex in turn needed a reclaim for a crashed holder, which was the age check, which is the same check-then-act one level up. Each round could only move the race. Only a lock the kernel releases when its holder dies has no reclaim step at all.

### Root cause #2
type: process

Each round fixed the interleave Codex named rather than the class it belonged to. The round 2 commit shipped with its residual race written in its own comment ("that clearing is itself check-then-act, so the residual race needs a run killed mid-reclaim AND two contenders in the same instant"). The repo already held the fix for the class: `kipi-promote.sh take_lock` takes `fcntl.flock` through a python child on an inherited fd, `linear-worker.sh` lines 1506 to 1519 say "The kernel drops an flock on close AND on process death, so there is no liveness to guess at", and `converge.sh` lines 465 to 490 record a hand-rolled lock that was copied without checking it. Recon for rounds 1 and 2 searched for the existing tree lock, not for the fleet's lock primitive. Rounds 2 and 3 are the same failure (a double owner from a pathname reclaim on a stale read), so the same-failure-twice rule applied before round 3 was written.

### Root cause #3
type: missing-test

Each test proved one fix at one chosen point. Round 1's competitor ran inside the reaper's tar step, after acquisition was complete. Round 2's test stood in as the mutex holder by hand. No test drove two real contenders through a forced schedule at each check-then-act seam and asserted the property that matters: at most one contender owns the tree, and the loser reports busy. So a fix that moved the race passed its own test.

## Verification

Evidence that the diagnosis is real, gathered before the fix:

- Ran `grep -n "lock.claim\|mmin +2" q-system/.q-system/scripts/pr-review-agent.sh` at 344b340f, got line 588 (`m="$1.lock.claim"`) and line 614 (the age check and `rmdir` by pathname): the reclaim of the mutex is itself a pathname reclaim.
- Ran `grep -rn "LOCK_EX" --include='*.sh' .` in the worktree, got `kipi-promote.sh:119`, the inherited-fd `fcntl.flock` idiom: the kernel-lock primitive existed in the repo before round 1.
- Red: ran `bash q-system/.q-system/scripts/test/test-pr-review-reap-trees.sh` with the new tests against the 344b340f `acquire_wt_lock`, got rc 1, 6 FAIL. The forced round 3 schedule printed `round 3 contenders (pid rc): A 37040 0, B 37041 0; the lock holds 37041`: both contenders took the tree and B overwrote A's live lock, which is Codex's interleave exactly.
- Green: the same test after the fix, under macOS bash 3.2 with BSD tools (`PATH=/bin:/usr/bin:/usr/sbin:/sbin:/opt/homebrew/bin /bin/bash ...`), got rc 0, 58 PASS, 0 FAIL, and `A 40875 2, B 40876 0; the lock holds 40876`: one owner, the other busy. The neighbors that extract `acquire_wt_lock` (`test-review-root-and-lock.sh`, `test-review-early-bail-ref.sh`, `test-pr-review-scratch.sh`) are rc 0.
- Mutation: ten mutants through `plugins/prd-os/scripts/mutate.py` (exact-once anchor, green baseline, digest-verified restore), each on a fresh copy, each checked against the one named test that should catch it. All ten KILLED, including the 344b340f `acquire_wt_lock` restored (killed by the round 3 one-owner check), the flock call removed and a per-process mutex file (both killed by the round 2 "A really waited" check), and the live-holder check skipped (killed by "A backs off as busy").

## Contributing factors

- macOS ships no `flock(1)`, which makes a hand-rolled bash lock look like the only option. The python child idiom removes that constraint, and python3 is already a hard dependency of the agent (six call sites).
- Review rounds read only the delta, which is right for cost, but the delta of a lock fix is a few lines, so each round judged the patch and not the protocol.
- The stop rule counts rounds per agent. Nothing counted findings per failure class, so the repeat in round 3 was visible only by reading.

## Fixes shipped

- Surface fix: no age-based mutex stealing remains. 265f668b.
- Structural fix: `acquire_wt_lock` becomes one kernel `flock` critical section (python3 `fcntl.flock`, the `kipi-promote.sh` idiom) over the whole acquire: fast path, re-entry, stale reclaim and the reaper's claim. The mutex is one file per review-trees directory that is never unlinked, so no path can be removed out from under a holder. The PID lock file stays as the long-lived ownership record that every reader already uses. A deterministic two-contender test forces the round 3 schedule with PATH shims and asserts exactly one owner. 265f668b.

## Next round, done differently

- Replace the primitive, not the interleave. No userspace reclaim of a mutex in any form.
- Reproducer first: the forced round 3 schedule, shown red on 344b340f, then green.
- One mutation per fix: drop the `flock` call and the two-contender test must go red.
- State the residuals that remain in the comment and as spillover, instead of shipping a known race as acceptable.

## Action items

- [x] Replace the mkdir mutex with one kernel flock critical section in acquire_wt_lock, shared by reviews and the reaper. owner: sana. type: code
- [x] Add the forced two-contender regression test for the round 3 schedule and show it red on 344b340f. owner: sana. type: test
- [x] Extend the scratchpad mutation script with a "no flock" mutant and record it CAUGHT. owner: sana. type: test
- [x] Capture PID reuse on the long-lived PID lock (a dead holder's PID reused by an unrelated process reads as live, so the tree is kept) as spillover: sp-fac84397, ASK-3933. owner: sana. type: process
- [x] Capture that a review never releases its own tree lock (review_worktree runs in a command substitution, so the EXIT trap sees an empty lock path), which widens sp-fac84397: sp-08d14f6b, ASK-3934. owner: sana. type: process
- [ ] Fix sp-fac84397 and sp-08d14f6b through their own issues. owner: sana. type: code
- [x] Round 6: rc 1 only on proof taken inside the mutex, rc 3 for unknown ownership, and the stale-ref clear run while the mutex is held. owner: sana. type: code
- [x] Round 6: one failure-path test per return path, each red on 96e2d311 by its effect, and the round 4 test proven by effect instead of elapsed time. owner: sana. type: test
- [x] Round 6: the mutation table extended so every new guard has a mutant it kills. owner: sana. type: test

## Residuals stated, not shipped as acceptable

- During rollout, a run that started on the old script still uses the mkdir mutex, which the new flock does not exclude. This lasts only while reviews started before the update are in flight, and clears on its own.
- PID reuse and the never-released review lock: sp-fac84397 and sp-08d14f6b above. Both fail closed (the tree reads busy), so neither produces a second owner.

## Rounds 4 and 5: the same failure twice, so the handoff agent stopped

Round 4 (Codex on 344b340f..c2fce41a, high): the kernel mutex closes the double-owner race, but a contender that timed out on it returned rc 1, so `review_worktree` called `_wt_bail` and deleted refs/remotes/pr/<N> under the live owner. 51aede08 moved that one path to rc 2 (red on c2fce41a, green after, mutant KILLED).

Round 5 (Codex on c2fce41a..51aede08), verbatim:

- high, pr-review-agent.sh:644: "A caller-local failure does not prove the tree is unowned. If A owns the tree and B cannot launch Python or open the mutex, B returns rc 1 and review_worktree deletes A's ref through _wt_bail. Preserve refs when ownership is unknown; perform stale-ref cleanup only after acquiring the mutex and establishing exclusive tree ownership."
- medium, test-pr-review-reap-trees.sh:333: "Elapsed time does not prove mutex timeout. Pause the contender after recording `s` for over 20 seconds: hold_mutex expires, the contender acquires the mutex immediately and returns rc 2 for LIVE, and all three assertions pass even with the old timeout bug. Hold the mutex until explicit release and assert the holder remained locked throughout the contender's execution, or instrument the timeout branch directly."

Rounds 4 and 5 are one failure: rc 1, the destructive branch, returned while ownership is unknown. Round 4's fix moved one path instead of the class, which is root cause #2 above repeating. The class: the caller's contract treats "I could not lock" as proof that "nobody has a tree", and only the inside of the mutex, after reading a dead or absent holder, can prove that.

What the next round builds (one change, not another path):

- Destructive cleanup needs proof. The helper returns a distinct code only when, under the mutex, the holder was proven dead or absent and taking the lock then failed (an unlink, tmp write or link OSError). Bash maps that code alone to rc 1, so `_wt_bail` runs.
- Every other failure (python3 cannot launch, so 126 or 127; an uncaught exception, which exits 1; the mutex cannot be opened; a non-EWOULDBLOCK flock error) maps to a new rc 3, "ownership unknown". `review_worktree` warns and returns 1 without `_wt_bail`. `_reap_take_lock` already skips on any nonzero. Keep the `    2) echo "  WARN: another review holds` line byte-identical, because `test-review-root-and-lock.sh` greps it, and add a `3)` arm next to it.
- The `mkdir -p` parent failure may stay rc 1: with no parent directory there is no tree and no owner.
- The cost is accepted: a ref left in place makes `assert_pr_ref_not_stale` refuse that run with FATAL, a refusal and never a wrong answer. A persistent rc 3 (no python3) is already a broken agent, since the verdict write at line 1742 is python3.
- Tests: a LIVE owner holds the tree, python3 is absent from PATH, and `review_worktree` must return without deleting the ref (drive it the way `test-review-early-bail-ref.sh` does). A mutant that maps "unknown" back to rc 1 must be KILLED.
- Medium: the round 4 test asserts `kill -0 "$H6"` (the holder still holds) after the contender returns and before `let-go`, instead of elapsed time, and `hold_mutex` waits for its release file with no 20 second expiry.

## Round 6: the class, path by path

Built by a fresh agent from the plan above. One change to the contract instead of one more path: rc 1, the only code that leads to a ref deletion, is now earned on proof, and every outcome nobody planned for is rc 3. Codex round 5 also said "perform stale-ref cleanup only after acquiring the mutex", so the shell now holds the mutex on fd 8 (python3 flocks the inherited fd, the `kipi-promote.sh` idiom) until the verdict and any cleanup are done, and `acquire_wt_lock <wt> clear-stale-ref` runs `_wt_bail` itself, inside it.

### Every return path of `acquire_wt_lock`

| Path | 96e2d311 | Now | Proof behind the code | Test (case in test-pr-review-reap-trees.sh) |
|---|---|---|---|---|
| `mkdir -p` of the parent fails | 1 | 3 (8bedf0ef had 1 and cleared; Codex round 6) | none: EACCES on a parent fails mkdir while the tree exists | round 6 mkdirfail, early-bail "a mkdir bail" |
| mutex cannot be opened | 1 | 3 | none | round 6 mutexdir |
| python3 cannot launch (126, 127) | 1 | 3 | none | round 6 nopy |
| python3 killed by a signal (128+n) | 1 | 3 | none | round 6 sigkill |
| flock error other than EWOULDBLOCK | 1 | 3 | none | round 6 flock |
| mutex wait times out | 2 | 3 | another process in a directory-wide mutex says nothing about this tree | round 4 |
| lock file unreadable | 1 | 3 | none | round 6 read |
| liveness check errors with neither ESRCH nor EPERM | 0: read as dead, reclaimed a LIVE owner's lock | 3 | none | round 6 kill |
| live holder that is not this run | 2 | 2 | `kill(pid, 0)` succeeded or EPERM, inside the mutex | round 2, root-and-lock |
| link finds a lock that appeared (EEXIST) | 2 | 2 | a pre-round-3 run created it outside the mutex | none (rollout residual) |
| lock names this run (re-entry) | 0 | 0 if the lock file reads `$$` | the lock record | root-and-lock "re-enters" |
| absent or dead holder, claim linked | 0 | 0 if the lock file reads `$$` | ESRCH or no file, inside the mutex | round 6 control, round 3 |
| absent or dead holder, unlink, tmp write or link fails | 1, cleared AFTER the mutex was let go | 1, cleared INSIDE the mutex | ESRCH or no file, inside the mutex | round 6 claimfail |
| claim linked, tmp tidy fails | 1: this run held the lock and deleted its own ref | 0 | the link | round 6 tmpunlink |
| helper exits 0 but the lock does not name this run | 0: "took" a live owner's tree | 3 | none | round 6 noop |
| any other helper exit (uncaught exception 1, usage error 2) | 1 or 2 | 3 | none | the `*)` mapping, mutant "unexpected exit maps to 1" |

Python's only deliberate exits are 0, 20 (busy), 21 (unowned, written in one place, after the proof) and 22 (timeout). The shell maps 0 to 0 only after reading the lock, 20 to 2, 21 to 1, and everything else to 3.

### Every caller and what it does with each rc

| Caller | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| `review_worktree` | proceeds as the owner; its later bails run `_wt_bail` on a tree it owns | returns 1; the ref was already cleared inside the mutex | returns 1, ref left | returns 1, ref left |
| `_reap_take_lock` (reaper, no clear flag) | archives and removes | skips, keeps the tree | skips | skips |
| main flow, after an empty `review_worktree` | | `assert_pr_ref_not_stale`: absent or current goes on to the fallback search | same; a stale ref makes this run refuse with FATAL | same; a stale ref makes this run refuse with FATAL |

The reaper never touches a ref, so it needed no change. Its skip line still says "held by another run" for rc 1 and 3; it carries no decision, so it was left.

### Evidence

- Red: the new test file against the 96e2d311 agent (a copy, the worktree untouched): rc 1, 91 PASS, 19 FAIL. nopy, mutexdir, flock, sigkill and read each printed `rc=1 ref=` (the live owner's ref deleted). kill printed `rc=0` with the lock rewritten to the claimant (two owners). noop printed `rc=0` and the ref moved. claimfail printed `clears=free free`. tmpunlink printed `rc=1`. The control printed `rc=0` on both versions.
- Green: `bash q-system/.q-system/scripts/test/test-pr-review-reap-trees.sh` rc 0, 110 PASS, 0 FAIL; the same under `PATH=/bin:/usr/bin:/usr/sbin:/sbin:/opt/homebrew/bin /bin/bash` rc 0, 110 PASS. Every case printed its fault as fired and `mutex-after=free`; claimfail printed `clears=held held`. `test-review-root-and-lock.sh`, `test-review-early-bail-ref.sh` and `test-pr-review-scratch.sh` rc 0 on both shells.
- Mutation: 22 mutants through `plugins/prd-os/scripts/mutate.py`, driven by the session scratchpad's `mutate5.sh` (it carries the round 1 to 4 rows forward with anchors re-cut for this code), each on a fresh copy and checked against one named test. All 22 KILLED, 789 seconds. The 12 new rows: an unexpected exit mapped to 1, the 96e2d311 helper restored, rc 0 trusted without reading the lock, an unopenable mutex returning 1, any kill() error read as dead, the clear run after the mutex is let go, a failed tmp tidy overturning a linked claim, the mutex never given back, review_worktree not asking for the clear, review_worktree clearing on unknown, and a timeout mapped back to busy or to unowned. One row first SURVIVED because the instrument named the ref check: with only the old helper swapped in, the new review_worktree no longer calls `_wt_bail` on rc 1, so the ref survives anyway. Renamed to the rc check, it was KILLED.
- Medium closed: `hold_mutex` no longer expires on its own (a 300 second hang guard only). The round 4 check asserts rc 3, which a contender that got inside the mutex could not return (it would read the live PID and return 2), and asserts the holder was still alive when the contender returned. No elapsed-time check remains.

### Codex round 6 (51aede08..8bedf0ef), verbatim, and the fix

- high, pr-review-agent.sh:617: "A failed `mkdir -p` does not prove the directory or live owner is absent, yet this branch calls `_wt_bail` outside the mutex. If A owns the tree and B encounters EACCES traversing its parent, B deletes A's shared ref through the still-accessible REVIEW_REPO. Fault injection confirmed rc 1 and both deletion calls. Return rc 3 without cleanup on mkdir failure, add a live-owner regression test, and correct the RCA table."

8bedf0ef had kept that one exception on reasoning ("no directory, so no owner") and listed it as a residual. That repeated this RCA's own lesson: a residual named in the fix is the next finding. The fix removes the exception, so rc 1 now has exactly one source, python's 21 after proof inside the mutex. This reverses a PR #265 round 2 ruling on purpose: `test-review-early-bail-ref.sh` used to assert that a mkdir bail clears the ref. It now asserts that the ref stays and that `assert_pr_ref_not_stale` then refuses the run with FATAL, a refusal and never a review of the wrong commit.

- Red on 8bedf0ef: the new mkdirfail case printed `rc=1 ref= clears=free free` (3 FAIL), and the early-bail suite failed 2 checks.
- Green: test-pr-review-reap-trees.sh 116 PASS on both shells; root-and-lock, early-bail and scratch rc 0 on both.
- Mutation: two more rows, the 8bedf0ef mkdir branch restored and a mkdir failure returning 1, both KILLED by the mkdirfail checks.

### Residuals stated

- Children started inside the fd 8 window inherit it, and bash 3.2 cannot set close-on-exec (measured: `func 8>&-` moves the fd to 10 and children still get it). Only `cat` and `git update-ref -d` run there. A git hook that outlived the window would hold the mutex, and later claims would time out as rc 3, which keeps refs, so that leak fails closed.
- A run that started on the pre-round-6 script still maps its own failures to rc 1 until it finishes.

## Lessons

- A userspace lock that must survive a crashed holder cannot be made exclusive by adding another userspace lock. The crash case always needs a reclaim, and a pathname reclaim is a race. Use a lock the kernel releases.
- When a fix's own comment names a residual race, the fix is not done. That residual is the next review's finding.
- Before writing a lock, search the repo for its lock primitive (`LOCK_EX`, `flock`), not only for the lock being patched.
- Test a lock with two real contenders and a forced schedule, and assert the property (one owner), not the patch.
- A return code that lets a caller destroy something must be earned on proof, never sit in the default arm of a `case`. Rounds 4 and 5 were the same finding because `*) return 1` turned every unplanned failure into "nobody owns this".
- When a fix is "one more path", list every return path and every caller first. The table above took one pass and found three paths no review had named yet (the liveness error, the no-op exit 0, the failed tmp tidy).
