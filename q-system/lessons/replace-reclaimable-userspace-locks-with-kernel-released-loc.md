---
id: replace-reclaimable-userspace-locks-with-kernel-released-loc
kind: pattern
title: Replace reclaimable userspace locks with kernel-released locks instead of patching each race
date: 2026-11-09
---

When a lock is built in userspace (a PID written to a file, liveness checked by signalling that PID, staleness judged by file age), it must have a reclaim step for when the holder crashes. That reclaim is almost always a check-then-act: read the lock state, decide it is stale, then remove or overwrite it by pathname. Between the read and the act, another contender can do the same, and two processes end up owning the resource.

Adding another userspace mutex around the reclaim does not fix this. The new mutex also needs a reclaim for a crashed holder, which is usually an age check, which is the same check-then-act one level higher. Each patch moves the race and never removes it. The only design without a reclaim step is a lock the kernel releases when its holder dies, such as an advisory file lock (flock/fcntl) held on an open file descriptor. Closing the descriptor or killing the process drops the lock, so there is no liveness to guess and nothing stale to clear. In shell, take the lock on a descriptor the long-running process holds, either directly or through a helper child that inherits that descriptor.

Process lessons:
1. Fix the class of the race, not the specific interleaving a reviewer points out. If a fix's own comment admits a residual race ("still check-then-act, but needs two rare events at once"), the fix is incomplete. Stop and redesign.
2. When a reviewer finds a second instance of the same failure mode, such as a second double-owner from a stale-read reclaim, treat it as a design problem. Do not ship another local patch.
3. Before writing a lock, search the codebase for its existing locking primitive and the reasoning behind it, not only for prior locks on the same resource. Mature codebases often already have a kernel-backed lock helper, and sometimes a recorded incident where a hand-rolled lock was copied without review.
4. Test with real concurrent contenders, not hand-staged state. A test that starts a competitor after acquisition finishes, or fakes the mutex holder by hand, proves one fix at one chosen point and misses the window that matters. Run two or more real processes through the full acquire path at the same moment, kill a holder at different points (before write, mid-reclaim, after acquire), and assert that there is never more than one owner. Repeat many iterations to widen coverage of interleavings.
