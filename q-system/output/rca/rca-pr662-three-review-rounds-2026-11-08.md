# RCA: PR #662 (ASK-3824, cap ladder) reached its third review round still REQUEST CHANGES

**Date:** 2026-11-08
**Trigger:** pr-review-agent.sh round 3 on PR #662 (head 324e5cdd, delta cc3ed9cf..324e5cdd) returned REQUEST CHANGES: 1 major, 1 minor. Written at the round cap, per iteration-speed.md rule 6: the agent that ran three rounds hands off to a fresh Sana agent with this diagnosis and does not start round 4.

## Short answer
Every round's major sat in one subsystem, the founder-ask channel (the morning status file's writer, reader, resolve and hold release). Each was introduced by the previous round's fix. That subsystem was designed inside the review loop and tested per finding, never per property.

## What happened
| Round | Head | Verdict | Findings |
|---|---|---|---|
| 1 | b3edcfda (full PR) | REQUEST CHANGES | 3 majors, 1 nonblocking major, 1 minor |
| 2 | cc3ed9cf (delta) | REQUEST CHANGES | 1 major, 4 minors |
| 3 | 324e5cdd (delta, includes a merge of main) | REQUEST CHANGES | 1 major, 1 minor |

## Surface symptom
Three consecutive REQUEST CHANGES verdicts on #662. The PR now holds 3 usable review rounds, so pr-review-agent.sh refuses a 4th at its cap.

## Surface root cause
Round 3 major: `status_add` in cap-ladder.py returns "" when it dedupes an identical unresolved ask, and `apply_decision` stores that "" as the hold's `ask_id` (cap-ladder.py:694). A repeated identical FOUNDER-DECISION therefore leaves a hold that `ask_resolved("")` can never release, while `--resolve` on the issue reports success on the older row.
Round 2 major: the first version of the channel keyed a resolved ask on the issue, so it released every later founder hold on that issue.
Round 1 majors: a gh failure read as "no branch", FOUNDER-DECISION waited on a flag nothing wrote, and SPLIT sub-tickets had no needs-triage.

## Structural root cause
type: process

1. **A subsystem was designed inside the review loop.** Founder rulings arrived mid-PR ("What's the point of timed retries", "but what happens if nothing changed? the ticket just stays?"). Between rounds, one PR gained the decision rung, event re-entry, ladder_hold, blocker-first ordering and a founder-ask channel. The channel had no prior design and no reader in the repo, so it was built one finding at a time.
2. **Tests were written per finding, not per property.** Each fix got a pin for the exact scenario the reviewer named. No test covered an ask's whole lifecycle: create, dedupe, hold, resolve, release, repeat. The round-3 bug is the "repeat" edge of that lifecycle.
3. **The PR is too wide for three rounds.** Ladder rungs, decision validation, event re-entry, the worker hold, pick order, ladder_owns, founder asks and a morning-brief section are at least two PRs.

## Verification
- Ran pr-review-agent.sh round 3 at 22:26Z and got REQUEST CHANGES. The review is at ~/.config/kipi/pr-reviews/assafkip_kipi-system__pr-662-20261108-142620.md.
- Read cap-ladder.py `status_add`: the dedupe branch is `return ""`, and `apply_decision` assigns it to `d["ask_id"]`.
- Everything else on the branch passed locally on 324e5cdd:
  - test_cap_ladder.py: 63 checks.
  - test-terminal-states.sh: 39 passed.
  - Also passed: test-fleet-liveness.py, test-job-checkouts.py, test-worker-guard-settings.sh (5 checks; this was the one red CI found on b3edcfda), test-worker-expired-park.sh (9) and test-severity-floor.sh.
  - The worker WIP, env-halt, review-redrive (39), converge-capout (38) and review-round-cap suites passed.
  - test_morning_brief.py: 63 passed.

## Contributing factors
- Three founder rulings in one evening changed the ladder's last rung twice.
- The status file was invented in round 1 to answer a finding, not designed first.
- A merge of main (6 commits, including #663's sort-last) entered the round-3 delta and widened what the reviewer read.

## Fixes shipped
- Round 1 (cc3ed9cf): only a gh 404 counts as "no branch"; a status-file writer, reader and resolve; needs-triage on sub-tickets.
- Round 2 (c91f1f5c): per-ask ids; dedupe by ask text; resolve one ask; the pytest refusal first.
- Census fix (287f0ce6): the primary claude launch keeps its literal shape and guard set.
- The round-3 findings are NOT fixed. They are the first action items below.

## Action items
- [ ] In `status_add`, when an unresolved row with the same issue, kind and ask exists, return that row's `id`, not "". Pin it: two BLOCKED-ON FOUNDER-DECISION decisions with the same ask text, one `--resolve`, and the hold releases.
- [ ] founder_asks.py and cap-ladder.py: replace "the stall sweep (ASK-4019) reads the same file" with "ASK-4019 will read it once built", or drop the clause.
- [ ] Add one lifecycle property test for an ask: create, dedupe returns the same id, hold, resolve by issue and by id, release, and a second distinct ask.
- [ ] Main decides the way past the review cap: a 4th round with KIPI_REVIEW_MAX_ROUNDS raised for #662, or a split. In the split, the founder-ask channel (status_add, status_resolve, --resolve, --founder-ask, founder_asks.py, the morning-brief registration) moves to its own PR, and #662 lands the ladder with FOUNDER-DECISION released by event (c) or (d) only.
- [ ] After merge: `install-plist.sh --pinned`, `launchctl kickstart gui/501/com.kipi.cap-ladder`, read `~/.config/kipi/cap-ladder.out`. Expected from the live dry run: 4 climb (ASK-1304, ASK-142, ASK-1923, ASK-3036), 2 wait on routing (ASK-128, ASK-1104), 11 closed records drop.
- [ ] #668 (ASK-3960) and #670 (ASK-3961) call `cap-ladder.py --founder-ask`. Rebase them on whichever PR carries the channel.

## Lessons
- A ruling that adds a new channel mid-PR gets its own PR, designed before code, with a lifecycle test written first.
- When a review finding lands in code the previous round wrote, test the whole lifecycle of that code before the next push, not only the named scenario.

## Addendum: the agent that took over (2026-11-08, after the cap)

Main's decision, recorded: SPLIT. PR A (#662, this branch) lands the ladder without the founder-ask channel. PR B (a new branch and ticket) carries the channel with the round-3 fixes.

### What PR A does with FOUNDER-DECISION
- check_blocker refuses a FOUNDER-DECISION target at validation. The refusal sends the RCA agent back for SPLIT or CLOSE, the same path a free-text blocker takes.
- The rung-4 prompt in fable-escalate.py no longer offers FOUNDER-DECISION, so no RCA call is spent on an answer that is always refused.
- Removed from PR A: the status file writer and reader, `--resolve`, `--founder-ask`, founder_asks.py and its morning-brief registration. PR B puts them back and turns the refusal off.
- ladder_owns() is unchanged, signature included, because pr-owner.py (#659) loads it by path.

### What changes in how I test
1. **Drive the real thing, never a model of it.** Every check runs the real cap-ladder.py as a subprocess, through its real CLI, against a temp world. For PR B, that means the real `--founder-ask` and `--resolve` verbs write the file, and the real `founder_asks.collect` reads it. No check builds status rows by hand and then asserts on them.
2. **Test the whole lifecycle, not the named finding.** PR B writes one property test first, before any fix: create an ask, dedupe returns the same id, hold, release on an event, re-cap with the same ask (same id again), resolve by id and by issue, the hold releases, then a second distinct ask on the same issue stays held. The round-3 bug was the "re-cap with the same ask" step of that sequence.
3. **Every new check is seen to fail.** Each one gets a mutant run through `plugins/prd-os/scripts/mutate.py`: the anchor matches exactly once, the bytes move (digest), the baseline is green first, and the bytecode cache sits outside the tree. For PR A, the mutant is a check_blocker that accepts FOUNDER-DECISION again. The refusal case must turn red.
4. **Name only readers that exist.** A comment that names a consumer names a script that is in the repo and installed, plus when it runs. cap-ladder.py:57 said the stall sweep (ASK-4019) reads report.json. ASK-4019 scans tickets and PRs, not that file. The honest consumers are cap-ladder.py itself the next night (no decision on file) and linear-owner-sweep.py at 02:00 (a blocker that lost its owner:* label).

### Stop rule for this agent
- One review round on the delta (KIPI_REVIEW_MAX_ROUNDS=4).
- If that round finds a major in code PR A changed, this agent does not start a fifth round. It writes the finding here and hands off to a fresh Sana agent, per iteration-speed.md rule 6.
