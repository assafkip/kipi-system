# Session handoff - 2026-07-02

## Headline

Hooks review found and fixed four token-guard/hook defects, all shipped through
tests-shown-red-first and pushed (128a0cc, 1442219, f852b3e). The guard now
warns before it blocks, successful edits no longer false-block, instances no
longer run the guard 2-3x per call, and the double-wired lints have one owner.

## What shipped today (effort, not outcomes)

1. **token-guard PostToolUse leg wired** (was dead since March, in skeleton
   settings.json + settings-template.json, matcher `Edit|Write|MultiEdit|Bash`).
   Kills the "3rd successful Edit to one file blocks" false positive; commit
   reset Wiring A live.
2. **Warnings reach the model.** warn() emitted top-level `additionalContext`
   from PreToolUse — Claude Code ignores that form. Now nested under
   `hookSpecificOutput`. All six warning tiers observed firing live in-session.
3. **kipi-update merge fixed + extracted** to `kipi-settings-merge.py`: dedup
   by invoked-script basename (template wins) instead of exact command string,
   which had let stale forms pile up — instances were running token-guard 2-3x
   per tool call after the first fleet push. Fleet re-updated, 3 instances
   verified clean.
4. **Lint ownership dedupe through the full gated flow**:
   PRD prd-lint-hook-ownership-dedupe-2026-07-02 → Codex review → issue →
   amend (Codex caught the template's voice-lint/voice-substance-lint
   `|| true` masking; both now if-then) → closeout → archive →
   **sp-700047ff resolved**. kipi-core 1.5.5; marketplace clone pulled and
   verified (0 CLAUDE_PROJECT_DIR refs in its hooks.json).

## Standing state

- 4 gates registered and green: token-guard-template-blocking,
  token-guard-hook-behavior, settings-merge-script-dedup,
  lint-hook-ownership-dedupe.
- Spillover ledger: back to the 9 pre-existing open items (none from today).
- `kipi update` ran twice, 20 updated / 0 failed each.
- Plan checkpoint: `q-system/output/plans/token-guard-hook-conflicts-2026-07-02.md`
  (all boxes checked).
- Memory updated: token-guard-autonomous-runs (3-edit workaround retired;
  commit resets the volume counter).

## Open threads

- Sessions on cached kipi-core 1.5.3/1.5.4 keep the old plugin hooks until the
  cache refreshes; new sessions load 1.5.5. Self-resolving, nothing to do.
- The skeleton session that did this work predates its own PostToolUse wiring;
  it applies from next session start.
- 9 pre-existing spillover items still hold `gates run` RED (by design).
