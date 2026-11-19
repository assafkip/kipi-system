# RCA: PR #858 used its 3 review rounds on an enforcer's heuristics and a version string that main had already taken

**Date:** 2026-11-18
**Trigger:** the round 3 review of PR #858 (ASK-5359) returned REQUEST CHANGES on a one-line delta: the kipi-core version bump.
**Surface-fix commit:** pending (fresh Sana agent, see Action items)
**Structural-fix commit:** pending

## What happened

PR #858 renamed `/voice-loop` to `/voice-review` and routed the voice skills and agents to the writer lane. Round 1 returned REQUEST CHANGES on the enforcer (a one-file roster). I fixed it in `f883a9f7` and round 2 returned APPROVE WITH NITS. The merge then stopped on `validate`: the plugin version-bump guard failed. I bumped `1.13.74` to `1.13.75` in `b257f884`. Round 3 returned REQUEST CHANGES: main had published `1.13.75` in #855 eleven minutes earlier, so the bump changes nothing against main and the version-keyed cache would keep running the pre-#858 copy.

## Surface symptom

`git diff origin/main HEAD -- plugins/kipi-core/.claude-plugin/plugin.json` printed nothing (identical manifests). `plugin-version-bump-check.py --against origin/main` exited 2 on a simulated squash merge ("kipi-core (version still 1.13.75)") while exiting 0 against the PR's own base.

## Surface root cause

I derived the new version by adding 1 to the version in my branch's manifest (`1.13.74`) and never read the version on `origin/main` at push time. Main had moved to `1.13.75` while the PR was in review.

## Structural root cause

### Root cause #1
The bump gate compares against the PR's base sha, not main's tip. A PR whose base is stale passes the gate with a version main already holds, so CI reports green on a change that will not load.
type: implicit-contract

### Root cause #2
Nothing makes the version bump part of the first push. A PR that touches `plugins/kipi-core/` goes through round 1 and round 2 with no bump, the bump arrives after approval as a separate commit, and a push after approval voids the SHA-bound approval. The bump commit then becomes the only thing round 3 reads, and it is the one thing the earlier rounds never examined.
type: process

### Root cause #3
Round 1 and round 2 spent their findings on `test_writer_lane_entry_points.py`: roster heuristics, whole-file substring matching, copy equality. All real, all fixed or logged. None of the rounds asked whether the shipped payload would load, which is decided by the cache key.
type: missing-test

## Verification

Reviewer's reproduction in the round 3 review: squash-merge simulation onto `origin/main`, then the bump check, exit 2. I confirmed the premise: `git show origin/main:plugins/kipi-core/.claude-plugin/plugin.json | grep version` printed `"version": "1.13.75"`. I have not applied the fix: the cap is 3 rounds and this report hands the fix to a fresh agent.

## Contributing factors

- Main moved four times while #858 was open; a rebase was never part of the loop.
- `plugin-version-bump-check.py --fix` derives patch+1 from the local manifest.
- `runtime-plugin-freshness.py` compares version strings only, so it reports green on a box running old content under a reused version.
- A memory note already said "bump kipi-core first" (PR #839). I did not apply it before the first push.

## Fixes shipped

- Surface fix: pending. Rebase `sana/ask-5359-entry-points` on origin/main, set kipi-core to one above main's tip, push, review only the delta.
- Structural fix: pending, see Action items 2 and 3.

## Recurrence

- <!-- rca-recurrence-skip -->

## Action items

- [ ] Rebase `sana/ask-5359-entry-points` onto origin/main, set `plugins/kipi-core/.claude-plugin/plugin.json` to a version above main's tip read at push time, push, run the round 4 delta review, merge on APPROVE — owner: fresh Sana agent, started by main now — type: code
- [ ] Make `plugin-version-bump-check.py` also compare against the live `origin/main` tip and refuse a version that is not strictly above it; red test first with a stale-base fixture — owner: Sana lane, ticket to be filed by main after #858 merges — type: gate
- [ ] Make `--fix` in the pre-commit hook derive its patch+1 from `origin/main`'s manifest, not the local one — owner: same ticket as the previous item — type: code
- [ ] Add "kipi-core touched: bump above main's tip before the first push" to the Sana start-up checklist file the agent reads — owner: same ticket — type: process

## Lessons

- Read main's version at push time. A branch's own manifest is stale the moment another PR merges.
- Bump before round 1, not after approval: a late push voids the approval and puts the unreviewed line in the next round alone.
- A cache key is part of the payload. When a change ships files under a plugin, ask whether the new files can load before asking whether their text is right.
