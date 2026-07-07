# Token-guard hook fixes (dead PostToolUse leg + silent warnings)

**What/why:** Hook review 2026-07-02 confirmed three defects. (1) token-guard.py's
PostToolUse leg is wired nowhere — the successful-edit spiral reset and commit
reset "Wiring A" are dead code, so the 3rd successful Edit to one file falsely
blocks. (2) `warn()` emits top-level `{"additionalContext"}` from PreToolUse,
which Claude Code ignores (docs: must be nested under `hookSpecificOutput` with
`hookEventName`) — all 6 warnings have never reached the model. (3) Fleet
template `|| true` fix (ef37dcd) not yet propagated; `kipi update` closes it.

**Approach (founder-approved):** fix 1+2 in one pass, then `kipi update`.

**Files to touch**
- `q-system/.q-system/token-guard.py` — warn() nested hookSpecificOutput form
- `settings-template.json` — new PostToolUse group `Edit|Write|MultiEdit|Bash`
  with token-guard (if-then form)
- `.claude/settings.json` — same group (bare form, skeleton style)
- `q-system/.q-system/scripts/test/test-token-guard-template-wiring.sh` — assert
  >=3 wirings incl. PostToolUse w/ Edit+Write+Bash matcher; also statically check
  the skeleton settings.json events
- `q-system/.q-system/scripts/test/test-token-guard-warn-shape.sh` — NEW: warn
  output must parse as hookSpecificOutput/PreToolUse/additionalContext

**Acceptance criteria**
- [x] Extended wiring test shown FAILING before the settings edits (2 wirings)
- [x] Warn-shape test shown FAILING before the warn() edit (top-level key)
- [x] Both tests PASS after fixes
- [x] PostToolUse leg proven live: simulated PostToolUse Edit success clears
      edit_targets in the cache file
- [x] `kipi update` run; instances regenerate settings with all three wirings

**Patterns to follow:** test extracts REAL command strings json-aware (existing
test's own convention); negative self-test before fix (fable-discipline);
template edited alongside settings.json (settings-template-sync scar).
