# RCA: A post-sync step's out-of-scope writes survived three review rounds
<!-- voice-lint-skip -->

**Date:** 2026-11-12
**Trigger:** PR #780 returned REQUEST CHANGES three times; the reviewer cap (3 rounds) was reached.
**Surface-fix commit:** 127a951d (round 2 fix; round 3 findings still open)
**Structural-fix commit:** 232fd89b

## What happened

The updater gained a declared post-sync step (ASK-4726). Round 1 found that a step writing tracked files outside the synced paths was neither committed nor rolled back. The builder added a pass that read `git status --porcelain`, diffed it against a pre-step copy, and restored each new line. Round 2 found a staged write survived it. Round 3 found a path with a space or accent (git C-quotes it) and a staged rename were reported restored and were not.

## Surface symptom

Round 3 reproducer output, from the review: `restore rc= 1 stderr= error: pathspec '"R\303\251sum\303\251.md"' did not match any file(s) known to git`, and the committed file content stayed clobbered across runs.

## Surface root cause

The restore sliced a porcelain line at offset 3 and passed it to `git restore` as a pathspec. Porcelain v1 without `-z` quotes unusual names, and a rename line holds two paths. Round 2's fix added `--staged` to the same line and left the parsing alone.

## Structural root cause

### Root cause #1

Rounds 2 and 3 were both defects in one hand-rolled "undo what the step did" pass. That pass is a second copy of a job git already does (name the changed paths exactly, put them back) and of a job the updater's existing rollback already does. Each round fixed the property its reviewer named, and no test asserted the property itself.

type: implicit-contract

### Root cause #2

The test asserted per-shape outcomes (one tracked file, ASCII name) and a status comparison whose filter hid the one untracked file every case creates. A hostile path name or a leftover untracked file could not turn it red.

type: missing-test

### Root cause #3

The existing rollback is pathspec-scoped to the synced paths by design, so the step's writes anywhere else had no owner. The new pass was bolted on beside it instead of replacing the question "what did the step change" with something git answers exactly.

type: process

## Verification

Ran `bash q-system/.q-system/scripts/test/test-kipi-update-post-sync-step.sh` in the scratch-repo harness: cases 1 to 11 PASS, 15 of 15 mutants KILLED, ALL PASS (about 3.7 minutes). Case 9 runs one step doing every hostile write at once (accented tracked file, staged rename, staged add, untracked files, a nested untracked dir, writes under `.claude/`, an edit of a human untracked file) with exit 0 and exit 3, and compares a before and after fingerprint (HEAD, index, content hash and mode of every tracked and untracked file, stash list). Before the change the same file was red at case 3/4 once `status_of` stopped hiding `.mirror-ok`. The first run of the new mutants found two survivors, "commit after a failed step" and "index change is not a violation"; cases 10 and 11 were added and both are now killed.

## Contributing factors

- The reviewer cap forced a verdict while the same class kept reopening.
- Round 2's counter-citation (`--staged`) answered the named shape, not the class.
- Reproducing a C-quoted path needs a non-ASCII or spaced name, which no fixture had.

## Fixes shipped

- `ps_tree`, `ps_snapshot`, `ps_violations`, `ps_rollback` in `kipi-update.sh`: the pre-step state is a git tree object plus a byte copy of the index; the after-state is read with `git diff-tree -r -z`; restore is `checkout-index` from the old tree plus unlink of added paths. No porcelain line is parsed, no stash entry or ref is created.
- Removed: the `ps_before`/`ps_after`/`ps_new` porcelain diff and the per-line `git restore` loop.
- One rule: a step may add untracked files and write under `plugins/`; any other change to an existing file, any write under `.claude/`, and any index change is refused. A failed step is rolled back the same way, so nothing it created survives.
- Not an option taken: handing refusals to the updater's existing rollback alone. It is scoped to the synced paths and cannot see root-level writes.

## Recurrence

- rca-pr-owner-three-rounds-2026-11-08.md: action "one authority for the class, not one patch per round" failed because the undo pass was added as a second authority beside the existing rollback.

## Action items

- [x] Replace the porcelain undo pass with a git snapshot and `-z` diff — owner: Sana — code
- [x] Property case over hostile names plus cases 10 and 11 for the two surviving mutants — owner: Sana — test
- [x] Make `status_of` see untracked files — owner: Sana — test
- [x] State the step's write rule in UPDATE.md — owner: Sana — doc
- [ ] Run one review on the new PR and merge it (`pr-review-agent.sh`, then auto-merge) — owner: Sana — process

## Lessons

- When a fix needs "undo what a command did", ask whether git can name the change set. If it can, use its NUL output, not text.
- Test the invariant once over the hostile set, not one shape per round.
- A mutant that survives because another layer would have refused anyway needs a fixture with that layer removed.
