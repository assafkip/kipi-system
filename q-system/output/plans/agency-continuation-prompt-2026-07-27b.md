# Continuation brief: the loop converges, and the two open founder decisions (ASK-113)

Written 2026-07-27, after the session where the review loop first reached APPROVE.
Paste the whole thing into a fresh session.

---

You are continuing autonomous work in `/Users/assafkipnis/projects/kipi-system`.
Tracking epic: **ASK-113**. The founder authorized this end to end. Sana does the
implementation; you fix the LOOP and dispatch her. Never route work to the founder.

## The headline: the loop converges now, unattended

It could not before. The reviewer had no severity floor, so REQUEST CHANGES fired
the same on 3 minors as on 1 blocker, and a Netflix-3am bar always finds
something. The gate was unsatisfiable by construction. Fixed and proven:

| Issue | Rounds | Verdict | PR |
|---|---|---|---|
| ASK-150 | 5 (4 before the fix) | APPROVE WITH NITS | #11 |
| ASK-183 | 3, fully unattended | APPROVE WITH NITS | #12 |
| ASK-184 | 1 (+1 stranded, see below) | APPROVE WITH NITS | #13 |
| ASK-188 | 1 | APPROVE WITH NITS | #14 |

ASK-150's arc was monotonic: 2 blockers, then 1 blocker + 2 majors, then 1 major
+ 6 minors, then 2 majors + 3 minors, then 2 minors + a nit. The work was
converging the whole time; only the gate could not say "good enough".

## TWO OPEN DECISIONS. Both are the founder's.

### 1. Branch protection — 4 approved PRs cannot merge

`gh pr merge 14` returns *"the base branch policy prohibits the merge"*. Getting
through needs `--admin`, because `validate` on main is RED on the 46 containment
findings (ASK-58/ASK-59). I did NOT use `--admin`: overriding a protection gate
unattended is the PocketOS shape the global rules exist to prevent.

**Consequence:** the parallelism unlock is INSIDE PR #14. Until it merges the
board stays serial at 25-70 min per issue. Founder decides: merge with `--admin`,
or fix validate first, or relax the required check for `sana/*` branches.

### 2. Long runs are being SIGKILLed — dispatching is currently unreliable

Three consecutive dispatches died: ASK-181 twice, ASK-182 once. Each left a
leaked claim that stopped the whole board until released by hand.

What is RULED OUT (do not re-test these):
- Not `claude -p` failing: it works standalone AND inside the worktree. Verified both.
- Not ASK-181-specific: ASK-182 died the same way. Session-level.
- Not the launchd-health watchdog killing its own run: `launchd-health-check.py`
  only shells `launchctl list` and posts Slack. It never boots out or kills.
- Not my TERM trap: the first kill predates the trap commit.
- **"Execution error" in the worker log is the SYMPTOM, not the cause.**
  `claude -p` emits it as it dies. Do not chase it as a root cause.

Still open: what sends the SIGKILL. 5 runs succeeded 07:16-08:19 UTC; the 3
failures were 13:36-13:54 UTC after a ~5h idle gap. Suspect the harness's
background-task lifecycle late in a long session. **Last action of the session:
relaunched ASK-182 DETACHED via `nohup ... & disown`** writing to
`~/.config/kipi/converge-ask182.log` — read that log first, it answers whether
detaching defeats the killer. If it does, detached is how converge should always
be launched.

## What shipped (all pushed to main)

| Commit | What |
|---|---|
| `22dfa8c` | Severity floor: blockers/majors rework, minors captured not wedged |
| `3e788f3` | Verdict DERIVED from severities + anchors + anti-re-litigation + `converge.sh` |
| `f221cd6` | Worker opens the PR in code (the ASK-184 stranding) |
| `4b5a7af` | Killed converge releases its claim (TERM/INT/HUP only — see ASK-189) |

- `pr-verdict-lib.sh` — ONE extractor, ONE `rework_gate`, shared by reviewer and
  worker. `verdict_from_findings()` computes the verdict from the labelled
  severities, and the reviewer's stated verdict is recorded beside it so
  miscalibration stays visible. A grading rule written into the reviewer text
  decides nothing on its own; `verdict_from_findings()` is the deterministic
  function that sets the gate, and `test-severity-floor.sh` is what fails if it
  drifts.
- `kipi converge --issue ASK-n [--max-rounds N]` — drives one issue to an
  approved PR with four coded exits: goal met, round cap, no-progress (same
  verdict AND unchanged head sha), error.
- Tests: `test-severity-floor.sh` 24/24, `test-converge.sh` 16/16, both declared
  in the capability manifest.

## Bugs found by RUNNING, not reading (the session's real lesson)

1. **My own parser lied.** Round 4 said `**REQUEST CHANGES** (not BLOCK — nothing
   here writes an unrecoverable object)`. The extractor took the last token on the
   line and recorded BLOCK. Both route to rework so behavior survived, but
   `APPROVE (not BLOCK...)` would have reworked an approved PR forever.
2. **Sana caught a bug I read past.** `rc=$?` under `if ! cmd` captures the
   NEGATION's status, so rc was always 0 and the claim-collision branch was
   unreachable — a real collision surfaced as "INFRA: claim failed rc=0".
3. **A claim released from the wrong cwd silently succeeds.** Release reads a
   different lock file, prints "not held", exits 0, and the real lock strands the
   issue forever.
4. **My TERM trap killed its own caller.** `kill -TERM $$` from a backgrounded run
   reached the parent. A cleanup path that can kill its caller is worse than an
   unconventional exit code.
5. **My test died while asserting on a kill.** `run_case` restores `set -e`, and
   `wait` on a SIGTERMed job returns 143, so the suite aborted with later cases
   silently unrun — indistinguishable from the defect it tested for.

## Queued for Sana, both urgent, in dependency order

- **ASK-188** (PR #14, approved, unmerged): claim taken from inside the worktree
  so issues stop contending for one repo-root lock. Verified 7/7 driving the real
  script concurrently. **Merge this before ASK-189** — same call sites.
- **ASK-189**: a SIGKILLed worker leaks its claim permanently. SIGKILL cannot be
  trapped, so the repair must live in the lock's READ path: record the WORKER's
  pid (long-lived, unlike the claiming python process) or a lease+TTL. The DoR
  names the failure to avoid above all — a liveness check that reads "dead" for a
  healthy long-running worker would quietly disable the mutex while its suite
  stays green.

## Open spillover from this session

`sp-a04b5299` worktrees never refresh between rounds (ASK-150's tree ran 9
commits behind main) · `sp-3477e5a9` worker cannot reach cross-repo issues
(ASK-114's target was 4_points_consulting) · `sp-7078a307` the worker itself still
leaks a claim on a direct `kipi work` kill · `sp-dd31f93b` PR #14's own test
leaked a real `sana/ask-aaa` branch + worktree into live state while passing 7/7
· `sp-38d9d19d` `launchd-health-check.py` matches `--dry` exactly while every
migration DoR passes `--dry-run`, so that watchdog runs LIVE when it believes it
is rehearsing.

Also worth knowing: pushing matters. Worktrees branch from `origin/main`, so
unpushed local commits mean Sana works against a stale base. Dispatching ASK-188
unpushed would have had her revert the severity floor.

## Standing constraints (unchanged)

Subscription only; `claude -p` under launchd, never cron. Linear objects are
permanent. The worker's four refusals are load-bearing: never merges, never
closes, never touches `owner:assaf`, never touches an issue without a DoR.
Instruction budget FAILING 513/300 — add no new always-on rules; write plan docs.
`gates run` is RED on 85 open spillover items (ASK-148), pre-existing.

## Suggested order

1. Read `~/.config/kipi/converge-ask182.log`. Did the detached run survive? That
   decides whether dispatching works at all right now.
2. Put the merge question to the founder (branch protection). Nothing scales
   until PR #14 lands.
3. `kipi linear claims` before any dispatch; release a stale one by its recorded
   holder, never by deleting the lock file.
4. Then ASK-189, then resume the board (36 job-migration issues + the audits).
