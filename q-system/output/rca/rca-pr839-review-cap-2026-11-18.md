# RCA: PR #839 was approved at 060b3038 and still could not merge, review cap spent

**Date:** 2026-11-18
**Trigger:** the lead's round-cap rule (3 rounds without a merge); ASK-4969 comment of 21:57 UTC
**Surface-fix commit:** pending (the merge is blocked on the open question in "Action items")
**Structural-fix commit:** pending

## What happened

PR #839 (Lane D, ASK-4969: `voice_full_gate.py` and `part_runs.py`) took three usable review rounds. Round 3 approved head 060b3038 (APPROVE WITH NITS, `kipi/reviewer-approved` success, all checks green). Then main moved (#840, ASK-5411) and both PRs bumped the same `plugin.json` version line, so #839 went CONFLICTING. The conflict was resolved by merging origin/main into the branch, which made head 55e215b0. That head carries no approval, and the reviewer refuses a fourth round, so the PR sits BLOCKED with the auto-merge armed and nothing able to satisfy the required check.

## Surface symptom

```
55e215b0  kipi/reviewer-approved  failure  21:56:58Z  no reviewer verdict at this head (floor: absent is not approved)
55e215b0  kipi/reviewer-approved  pending  21:57:06Z  review cap reached (3); cap-ladder.py takes this PR at its next nightly run
060b3038  kipi/reviewer-approved  success  21:33:41Z  delta 21aa3214..060b3038: APPROVE WITH NITS
gh pr view 839: mergeStateStatus BLOCKED, autoMergeRequest enabled 21:17:43Z (SQUASH)
```

## Surface root cause

A push after the last reviewed round. Merging origin/main into the branch created a new sha. GitHub statuses attach to a sha, so the approval stayed on 060b3038. The `reviewer-floor` workflow (fires on `synchronize`) correctly posted `failure` on the new sha, and `pr-review-agent.sh` (PRIOR_ROUNDS 3 >= MAX_ROUNDS 3) refused a new round with PENDING.

## Structural root cause

### Root cause #1: the carry path only knows receipt-only deltas

`receipt-carry-approval.sh` is the one route that copies an approval onto a later sha. `delta_kind` returns `same | receipt-only | other`, and only `receipt-only` carries (line 186 onward: "only a receipt-only delta carries"). A merge of origin/main is `other`. So a delta that is main's own commits plus a version line gets no carry, and its only remaining route is a fresh review that the cap forbids.

type: implicit-contract

### Root cause #2: the cap counts reviews, and a main merge is not a review-worthy change

The cap (`pr-review-agent.sh` lines 455-467) is a budget on model runs per PR, not per head. Every review costs a round whether it reads new PR code or not. A clean merge of main adds no PR-owned code, but it needs a verdict on the new sha, and the only way to get one spends a round.

The delta-review code already knows the difference: `pr-review-agent.sh` ~line 1091 reads the whole PR when a range crosses a merge of base, because the two-dot delta would show main's code as the PR's (PR #821 round 1). The reviewer therefore treats a main merge as the expensive case, which is right for review and wrong for re-attestation.

type: process

### Root cause #3: three rounds each found something real, so the cap was reached honestly

Round 1 (20:36, REQUEST CHANGES): 2 major, 3 minor, 1 nit. Round 2 (21:17): 2 minor, 1 nit. Round 3 (21:33): 2 minor. Every round's findings were real and each fix was a small hardening of one new file. The cap did its job; the reviewer did not overrun the cap. The cost was the ordering: the merge of main came after the approval and was not avoidable (the same version line was changed on main).

type: code-defect (the findings themselves), not a gate defect

### Correction to the ASK-4969 note

The note said one counted round was an aborted run. Measured: of the four review files for PR 839 in `~/.config/kipi/pr-reviews/`, the 0 byte file (`...125549.md`) is NOT usable under `review_is_usable`; the other three are. `PRIOR_ROUNDS` is 3 without it. `pr-839.verdict.json` says `"round": 4` because it counts files, not usable rounds. The abort did not spend a round and did not cause the cap.

## Verification

Ran these against the live PR and ledger before writing this, and observed:

- Ran `gh pr view 839 --json ...statusCheckRollup`, got: validate IN_PROGRESS at write time, `kipi/reviewer-approved` PENDING on 55e215b0.
- `gh api repos/assafkip/kipi-system/commits/<sha>/statuses` for both shas: approval on 060b3038, failure then pending on 55e215b0 (table above).
- `review_is_usable` run on each of the four review files: usable, not-usable (the 0 byte file), usable, usable.
- `git show -s --format=%P 55e215b0`: parents 060b3038 and 9e3aca42 (origin/main). The head is a merge of main into the reviewed commit.
- `git diff 060b3038 55e215b0 -- <the PR's 8 files>`: exactly one file differs, `plugins/kipi-core/.claude-plugin/plugin.json`, one line, `"version": "1.13.70"` to `"1.13.72"`. Main's value is 1.13.71 (`git show origin/main:plugins/kipi-core/.claude-plugin/plugin.json`), so 1.13.72 is a hand-resolved conflict value, not text taken from main. The other 8 files in the whole-range diff are main's own (#840), none in the PR's list.

Not verified: that a merge route exists. No script copies an approval across a main merge (grep for round cap, stale approval, re-attest and carry the verdict over scripts, rules and docs found only `receipt-carry-approval.sh`, receipt-only).

## Contributing factors

- Two PRs in flight both bumped one version line, so a main merge was certain once #840 landed.
- The auto-merge was armed at 21:17, after round 2 and before the approval on the final head. It is harmless here but shows the arming is not tied to the head it waits on.
- The cap counts rounds, with no notion of "the delta since the approved sha holds no PR-owned change".
- `cap-ladder.py` (nightly 04:40) takes a capped PR, but its rungs are rca, runner and rescope. None re-attests an approval, so for this shape it would run an RCA and a runner on a PR that needs no code change.

## Fixes shipped

- Surface fix: none yet. A merge needs a green `kipi/reviewer-approved` on 55e215b0, which needs a route that does not exist.
- Structural fix: a re-attest mode in `receipt-carry-approval.sh` (new delta kind) that carries an APPROVE onto a head when the PR-owned files are byte-identical to the approved sha. Not built: the identity check failed on one line (see action item 1), so per the brief nothing was built or merged.

## Recurrence

- rca-stall-sweep-review-cap-2026-11-08.md: same family (a capped PR with no mover). Its fix was the cap-ladder consumer. That consumer does not cover "approved, then main moved", so the class remains open in a narrower form.

## Action items

- [ ] Decide the one-line delta: the PR's `plugin.json` version differs between the approved head and 55e215b0 (1.13.70 to 1.13.72, hand-resolved). Either the lead rules that a version-line conflict resolution counts as part of a main merge, or the line is reviewed. Owner: the lead's next Sana agent, now.
- [ ] If ruled in: build the re-attest mode as a separate small PR, red test first (head with identical PR-owned files gets the carry; a head with a differing PR-owned file, a non-ancestor reviewed sha, a non-success verdict, or an existing real verdict on the head does not), reviewed with `KIPI_FLEET_API_KEYS=0 kipi review <n> --repo /Users/assafkipnis/projects/kipi-system --post`. Owner: Sana. Type: code.
- [ ] Teach `cap-ladder.py` to try the re-attest before rung 1 when the capped PR's last approval is on an ancestor of its head. Owner: Sana. Type: code.
- [ ] Merge main into a PR branch before the final review round, not after, when another open PR touches the same version line. Owner: Sana (worker prompt for sana/ lanes). Type: process.

## Lessons

- A green approval belongs to a sha. Any push after it, even a clean merge of main, starts the verdict over.
- The cap counts usable rounds; a 0 byte aborted file is not one.
- Re-attesting an approval needs a code identity check on PR-owned files. A sentence in a comment is not one.
