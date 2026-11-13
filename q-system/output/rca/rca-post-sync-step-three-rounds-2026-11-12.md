# RCA: policing an instance's post-sync step reopened the same defect class across four PRs
<!-- voice-lint-skip -->

**Date:** 2026-11-12 (rewritten 2026-11-13 against shipped state)
**Filename note:** the slug says `three-rounds` because the first draft covered PR #780's three rounds only. The name is kept, not corrected, because PR #785's MERGED body cites this exact path; renaming it would leave a dead link in merged history. The scope below is four PRs, not one.

**Trigger:** PR #780 hit the reviewer cap (3 rounds, all REQUEST CHANGES). The same class then reopened on #784 and #787.
**Resolution commit:** 785's merge onto main, `01:11:49Z`, which REMOVED the policing rather than fixing it.
**This branch's commit:** the post-sync step's wall clock and file-redirect (ASK-4726, PR #787).

## What happened

The updater gained a declared post-sync step (ASK-4726): an instance names one command in `.kipi-post-sync`, and the updater runs it after the rsync and before the config commit, so a mirror gate has its derived artifact on disk before the commit it guards.

Four PRs shipped against that one feature. Measured from the PR comment timeline, not from memory:

- **#780** (CLOSED, 3 rounds, all REQUEST CHANGES, 23:16 / 23:32 / 23:47). Round 1: a step writing tracked files outside the synced paths was neither committed nor rolled back. The builder added a pass that read `git status --porcelain`, diffed it against a pre-step copy, and restored each new line. Round 2: a staged write survived it. Round 3: a C-quoted path (space or accent) and a staged rename were reported restored and were not.
- **#784** (CLOSED, 1 round, REQUEST CHANGES, 00:20). The porcelain pass was replaced by a git-tree snapshot. Round 1 found the snapshot skipped gitignored paths under `.claude/`, and that `ps_rollback` left behind directories the step created.
- **#785** (MERGED 01:11:49Z, 2 rounds: REQUEST CHANGES 00:41, APPROVE WITH NITS 00:56). A different shape, on its own branch `sana/ask-4726-b`: the updater does NOT police what the step writes at all. What holds instead is that the config commit stages only `.claude/` and `plugins/`.
- **#787** (OPEN, 2 rounds, both REQUEST CHANGES, 01:10 / 01:46). This PR. Round 1 named three more defects INSIDE the snapshot machinery plus one outside it. Round 2 named this RCA as describing code the branch had since reverted.

**Correction to a merged claim:** #785's body says "#780 and #784 spent six rounds". The measured count is four (3 + 1). Eight rounds total across all four PRs. The merged body is not editable retroactively without rewriting merged history, so the count is corrected here instead.

## Surface symptom

Each round produced a different reproducer against the same question, "undo what the step wrote":

- #780 round 3: `restore rc= 1 stderr= error: pathspec '"R\303\251sum\303\251.md"' did not match any file(s) known to git`, and the committed content stayed clobbered across runs.
- #784 round 1: a step clobbering `.claude/settings.local.json` (gitignored) was neither refused nor restored, and git held no copy of the original.
- #787 round 1: `ps_restore_refs` replayed `for-each-ref`, which omits HEAD, so a refused step that checked out a new branch left the instance on a deleted branch with `git rev-parse HEAD` fatal.

## Surface root cause

Per round, a different parsing or enumeration gap: a porcelain line sliced at offset 3; `git add -A` skipping ignored paths; `for-each-ref` omitting HEAD. Each fix was correct for the shape its reviewer named.

## Structural root cause

### Root cause #1

The feature answered a question it did not have to ask. "What did the step change, and should the updater undo it?" requires the updater to enumerate every way a process can mutate a repository: tracked content, index state, ignored files, refs, HEAD, directories, C-quoted names. That enumeration has no closed form, which is why six of the eight rounds each found a new member of it. The merged shape deletes the question: the step is the instance's own code, trusted the same as its pre-commit hook, and the updater does not undo what it writes.

type: implicit-contract

### Root cause #2

The builder treated each round's finding as the spec for the next commit, so the work converged on patching the enumeration instead of on whether the enumeration was the right instrument. Five commits of snapshot-and-undo machinery were written and then reverted whole by the merge.

type: process

### Root cause #3

The tests asserted per-shape outcomes (one tracked file, an ASCII name) rather than the invariant over a hostile set. A hostile path name, an ignored file, or a moved HEAD could not turn them red until a reviewer named each one.

type: missing-test

## Fixes shipped

Two things, and nothing else. The first draft of this section named five functions and a refusal rule that are not in the shipped code; what is below was read off `kipi-update.sh` on this branch, not off the plan.

- **On main, via #785:** no policing. `kipi-update.sh` runs the declared step with `bash -c`, reports its own stdout and stderr, and refuses the config commit when the step exits non-zero. The bound on blast radius is that the config commit stages only `.claude/` and `plugins/` (case 7 proves it with `git show --name-only`).
- **On this branch (#787):** `ps_run_step` in `kipi-update.sh`, which protects the OTHER instances from one instance's step rather than restricting what that step writes. Three properties, one reproducer each:
  - a wall clock (`POST_SYNC_TIMEOUT`, 600s, overridable by `KIPI_POST_SYNC_TIMEOUT` so the suite proves the deadline in 3s), because a hung step held the sweep forever and every later instance in the registry never synced;
  - the step's output goes to a FILE, not a command substitution, because `$(...)` waits for the write end of the pipe to close and a background child the step leaves behind holds it open after the step exits 0 (measured: 3s of work, 29s of waiting);
  - stdin stays closed, because the instance loop reads the registry from stdin and a step that read it ate the remaining instances while the run still exited 0.

**Not shipped, and named here because the first draft of this RCA claimed it was:** `ps_tree`, `ps_snapshot`, `ps_violations`, `ps_rollback`, `ps_restore_refs`; the one-rule refusal ("a step may add untracked files and write under `plugins/`; any other change is refused"); and the held-snapshot release block. All of those were reverted by this branch's merge of origin/main. The shipped updater refuses NOTHING the step writes.

## Verification

Ran `bash q-system/.q-system/scripts/test/test-kipi-update-post-sync-step.sh` from this worktree: 11 cases PASS, 10 of 10 mutants KILLED, `ALL PASS`.

Red observed before green on both new cases, against the committed updater (`git show HEAD:kipi-update.sh`, which has no wall clock):

```
case 10 against /tmp/ask4726-updater-HEAD.sh: EXIT=1 :: FAIL: case 10 should refuse a step that runs past its deadline
case 11 against /tmp/ask4726-updater-HEAD.sh: EXIT=1 :: FAIL: case 11 waited 29s on a background child of a step that had exited
```

Then against the fixed updater:

```
case 10 ... EXIT=0 :: PASS 10: a step past its deadline is killed, named, and the sweep continues
case 11 ... EXIT=0 :: PASS 11: a background child of a finished step does not hold the sweep
```

One defect in the test file itself, found while re-running it and fixed in the same commit: the command-substitution mutant was written with four `'"'"'` sequences per anchor and shipped one closing quote short, so `bash -n` reported `unexpected EOF while looking for matching` and the WHOLE suite was a parse error rather than a failing assertion. Both anchors are now built in quoted heredocs. A test file that cannot be parsed reports nothing at all, which is indistinguishable from a clean run in a summary.

## Contributing factors

- The reviewer cap (3 rounds) forced a verdict on #780 while the same class kept reopening, and the next PR inherited the machinery rather than the question.
- Each round's counter-citation answered the named shape. `--staged` on #780 round 2 is the clearest instance.
- Reproducing a C-quoted path needs a non-ASCII or spaced name, which no fixture had until round 3 asked for one.
- The branch carried ~500 lines of the reverted machinery, so #787's first review round spent three of its four findings on code that was about to cease to exist.

## Recurrence

- `rca-pr-owner-three-rounds-2026-11-08.md`: action "one authority for the class, not one patch per round" FAILED here. The undo pass was added as a second authority beside the updater's existing rollback, and then patched per round for four rounds.
- This issue is itself the recurrence record for #784 and #785. No separate RCA was written for either, because both are rounds of the one class diagnosed above rather than distinct defects. #784's single round is the third patch of the enumeration; #785 is the first PR that stopped patching it.

## Action items

- [x] Remove the policing rather than patch its enumeration — owner: Sana — code (#785, merged 01:11:49Z)
- [x] Take main for `kipi-update.sh`, `UPDATE.md` and the suite on this branch instead of rebasing the reverted machinery — owner: Sana — code (merge `b3f64ea5`)
- [x] Bound one instance's step so it cannot stop the sweep: deadline, output to a file, closed stdin — owner: Sana — code
- [x] One reproducer per property, red observed before green (cases 9, 10, 11) — owner: Sana — test
- [x] Rewrite this RCA against shipped state, after it described reverted code for one review round — owner: Sana — doc
- [ ] Run one review on PR #787 and merge it — owner: Sana — process

## Lessons

- When a fix needs "undo what a command did", first ask whether the updater has to know. Deleting the question beat every attempt to enumerate its answer, and the enumeration cost six rounds.
- A reviewer finding is a defect report, not a spec. Three of #787 round 1's four findings were defects in code that should not have existed; answering them would have been round seven of the pattern.
- An RCA written mid-branch describes the branch at that moment. When the branch reverts the work, the RCA is a false record until it is rewritten, and it reads exactly like a true one.
- Run `bash -n` on a test file before trusting its verdict. A parse error and a clean pass are both silence.
