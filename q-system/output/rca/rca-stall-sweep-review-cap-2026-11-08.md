# RCA: PR #689 (ASK-4019) reached the 3-round review cap holding an approval it could not merge

**Date:** 2026-11-08 (UTC 2026-11-09)
**Trigger:** pr-review-agent.sh refused round 4 at 02:15:26Z: "PR #689 already has 3 claude review round(s). review cap reached (3); cap-ladder.py takes this PR at its next nightly run."
**Surface-fix commit:** the merge of origin/main on `sana/ask-4019` that carries this file
**Structural-fix commit:** pending, ASK-4128

## What happened

| Round | Head | Verdict | Findings |
|---|---|---|---|
| 1 | eddbc04a | REQUEST CHANGES | 2 major, 2 minor, 1 nit |
| 2 | 46b31f6e (delta) | APPROVE WITH NITS | 3 minor |
| 3 | 7468a224 (delta) | APPROVE WITH NITS | 2 minor, 1 nit |
| 4 | f042a250 | refused by the cap | none |

The findings converged: severity fell each round, and every finding was fixed red-first with a mutant that killed it (23 mutants, none survived). The PR still cannot merge. 7468a224 carries `kipi/reviewer-approved=success`, but it conflicts with main, so it never got a validate run. f042a250 holds the round-3 fixes, has no approval, and the cap blocks a fourth review.

## Surface symptom

```
02:06:57Z  gh pr checks 689         -> no checks
02:15:26Z  pr-review-agent.sh 689   -> REFUSING: ... review cap reached (3)
02:15:xxZ  gh pr view 689 --json mergeable,mergeStateStatus -> CONFLICTING DIRTY
           git merge-tree HEAD origin/main -> CONFLICT (content): Merge conflict in q-system/.q-system/job-checkouts.json
```

## Surface root cause

PR #659 (ASK-3962, pr-owner.py) merged at 01:53:55Z. That was after my 46b31f6e push (its runs were created at 01:52:08Z) and before the 7468a224 push (about 02:03Z). Both PRs add one label at the same line of `job-checkouts.json` `pinned`. From then on this PR was DIRTY, and GitHub creates no pull_request run without a merge ref.

## Structural root cause

### Root cause #1
type: code-defect

pr-review-agent.sh never checks whether the PR can merge (`grep -n 'mergeable\|mergeStateStatus\|DIRTY' pr-review-agent.sh` finds nothing). Round 3 reviewed and approved a DIRTY head, and that approval can never be the merge head. It also spent the cap's last round.

### Root cause #2
type: implicit-contract

The cap counts every round, approved or not. no-orphan-findings.md requires each APPROVE-WITH-NITS minor to be fixed in the change or rejected with a reason. Together, after an approval in round 3, a fix can only land through cap-ladder.py. Nothing states that. I fixed the round-3 minors because the head had to change anyway, and Root cause #1 is why it had to.

### Root cause #3
type: process

Round 2 minor 2 suggested reading "no attempts ledger here" as a fact. I took the reviewer's fix shape without checking the producer. worker_history's docstring says it fails closed, and launchd-health-check.py files an alert for any non-zero exit, so exit 9 already had a consumer. Round 3 found the flip.

## Verification

Ran on the merged tree (origin/main merged into `sana/ask-4019`, `job-checkouts.json` keeps both `com.kipi.pr-owner` and `com.kipi.stall-sweep`):

```
python3 -m pytest q-system/.q-system/tests/test_stall_sweep.py q-system/.q-system/tests/test_hold_label_consumers.py -q
94 passed in 0.17s
python3 q-system/.q-system/scripts/test/test-job-checkouts.py
PASS
python3 q-system/.q-system/scripts/stall-sweep.py --json      (report only, 13.36s)
status red; 78 idle items name a consumer; 57 in 7 gaps: no-project 37, started-no-history 8,
blocked:capability 7, alert-lane-refused 2, owner:assaf 1, outside-fleet-project 1,
pr-outside-pr-owner 1 (assafkip/kipi-investigations#6, idle 3598h); 14 skipped; incomplete []
```

That last run is the first with pr-owner.py on the tree. `pr_owner_set()` read it without error. Its calls match the merged API: `fleet_repos(ROOT)` returns `(name, path, remote)` rows, and `slug_for(ROOT, path, targets)` takes those arguments.

## Contributing factors

- I read "no checks" on a pushed head as a GitHub delay for 9 minutes before checking mergeability.
- The lane rebased once at the start and never rechecked main while 4 other PRs merged (#659, #669, #679, #680).
- The reviewer's `--delta` base comes from its verdict record. So a delta taken after a merge from main also covers the merged PRs. The next round has to scope by hand.

## Fixes shipped

- Surface fix: origin/main merged into `sana/ask-4019`, conflict resolved by keeping both pinned labels. The PR is mergeable again, so CI runs on the new head.
- Structural fix: pending, ASK-4128 (pr-review-agent.sh refuses a DIRTY PR, and that refusal does not count toward the cap).

## Action items

- [ ] Review the round-3 fixes and the conflict resolution: `git diff 7468a224 f042a250` plus `git show <merge> -- q-system/.q-system/job-checkouts.json`, not a plain `--delta` (which includes #659, #669, #679, #680). Owner: the fresh Sana agent the orchestrator starts for round 4, after cap-ladder.py (com.kipi.cap-ladder, 04:40) takes PR #689. Type: process.
- [ ] After merge: `bash q-system/.q-system/scripts/install-plist.sh com.kipi.stall-sweep` from a fresh worktree at origin/main, then `launchctl kickstart gui/501/com.kipi.stall-sweep`, then read `~/.config/kipi/logs/stall-sweep.out.log`. Expected: 4 no-builder gaps against a cap of 3, so 3 tickets are filed and the run exits 1. The next hourly run files the fourth. Owner: the same Sana agent. Type: code.
- [ ] pr-review-agent.sh refuses a DIRTY PR, and that refusal does not count toward the cap. Owner: the fleet worker (com.kipi.dispatch) on ASK-4128 (Todo, DoR written). Type: gate.

## Lessons

- A pushed head with no check runs after 2 minutes is a mergeability question first: run `gh pr view --json mergeable` before waiting.
- An APPROVE-WITH-NITS in round 3 can be closed in this lane only by rejecting the minors with a reason. A fix needs the cap ladder.
- Check a reviewer's suggested fix against the producer's own code and its consumers before taking it.
