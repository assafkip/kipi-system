# RCA: three Codex rounds on PR #615 each found a new shell spelling that defeats hook identity

**Date:** 2026-11-06
**Trigger:** the 3-round Codex cap (iteration-speed rule 6) on kipi-system PR #615, ASK-3685
**Surface-fix commit:** fc10fb6c (the round-3 `cd` input, red then green)
**Structural-fix commit:** fc10fb6c (one canonical spelling earns path identity; the bare-relative branch is gone)

## What happened

PR #615 lets an instance with no settings-template.json edit .claude/settings.json through the apply engine. That rests on a premise: kipi-settings-merge.py keeps instance-added hooks on every update. Round 1 showed the premise was false (identity was the script basename, so a colliding or retired name dropped an instance hook). Rounds 2 and 3 each found a new command spelling that broke the fix from the round before. Round 3 did not return a clean verdict, so the loop stops here.

## Surface symptom

Codex verdicts, in order (logs under the session scratchpad, codex-engine-r1/r2/r3.txt.log):

- r1 high: `q-inst/memory_autocapture.py` retired with the skeleton script of the same basename.
- r2 high: `q-inst/not-q-system/token-guard.py` read as skeleton-owned (substring test); `"$D/q-system/.q-system"/token-guard.py` read as instance-owned (quote split).
- r3 high: `cd "$CLAUDE_PROJECT_DIR/q-system" && python3 .q-system/token-guard.py` reads as instance path `.q-system/token-guard.py`, so the skeleton guard is kept twice.
- r4 (handoff agent, on fc10fb6c, the opposite direction): high, `$CLAUDE_PROJECT_DIR/q-inst/custom.memory_autocapture.py` read as the retired `memory_autocapture.py` (no dots in the file-name pattern), so a canonical instance hook was dropped; medium, the `.` in `python3 "$CLAUDE_PROJECT_DIR/q-inst/token-guard.py" .` read as the source builtin (position-blind word check), so the hook deduped away.

## Surface root cause

`_script_identity()` in kipi-settings-merge.py treats any bare relative path as project-relative. A preceding `cd` in the same command changes the working directory, so the path is not project-relative and the ownership call is wrong.

## Structural root cause

### Root cause #1
type: implicit-contract

Hook identity is derived by regex from free-form shell text. Shell has unbounded ways to spell one path (quotes, `cd`, variables, subshells), so each fix closed one spelling and the next review found another. The loop was testing guesses about spellings instead of narrowing what is accepted.

### Root cause #2
type: missing-test

The merge had no test of instance-owned hooks at all before this PR. Its tests only covered the skeleton fossil dedup and the retired list, so the "instance hooks survive" premise in its own docstring was never pinned.

## Verification

- Old vs new merge over all 13 registered instances that have a settings.json: 0 merged hook sets differ (measured this session), so no live instance is affected by rounds 1 to 3.
- `test-settings-merge.sh` and `test-apply-claude-changes.sh` (146/0) are green on branch head 44b66a8c.
- Round 4 (handoff agent, fc10fb6c): the round-3 input and a 20-row grammar table were added to test-settings-merge.sh. Red on 0f1f7536: the merge kept 2 token-guards, and 12 of 14 out-of-grammar spellings got path identity. Two of those were doubling routes no review had named: `$CLAUDE_PROJECT_DIR//q-system/...` and `$CLAUDE_PROJECT_DIR/$SUB/...`. Green on fc10fb6c, 6 of 6 blocks; test-apply-claude-changes.sh 146 passed, 0 failed.
- mutate.py, 5 of 5 KILLED, each applied once with a moved digest and restored: the `cd` check off, `cd` dropped from the word set, the anchor-write check off, a leading slash allowed, the path charset opened.
- Fleet re-measure on fc10fb6c, in memory only: 14 registered instances have a settings.json (13 when the RCA was opened). Old vs new merge differ in 0 of them. All 17 live path-identity hooks keep it, and every one uses the canonical spelling.
- Round 5 (a0c4fddc): both round-4 inputs added as a merge block that requires both hooks to survive, plus 8 grammar rows. Red on fc10fb6c, green on a0c4fddc, 7 of 7 blocks; apply suite 146 passed, 0 failed. mutate.py on a green baseline: 11 of 11 KILLED, each applied once. Fleet: 0 of 14 differ, 17 of 17 path-identity hooks kept.

## Contributing factors

- The bare-relative-path branch was added for completeness, not because any real hook used it. The case gate and gate-draft hooks both use the `$CLAUDE_PROJECT_DIR/<rel>` form.
- Each round fixed exactly the reported spelling instead of shrinking the accepted grammar.
- The first narrowing (fc10fb6c) tested the refused side with 14 rows and the accepted side with 6 live spellings. Its tokenizer did not implement its own grammar: dots were legal in the path charset but not in the file-name pattern, and a builtin's name was refused even as an argument.

## Fixes shipped

- Surface fix (fc10fb6c): the round-3 spelling now dedupes, because a relative path never earns path identity.
- Structural fix (fc10fb6c): the parser accepts one spelling and refuses the rest. Path identity needs a token that starts with `$CLAUDE_PROJECT_DIR/` or `${CLAUDE_PROJECT_DIR}/` and goes on in plain path characters. It also needs a command that never moves the working directory (cd, pushd, popd), never runs text as code in the shell (source, ., eval), and only reads CLAUDE_PROJECT_DIR. Anything else keeps basename identity and fails toward dedup. This is narrower than the handoff's recommendation, which restricted only the anchor and `cd`.
- Accept-side fix (a0c4fddc): dots are part of a file name, and a state word counts only as a command name (the first word after the POSIX command prefix, an opening reserved word, or the builtin/command wrapper), so a builtin's name used as an argument no longer refuses a canonical hook.

## Recurrence

<!-- rca-recurrence-skip -->
No earlier RCA in this directory covers hook identity in kipi-settings-merge.py.

## Action items

- [x] Add the round-3 `cd` input to test-settings-merge.sh, show it red; owner: Sana (handoff agent); type: test
- [x] Narrow path identity to the canonical `$CLAUDE_PROJECT_DIR/<rel>` form with no `cd`; drop the bare-relative branch; owner: Sana (handoff agent); type: code
- [ ] Run Codex round 4 on PR #615 from a fresh agent; merge only on a clean verdict; owner: Sana (handoff agent); type: process

## Lessons

- When a parser of free-form text loses a review round to a new spelling, shrink the accepted grammar; do not add the next spelling.
- A premise a feature rests on ("the merge keeps instance hooks") needs its own test before the feature ships.
- A narrowed grammar has two edges. Test the accepted side as hard as the refused side, with inputs the live data does not happen to contain.
