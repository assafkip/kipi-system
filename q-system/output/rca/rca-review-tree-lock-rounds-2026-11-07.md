# RCA: three Codex rounds on PR #627 each found a new way for two runs to own one review tree

**Date:** 2026-11-07
**Trigger:** the 3-round Codex cap (iteration-speed rule 6) on kipi-system PR #627, ASK-3930
**Surface-fix commit:** pending
**Structural-fix commit:** pending

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
- The reproducer and its red run on 344b340f, the green run after the fix, and the mutation result are recorded below once the fix lands.

## Contributing factors

- macOS ships no `flock(1)`, which makes a hand-rolled bash lock look like the only option. The python child idiom removes that constraint, and python3 is already a hard dependency of the agent (six call sites).
- Review rounds read only the delta, which is right for cost, but the delta of a lock fix is a few lines, so each round judged the patch and not the protocol.
- The stop rule counts rounds per agent. Nothing counted findings per failure class, so the repeat in round 3 was visible only by reading.

## Fixes shipped

- Surface fix: no age-based mutex stealing remains. Pending commit.
- Structural fix: `acquire_wt_lock` becomes one kernel `flock` critical section (python3 `fcntl.flock`, the `kipi-promote.sh` idiom) over the whole acquire: fast path, re-entry, stale reclaim and the reaper's claim. The mutex is one file per review-trees directory that is never unlinked, so no path can be removed out from under a holder. The PID lock file stays as the long-lived ownership record that every reader already uses. A deterministic two-contender test forces the round 3 schedule with PATH shims and asserts exactly one owner. Pending commit.

## Next round, done differently

- Replace the primitive, not the interleave. No userspace reclaim of a mutex in any form.
- Reproducer first: the forced round 3 schedule, shown red on 344b340f, then green.
- One mutation per fix: drop the `flock` call and the two-contender test must go red.
- State the residuals that remain in the comment and as spillover, instead of shipping a known race as acceptable.

## Action items

- [ ] Replace the mkdir mutex with one kernel flock critical section in acquire_wt_lock, shared by reviews and the reaper. owner: sana. type: code
- [ ] Add the forced two-contender regression test for the round 3 schedule and show it red on 344b340f. owner: sana. type: test
- [ ] Extend the scratchpad mutation script with a "no flock" mutant and record it CAUGHT. owner: sana. type: test
- [ ] Capture PID reuse on the long-lived PID lock (a dead holder's PID reused by an unrelated process reads as live, so the tree is kept) as spillover. owner: sana. type: process

## Lessons

- A userspace lock that must survive a crashed holder cannot be made exclusive by adding another userspace lock. The crash case always needs a reclaim, and a pathname reclaim is a race. Use a lock the kernel releases.
- When a fix's own comment names a residual race, the fix is not done. That residual is the next review's finding.
- Before writing a lock, search the repo for its lock primitive (`LOCK_EX`, `flock`), not only for the lock being patched.
- Test a lock with two real contenders and a forced schedule, and assert the property (one owner), not the patch.
