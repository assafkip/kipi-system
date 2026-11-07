# RCA: three Codex rounds on PR #615 each found a new shell spelling that defeats hook identity

**Date:** 2026-11-06
**Trigger:** the 3-round Codex cap (iteration-speed rule 6) on kipi-system PR #615, ASK-3685
**Surface-fix commit:** pending (round-3 finding handed to a fresh Sana agent)
**Structural-fix commit:** pending

## What happened

PR #615 lets an instance with no settings-template.json edit .claude/settings.json through the apply engine. That rests on a premise: kipi-settings-merge.py keeps instance-added hooks on every update. Round 1 showed the premise was false (identity was the script basename, so a colliding or retired name dropped an instance hook). Rounds 2 and 3 each found a new command spelling that broke the fix from the round before. Round 3 did not return a clean verdict, so the loop stops here.

## Surface symptom

Codex verdicts, in order (logs under the session scratchpad, codex-engine-r1/r2/r3.txt.log):

- r1 high: `q-inst/memory_autocapture.py` retired with the skeleton script of the same basename.
- r2 high: `q-inst/not-q-system/token-guard.py` read as skeleton-owned (substring test); `"$D/q-system/.q-system"/token-guard.py` read as instance-owned (quote split).
- r3 high: `cd "$CLAUDE_PROJECT_DIR/q-system" && python3 .q-system/token-guard.py` reads as instance path `.q-system/token-guard.py`, so the skeleton guard is kept twice.

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
- The round-3 input is not yet a test. It stays unverified until the handoff agent adds it red, then green.

## Contributing factors

- The bare-relative-path branch was added for completeness, not because any real hook used it. The case gate and gate-draft hooks both use the `$CLAUDE_PROJECT_DIR/<rel>` form.
- Each round fixed exactly the reported spelling instead of shrinking the accepted grammar.

## Fixes shipped

- Surface fix: pending. Handed to a fresh Sana agent with the round-3 input.
- Structural fix: pending. Recommended shape: path identity ONLY for one canonical form, a token anchored on `$CLAUDE_PROJECT_DIR/` in a command with no `cd`; every other spelling keeps basename identity (fails toward dedup).

## Recurrence

<!-- rca-recurrence-skip -->
No earlier RCA in this directory covers hook identity in kipi-settings-merge.py.

## Action items

- [ ] Add the round-3 `cd` input to test-settings-merge.sh, show it red — owner: Sana (handoff agent) — type: test
- [ ] Narrow path identity to the canonical `$CLAUDE_PROJECT_DIR/<rel>` form with no `cd`; drop the bare-relative branch — owner: Sana (handoff agent) — type: code
- [ ] Run Codex round 4 on PR #615 from a fresh agent; merge only on a clean verdict — owner: Sana (handoff agent) — type: process

## Lessons

- When a parser of free-form text loses a review round to a new spelling, shrink the accepted grammar; do not add the next spelling.
- A premise a feature rests on ("the merge keeps instance hooks") needs its own test before the feature ships.
