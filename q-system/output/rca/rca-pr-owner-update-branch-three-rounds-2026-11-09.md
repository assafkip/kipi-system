# RCA: three review rounds on PR #693 each gave a failed `gh pr update-branch` a different wrong exit

**Date:** 2026-11-09
**Trigger:** the 3-round review cap (iteration-speed rule 6) on kipi-system PR #693, ASK-4099. Round 3 was REQUEST CHANGES at head 4a412268.
**Author:** sana-4099, the lane that ran the three rounds. Per rule 6 a fresh Sana agent continues from this file; this lane does not start round 4.

## What happened

PR #693 ships ASK-4099: five fixes to pr-owner.py (the two follow-ups the PR #659 round-7 contract test found, plus that round's three minors). Four of the five were judged sound in all three rounds. One sub-path did not converge: what pr-owner does when its own `gh pr update-branch` call fails, for an approved, green, conflict-free PR that is only BEHIND its base (item 4).

| Round | Head | Verdict | What the update-failure path did | Reviewer's reproducer |
|---|---|---|---|---|
| 1 | 63763b6c | APPROVE WITH NITS | record written before the call; a failure read next hour as "the head did not move", so the red table: rework, then close | a 502, then a close-requeue 48h later |
| 2 | b6e84192 | APPROVE WITH NITS | record written only on success; a failure is not recorded, so it retries every hour forever, exit 2 forever | 24 hourly runs against a 403: 24 calls, exit 2 every time, no escalation |
| 3 | 4a412268 | REQUEST CHANGES | failures counted; at 3 the PR goes to the red table, so close-comment, exit 0, no Linear note | 3 hours of a 502 outage closes every approved BEHIND PR, and the closing run reports healthy |

## Surface symptom

Round 3 review: `~/.config/kipi/pr-reviews/assafkip_kipi-system__pr-693-20261108-184523.md`.
- major: a capped update failure (a 502 outage or a 403 token scope) closes an approved, CI-green PR. The run exits 0. The cap is terminal at that head, so GitHub recovering never clears it (pr-owner.py:897, :1130-1140).
- minor: the docstring (pr-owner.py:55), decide()'s comment (:889) and contract promise P50 still say "once per head, never closed for it", which the code no longer does.

## Surface root cause

decide() sends a capped `updates[key]["fails"] >= UPDATE_TRIES` to `red`. For an approved PR with no open ticket, `red` ends in `close-comment`.

## Structural root cause

### Root cause #1
type: wrong-failure-class

All three rounds routed a failure of **pr-owner's own write** into decide()'s red table. That table is a verdict on the **PR's content** (CI red, conflict, REQUEST CHANGES), and its terminal is a close. A failed API call says nothing about the PR's content. The fleet already has the rule for it, and this lane never read it until round 3 cited it: `.claude/rules/self-healing-retry.md` rule 5. Environmental failures (auth error, server crash, hard-down service) are `environmental-trigger` class, stop on attempt 1, are surfaced, and are never escalated. Each round picked a new retry policy (record before, record never, count to 3) inside the wrong table, so each fix moved the failure to a different wrong terminal: close, then forever, then close again.

### Root cause #2
type: missing-test

The tests were built from each previous finding's single input, not from the input class. Round 1 tested a 502 once. Round 2 tested a 403 every hour. Neither tested a transient outage that outlasts the cap, or a recovery after the cap. Those two inputs are the ones round 3 used. And the contract test checks that each promise's anchors exist in pr-owner.py, not that the promise sentence is true, so "once per head, never closed for it" survived a delta that made it false.

## Verification

This verifies the diagnosis; the fix is not shipped yet (see Fixes shipped). Ran at head 4a412268, in the lane worktree:

```
$ python3 q-system/.q-system/scripts/test/test-pr-owner-contract.py
51 promises, 132 assertions
PASS
```

That pass is the defect: the F4e rows assert that a 403 every hour gives `["update-branch"] x3, then ["close"]`, with exits `[2, 2, 2, 0]`. The suite pins the close round 3 rejected. The round-3 reviewer ran the same path with a 502 and got `run 4: action=close-comment ok=True job-exit=0`. Root cause #1 says to fix this by holding instead of going red. Done, the same F4e run gets four `update-branch` sends, exits `[2, 2, 2, 2]`, no close, and one alert.

Rule check, ran `sed -n 24,28p .claude/rules/self-healing-retry.md`, got: "Environmental failures stop on attempt 1 ... Retrying logic cannot fix an environment; surface it immediately."

## Contributing factors

- No live producer: no fleet repo has strict branch protection (measured 2026-11-09, every repo `strict=false`), so BEHIND is never emitted today. Three review rounds went to a preventive path that has no live input.
- Each round fixed exactly what the previous review named (the brief's "fix exactly what was flagged"). That is right for scope, and wrong when the named defect is one point of an unclassified input space.

## What is finished and sound (keep it)

Reviewed sound in all three rounds, with mutants that each go red on their own promise (M1 to M10, scratch runner in the lane's scratchpad):
- item 1 (P47): a ticket outside linear-worker.sh `QUEUE_STATES` gets close-requeue, never "the worker reworks it".
- item 2 (P48): prune_state() bounds the state file; the 1,000-entry fixture prunes to the 13 it must keep.
- item 3 (P49): `ci_state` "none"; merge with no workflow file, logged as that; red with workflows; hold when unread.
- item 5 (P51): `gh pr merge --auto --squash <n>` from the checkout, asked of merge-bypass-gate.py, re-read, read back; gh_write strips GH_REPO/GH_HOST from every write.
- item 4's success path (P50): update-branch once per accepted head; a live lane holds it (round-1 minor, kept on purpose with a reason at decide()).
- validate passed on head 63763b6c. Both suites pass at 4a412268: contract 51 promises / 132 assertions, unit PASS.

## Fixes shipped

- Surface fix: none yet. This lane stops at the round cap, and the fresh Sana agent ships it on branch sana/ask-4099.
- Structural fix: none yet. Action item 1 is the structural fix (a write failure is classed as environmental and never reaches the content table). Action item 3 removes the false sentences the anchor check could not see.

## Action items

- [ ] A failed update-branch never enters `red`. The PR holds. The first failure at a head files one alert through slack-notify.sh, recorded only when `filed_ticket()` names a ticket, and linear-alert-triage.py takes it nightly. The run exits 2, and the next hour retries, so an outage heals itself. Red-first: a 502 for 4 hours then success gives no close and the update lands; a 403 for 24 hours gives no close and 1 alert, not 24. — owner: fresh Sana agent (launched by the orchestrator on this lane's report) — type: code + test
- [ ] Decide the accepted-call-but-head-unmoved case on purpose: keep red with a reason in code, or hold it like the item above. — owner: fresh Sana agent — type: code
- [ ] Make the promise sentences true: the docstring at pr-owner.py:55, decide()'s comment at :889, and P50's `says` in test-pr-owner-contract.py. — owner: fresh Sana agent — type: doc + test
- [ ] Review the delta only (rule 11): `KIPI_REVIEW_EXPECT_HEAD=<head> bash q-system/.q-system/scripts/pr-review-agent.sh 693 --issue ASK-4099 --post --delta` from the pinned checkout. Merge on kipi/reviewer-approved success plus validate green: `gh pr merge 693 --repo assafkip/kipi-system --squash --match-head-commit <head>`. — owner: fresh Sana agent — type: process
- [ ] After merge, reinstall com.kipi.pr-owner from a fresh worktree at origin/main (`install-plist.sh com.kipi.pr-owner`), dry run from the pinned tree, `launchctl kickstart gui/501/com.kipi.pr-owner`, read ~/.config/kipi/pr-owner.log. — owner: fresh Sana agent — type: process

## Lessons

- Before choosing a retry or exit policy, find the fleet's failure-class rule (self-healing-retry.md) and classify the failure. A write that failed is not evidence about the thing written to.
- When a review names one input, the red-first test covers that input's class: transient, permanent, and recovery.
