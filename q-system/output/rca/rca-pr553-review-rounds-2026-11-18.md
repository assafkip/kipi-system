# RCA: consulting PR #553 did not converge in three review rounds (the exporter kept publishing "the branch")

**Date:** 2026-11-18
**Trigger:** round 3 (the cap) on head 49d4e003 returned REQUEST CHANGES. Reviews: `~/.config/kipi/pr-reviews/assafkip_ASK_AI_consultant__pr-553-20261112-230822.md`, `-20261112-232221.md`, `-20261118-101711.md`.
**Surface-fix commit:** 49d4e003 (round 1 fix), 16df153c is a merge
**Structural-fix commit:** pending (this branch, see Fixes shipped)

## What happened

- ASK-4726 made the fleet updater run consulting's declared `.kipi-post-sync` step. That step is `export_voice_loop.py --write --commit`, which pushes to the PUBLIC repo with nobody watching.
- The updater side merged in kipi-system (#785, #787). The consulting side is #553 and is not on consulting main: `.kipi-post-sync` and the commit path exist only on the PR branch. So #553 is not superseded.
- Three review rounds each found the same kind of hole in the exporter's push, and each fix added another check on the mirror's state instead of changing what gets pushed.

## Surface symptom

Findings by round (from the three review files):

- Round 1 (BLOCK): "The retry push ... pushes any local commit in the mirror, including a human's unpushed scratch commit, to the PUBLIC repo" (`export_voice_loop.py:1059`).
- Round 2: "unpushed_foreign_commits runs before the write while the push runs after the mirror's whole test suite, so a commit landing in that window is published ... with exit 0" (`:1143`). Plus: a stray `.DS_Store` refuses before the write, so the engine is never exported (nonblocking).
- Round 3: the same window finding, "repro re-run live on unchanged code". New: `unpushed_foreign_commits` returns `[]` when `git log @{u}..HEAD` fails, and with `push.autosetupremote=true` the push then succeeds and publishes a human's commit. Plus: `git add -- owned` is path-scoped but `git commit` has no pathspec. The stray-file refusal came back a second time.

## Surface root cause

`push_mirror()` runs `git push -q`, which pushes the mirror's checked-out branch to its upstream. Whatever sits on that branch goes public, including a commit that landed after the last look.

## Structural root cause

### Root cause #1: the guard inspected mutable shared state, not the thing being pushed
type: implicit-contract

The mirror `~/projects/voice-loop` is a checkout humans and other jobs also use. The design asked "is the mirror clean and not ahead?" at one moment (before the write), then pushed "the branch" at a later moment (after a pytest run of unknown length). Any check on that state has a window. Round 1 closed one reader of the state (ahead-of-upstream), round 2 named the window, round 3 found a second reader that fails open (`@{u}` missing). Every fix was another filter on ambient state, so every round found the next gap. A push of a branch name cannot be made safe by checks that do not read what the push will send.

### Root cause #2: a policing refusal that the founder had already ruled out
type: process

The updater side was ruled "Shape B" on 2026-11-13: the step is not policed; the safety is that only planned paths are ever staged (`c0f94562`, test case 7). The exporter kept a pre-write refusal on any foreign file in the mirror. It appeared as a nonblocking finding in rounds 2 and 3 and was left: a stray untracked file stops the engine export and `kipi-update.sh` rolls consulting's config half back on every sweep. Path-scoped staging and commit already stop the stray from being published, so the refusal protects nothing and costs the export.

### Root cause #3: tests asserted refusals, not the pushed bytes
type: missing-test

The suite checked "exit 2 and the message" for each guard. No test drove the window (a commit landing after the guard) or the `@{u}`-missing case, so each round's reviewer found by hand what a test could have held.

## Verification

Instrument: the reviewers' repros rebuilt as tests against throwaway repo pairs (`automation/test_export_voice_loop_commit.py`, tmp dirs only).

- Ran the 5 new tests against 49d4e003 before the fix: 5 failed (stray file, index-staged file, commit landing during the mirror tests, commit landing after the pin, no upstream plus `push.autosetupremote`).
- Ran them after the fix at 2447f212: `12 passed`. Neighbour files: published 17 passed, sender_lookup and usage_ledger 9 passed.
- Negative self-test, two mutants: sending `HEAD` instead of the pinned sha: 1 failed (the window test). Replacing the subject check with `if False:`: 3 failed.
- Fresh hand review on the delta: see the PR for the verdict.

## Contributing factors

- Each round fixed the named line, not the class, and a push-side review reads the delta only (iteration-speed rule 11), so the class was never re-derived.
- The mirror is shared with humans, so "clean" is never a stable fact.
- Same finding in two consecutive rounds (the window, the stray refusal) was not treated as a signal to change the shape.

## Fixes shipped

- `publish_head()` in `automation/export_voice_loop.py` sends one pinned sha as `<sha>:refs/heads/<default>`. Just before sending it lists `origin/<default>..<sha>` and refuses unless every commit has this exporter's subject and touches only planned paths. Any git failure refuses.
- The commit takes the planned paths as a pathspec, so an index-staged stray is not committed.
- The pre-write stray-file and foreign-commit refusals are removed (`foreign_dirty`, `unpushed_foreign_commits`).
- A write that restores a planned file to HEAD is a clean no-op, and "committed and pushed" prints only when a commit was made.

## Action items

- [x] Sana (this agent): ship the shape change on the PR branch, red tests first (done, 2447f212).
- [ ] Sana (this agent): one fresh hand review on the delta; the round cap needed KIPI_REVIEW_MAX_ROUNDS=4 once, as the script documents.
- [ ] Sana: if the fresh review still requests changes, stop and report with the finding class.
- [ ] Sana: record the decision and reason on ASK-4726.

## Lessons

- When the thing sent is decided at push time, the check must read exactly that object at that time. A commit sha is immutable; a branch name is not.
- The same finding in two rounds means the shape is wrong. Change the shape, not the line.
- A rule already ruled on one side (no policing) applies to the paired side. Check the sibling's ruling before adding a refusal.
