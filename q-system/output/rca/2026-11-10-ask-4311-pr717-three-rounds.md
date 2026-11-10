# RCA: PR #717 (ASK-4311) took 3 review rounds and 3 worker attempts and did not land

**Date:** 2026-11-10
**Trigger:** rule 6 of `~/.claude/rules/iteration-speed.md` (3 failed rounds). The WIP release closed PR #717 at 12:34Z as "3/3 attempts spent, terminal"; the orchestrator reopened it at c7650286 and handed it to a fresh Sana lane.
**Surface-fix commit:** pending (this lane, on branch sana/ask-4311)
**Structural-fix commit:** pending (follow-up tickets in Action items)

Author: Sana, lane `sana-ask4311`, ~20:15Z. Written before any code change in this lane. Measured from the worker log, the three review files in `~/.config/kipi/pr-reviews/`, the CI logs at head c7650286, and `git diff --shortstat` per round.

**Structural cause, one line:** every round was judged by a fresh full read of a diff that the previous fix had just grown by about 900 lines, while the two measurements that show the real state (the repo's full CI suite and the DoR's own credit facts) were never taken, and the ticket was bigger than the 1800s run that had to finish it.

## What happened

ASK-4311 moves fleet `claude -p` runs onto the API credits, with a budget, a failover and a daily report. Three worker attempts each pushed a rework and each was killed at the 1800s watchdog. Three claude reviews each returned REQUEST CHANGES with majors in a different area. The PR was closed with its attempts spent, not merged.

## Surface symptom

```
2026-11-10T02:30:13Z TIMEOUT after 1800s; killing process group 2933        (attempt 1)
2026-11-10T03:10:07Z TIMEOUT after 1800s; killing process group 80196       (attempt 2)
2026-11-10T03:49:29Z TIMEOUT after 1800s; killing process group 64057       (attempt 3)
2026-11-10T04:00:16Z ASK-4311: REQUEST CHANGES (round 3)
2026-11-10T12:34:26Z [dry] would release PR #717 (attempts): close it with its last FINDINGS block
```

| Round | Head reviewed | Diff vs base 58c9ac80 | Majors | Where |
|---|---|---|---|---|
| 1 | 1abde256 | 12 files, +2010 | 3 | report GraphQL, `--ready-json` side effects, refusal detector |
| 2 | 5beb4146 | 14 files, +2864 | 2 | `probe` green with no key, killed run never metered |
| 3 | c7650286 | 17 files, +3859 | 1 | dispatch gate fails closed on a crashed helper |

## Surface root cause

- **Rounds:** round 3's major sits in code round 2's fix wrote (the `probe` "no key"/"paused" split and the two gate branches). Round 2's majors sit where round 1's fixes widened `probe` and the watchdog path. Each fix was right for its finding and added new branches that the next full read saw for the first time.
- **Attempts:** each attempt finished its rework, pushed and commented (02:25Z, 02:58Z, 03:48Z), then ran on until the watchdog killed it (rc=143). `linear-worker.sh` charges rc=143 as a failed attempt. So 3/3 was spent by the clock, not by bad work.

## Structural root cause

### Root cause #1: rounds 2 and 3 were full reads, not deltas
type: process

`linear-worker.sh:4177` calls `$REVIEWER_CMD "$PR_NUM" --issue "$ISSUE" --post --engine claude` with no `--delta`. The reviewer has a delta mode (ASK-3884) and rule 11 requires it after round 1, but its main caller never passes the flag. A "fresh eyes" reviewer re-reading a PR that grew 54% then 35% reports new ground each round. Round 2's file says so: "Both of my findings are new ground."

### Root cause #2: the full suite was never measured
type: missing-test

CI `validate` at c7650286 has 22 existing suites red plus 2 new suites undeclared in the capability gate, and `verify` has `test_model_routing.py` red. Main at the same time is red only on `test_trigger_inventory.py` (a 420s timeout, also red on 0ed40627 and f9434b47). So 23 reds are this PR's, present since round 1.
- Most stub `claude` on PATH and drive the worker or reviewer. The PR moved both onto `fleet-claude.sh`, which copied test skeletons lack (rc=127) or which refuses with no key (rc=4).
- Others: new `exit` sites missing from the terminal-states registry, a new plist in neither list of `test-job-checkouts.py`, and the dispatch gate stopping `test-dispatch-disk-floor.sh` case 6.

No round's evidence names `validate`. Each round ran the PR's own suites plus `test-subscription-only.sh`, and the reviewer reads the diff, not CI. One read of CI would have shown 23 regressions on day one, instead of 1 to 3 findings a round.

### Root cause #3: the credit model was never checked against the source
type: implicit-contract

The DoR said $250 per key per calendar month. The facts (`~/.config/kipi/fleet-api.json`, Help Center article 17154008): Max $100 a month, Ultra $200, key 2 unknown, refreshed per billing cycle, key 1 anchored on the 26th. Round 3's minor 2 (the 1st-of-month window) is an edge case of the wrong model. A reviewer reading code built on the wrong model finds those edges one at a time.

### Root cause #4: the ticket was larger than one worker run
type: capacity

The DoR bundled seven deliverables: key helper, failover, spend ledger, dispatch gate, picker order, daily report with a launchd job, and the call-site inventory. A rework round took 18 to 29 minutes, which leaves no margin under the 1800s watchdog. The worker also cannot tell "killed after pushing" from "killed with nothing done", so real work still burns attempts.

## Verification

Evidence for the diagnosis, observed this session:

```
gh run view 42751755948 --log-failed | grep -c "RED: test-failed"          -> 22
gh run view 42751755945 --log-failed  -> FAILED test_model_routing.py::CallSites::test_worker_main_run_passes_a_model
gh run view 42855329078 --log-failed (main f9434b47) | grep "RED: " -> test-timeout (420s): test_trigger_inventory.py (only)
grep -n "pr-review-agent\|REVIEWER_CMD" linear-worker.sh  -> 4177: ... --post --engine claude   (no --delta)
git diff --shortstat 58c9ac80 1abde256 / 5beb4146 / c7650286 -> +2010 / +2864 / +3859
```

Verification of the fix (validate green, a delta round's verdict) is recorded on ASK-4311 when this lane lands.

## Contributing factors

- The reviewer persona is told to find what is wrong with fresh eyes, which is right for round 1 and wrong without a delta.
- The worker's own evidence blocks listed the PR's suites and called them done; nothing compared that list to what CI runs.
- Two new test files were not declared to the capability gate, so the updater test went red as a side effect.
- The 1800s watchdog is per run, and the ticket had no split point between "core path" and "report and ordering".

## Fixes shipped

- Surface fix: this lane fixes the 23 reds, the round-3 findings and the credit model on sana/ask-4311 (commits listed on ASK-4311).
- Structural fix: pending, see Action items. The lane itself runs delta reviews by hand and runs every dispatcher, worker and reviewer suite before each push.

## Action items

- [ ] The worker's review call passes `--delta` after round 1 (`linear-worker.sh:4177`) — owner: Sana via the fleet worker (`owner:sana` ticket) — type: code
- [ ] A run killed by the 1800s watchdog after it pushed is not charged as a failed attempt — owner: Sana via the fleet worker (`owner:sana` ticket) — type: code
- [ ] This lane runs every suite that drives `kipi-dispatch.sh`, `linear-worker.sh` or `pr-review-agent.sh` before each push, and reads CI before asking for a review — owner: Sana lane `sana-ask4311` — type: process
- [ ] Per-key credit and cycle facts are read from `~/.config/kipi/fleet-api.json`; no amount is hard-coded — owner: Sana lane `sana-ask4311` — type: code

## Lessons

- A full-PR review per round on a growing diff never converges. Review the delta.
- The PR's own suites are not the target. CI is. Read it before round 2, not after round 3.
- Check the premise against its source before building edge cases of it.
- If a rework round takes most of the run's wall clock, the ticket is too big for the run.
