---
id: lessons-consumer-hook
title: SessionStart consumer hook registered in settings-template.json: emit <=20 lesson titles via hookSpecificOutput.additionalContext, resolve project root via session-start.py get_qroot (flat + nested layout), fail-closed never-blocks, no persisted index file
status: closed
priority: p1
parent_prd: prd-cross-instance-learning-2026-06-19
allowed_files:
  - q-system/hooks/lessons-index.py
  - settings-template.json
  - q-system/hooks/test/test-lessons-index.sh
disallowed_files: []
required_checks:
  - bash q-system/hooks/test/test-lessons-index.sh
required_reviews: []
bypass_check: "bash q-system/hooks/test/test-lessons-index.sh"
---
<!-- generated-by: prd_split.py prd=prd-cross-instance-learning-2026-06-19 finding=finding-5 at=2026-06-19T23:50:26Z -->

# SessionStart consumer hook registered in settings-template.json: emit <=20 lesson titles via hookSpecificOutput.additionalContext, resolve project root via session-start.py get_qroot (flat + nested layout), fail-closed never-blocks, no persisted index file

## Context

Parent PRD: `.prd-os/prds/prd-cross-instance-learning-2026-06-19.md`

## Acceptance

- [ ] `q-system/hooks/lessons-index.py`: SessionStart hook. Resolves project root via `CLAUDE_PROJECT_DIR` and a `get_qroot` mirroring `session-start.py` (flat AND nested `q-system/q-system/` subtree layout). Reads `q-system/lessons/*.md` frontmatter titles (excluding README.md), sorts by `date` descending, caps at 20, emits `{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":<titles>}}`. Bodies are NEVER emitted. Fail-closed never-blocks: missing `lessons/` or any error -> no output, exit 0. stdlib only.
- [ ] Registered as a SessionStart hook in `settings-template.json` (so the `kipi-update.sh` hook-union carries it to every instance; NOT the skeleton `.claude/settings.json`, which does not propagate).
- [ ] `test-lessons-index.sh`: titles-only output (asserts a body string is NOT present); the 20-cap holds with 25 lessons; absent `lessons/` -> empty output + exit 0; a nested `q-system/q-system/lessons/` layout is found; README excluded.
- [ ] required_check passes (`bash q-system/hooks/test/test-lessons-index.sh`).
