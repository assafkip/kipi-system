# RCA: ASK-5352 (consulting PR #635) used three review rounds and had no approving verdict

**Date:** 2026-11-23
**Trigger:** the round 3 delta review ran to its 2400s bound at 13:09 PT, exit 143, no verdict. kipi/reviewer-approved stayed on the round 2 failure.
**Surface-fix commit:** pending (round 4 delta review, base e7f8f7ed, running)
**Structural-fix commit:** pending (ticket filed for Sana, not started)

## What happened

PR #635 got round 1 (APPROVE WITH NITS, head 3f74c339), round 2 (REQUEST CHANGES, one major, head 1eb161a0), then a round 3 delta review of the fix commit 714a3826. Round 3 wrote an empty review file and was killed at the bound. Expected: a verdict on a 102 line delta. Got: no verdict, a round counted anyway, and the reviewer process still alive 44 minutes later.

## Surface symptom

- `~/.config/kipi/pr-reviews/assafkip_ASK_AI_consultant__pr-635-20261123-122911.md` holds only the Code Mode warning line (229 bytes). No findings, no verdict.
- `assafkip_ASK_AI_consultant__pr-635.verdict.json` still says round 2, REQUEST CHANGES, head 1eb161a0, ts 2026-11-23T20:00:38Z.
- At 13:14 PT, `ps` showed `claude -p --model claude-opus-5 ... pull request #635` as pid 34608, parent pid 1, elapsed 44:44, with the wrapper script gone. Load average 28.75.
- The round 4 start line printed `round: 4`, so the review counter held 3 rounds although only 2 verdicts exist.

## Surface root cause

The round 3 run read far more than the fix commit and ran too long under load.

- It was called with `--base 3f74c339`. That range crosses the merges of main (1eb161a0 and e7f8f7ed). The script's merge-crossing check (pr-review-agent.sh, the PR #821 block) compares `merge-base origin/main <base>` with `merge-base origin/main <head>`. I ran both: 3f74c339 gives 34d5ad6c, head gives d9989559. They differ, so the script discards the base and reads the whole PR. The whole PR is 903 diff lines across 13 files. The requested delta was meant to be 102 lines across 3 files.
- The round 2 head 1eb161a0 as base fails the same check (merge base f08b8121 against d9989559). A small base was never available through the head the caller named.
- The reviewer runs the PR's own test files. Rounds 1 and 2 logged `269 passed in 335s` and `127 passed in 230.22s`. At 13:14 PT the machine load average was 28.75 with a 33 minute `verify.sh --staged` pytest from another session at 85 percent CPU. Same work, more than twice the wall time.
- I did not find the round 3 stderr (no file holds it), so the "read the whole PR" line is inferred from the script's code path and the merge-base values above, not seen in a log.

## Structural root cause

### Root cause #1: the bound kills one pid, not the reviewer

type: code-defect

`run_bounded` in pr-review-agent.sh signals only `$job`. The `claude -p` process survived the TERM/KILL and was re-parented to launchd. The review still spends tokens and CPU after the wrapper reports exit 143, holds the review tree, and can never post (its wrapper is gone). I observed pid 34608 at 44:44 elapsed and sent TERM to it and its two children by hand.

### Root cause #2: a round with no verdict counts, so the cap is spent by an abort

type: implicit-contract

The counter counts review files, and the aborted run left one. Three files gave `round: 4`. The same class cost PR #839 its cap earlier (memory note aborted-review-counts-and-version-bump). The fix then was a caller habit ("never start a run you might abort"), which cannot hold when the bound itself aborts the run.

### Root cause #3: a delta across a clean merge of main falls back to the whole PR

type: implicit-contract

pr-owner.py updates lane branches by merging main, so most lane PRs cross a merge between rounds. The fallback is correct when the merge changed the PR's files and wasteful when it did not. I ran `git show --cc e7f8f7ed` and got an empty combined diff: the merge was clean, and `git diff e7f8f7ed 714a3826` is 102 lines across 3 files. The script has no way to take that delta.

### Root cause #4: cap-ladder had nothing to list (this is not a defect)

type: process

cap-ladder reads three cap signs: a capout in the attempts ledger, `.round-cap-<slug>-pr-<n>` in pr-reviews, and escalation keys. I checked: no marker for pr-635 exists, and `linear-worker-attempts.json` has no ASK-5352 entry. The marker is written only when the script is CALLED a fourth time and refuses (PRIOR_ROUNDS >= MAX_ROUNDS). Nobody called it. So the dry run was right: the PR sat at "3 rounds, 2 verdicts" with no cap event. Had any caller re-run with the default cap, the refusal would have written the marker and cap-ladder would have taken it at its next run. That path works as designed. The gap is that the aborted run itself, with exit 143 and no verdict, produces no signal for any consumer, which is root cause #1 and #2 seen from the PR side.

## Verification

Ran `git merge-base origin/main` on the three heads and got three different values (34d5ad6c, f08b8121, d9989559). Ran `git show --cc e7f8f7ed` and got an empty combined diff. Ran `git diff e7f8f7ed 714a3826` and got 102 lines, 3 files. Started `pr-review-agent.sh 635 --base e7f8f7ed` with KIPI_REVIEW_MAX_ROUNDS=4 and KIPI_FLEET_API_KEYS=0; it printed `delta: reviewing only e7f8f7edfd42..714a3826800e (base from --base)`, so the guard accepted the base this time. The round 4 verdict is recorded on ASK-5352 and PR #635, not in this file.

## Contributing factors

- The round 3 caller used the round 1 head as base, which is the wrong end of the range for a PR that main was merged into twice.
- No log of the round 3 stderr was kept, so the whole-PR fallback has to be inferred.
- Test suites run inside the review at a time when other sessions run 30 minute suites on the same machine (load 28.75).
- The wrapper timeout is the only bound, and it reaches one process.

## Fixes shipped

- Surface fix: killed the orphaned reviewer (pid 34608 and two children); reran round 4 as a delta with base e7f8f7ed (the merge commit whose merge base with main equals the head's, clean by `--cc`), KIPI_REVIEW_MAX_ROUNDS=4, --post.
- Structural fix: pending. One ticket for Sana covers the three code items below.

## Recurrence

- rca-pr553-review-rounds-2026-11-18.md: action "stop review rounds that read the whole PR" did not hold because the delta guard cannot take a clean merge of main, so the next lane PR repeats it.

## Action items

- [ ] run_bounded kills the reviewer's whole process group, then verifies none survive — owner: sana — type: code
- [ ] a run that ends without a verdict (timeout, kill) is not counted as a round, or writes its own marker that cap-ladder reads — owner: sana — type: code
- [ ] a delta whose range crosses a merge of main with an empty `--cc` diff reviews from that merge commit instead of the whole PR — owner: sana — type: code
- [ ] the caller picks the base as the last merge commit of main when one sits between rounds — owner: sana — type: doc
- [ ] keep the reviewer's stderr per round next to its review file — owner: sana — type: code

## Lessons

- A bound that kills one pid is not a bound. Check the process list after any timeout.
- A "capped" PR needs a marker before any consumer sees it; a PR that never reached a refused call has no cap event.
- For a lane PR that main was merged into, name the merge commit as base, not an older head.
