---
id: lessons-validator
title: Allowlist validator for q-system/lessons/, wired PostToolUse in the skeleton .claude/settings.json: exit 2 on kind not in {pattern,methodology}, missing required field, any frontmatter key outside {id,kind,title,date}, or title matching the client-token denylist; pair per skill-hook-pairing
status: closed
priority: p1
parent_prd: prd-cross-instance-learning-2026-06-19
allowed_files:
  - q-system/.q-system/scripts/lessons-validator.py
  - q-system/.q-system/scripts/test/test-lessons-validator.sh
  - .claude/settings.json
  - .claude/rules/skill-hook-pairing.md
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-lessons-validator.sh
required_reviews: []
bypass_check: "bash q-system/.q-system/scripts/test/test-lessons-validator.sh"
---
<!-- generated-by: prd_split.py prd=prd-cross-instance-learning-2026-06-19 finding=finding-8 at=2026-06-19T23:50:26Z -->

# Allowlist validator for q-system/lessons/, wired PostToolUse in the skeleton .claude/settings.json: exit 2 on kind not in {pattern,methodology}, missing required field, any frontmatter key outside {id,kind,title,date}, or title matching the client-token denylist; pair per skill-hook-pairing

## Context

Parent PRD: `.prd-os/prds/prd-cross-instance-learning-2026-06-19.md`

## Acceptance

- [ ] `q-system/.q-system/scripts/lessons-validator.py`: given a file path, self-scope to `q-system/lessons/` (fast-exit 0 for files outside it and for `README.md`). Parse YAML frontmatter. Exit 2 (BLOCK) when: `kind` not in {pattern, methodology}; any of {id, kind, title, date} missing; ANY frontmatter key outside {id, kind, title, date} present (allowlist); or `title` matches the client-token denylist (`KTLYST|ktlyst|CISO|re-breach|Assaf|/Users/`). Exit 0 for a valid lesson. stdlib only.
- [ ] Wired as a PostToolUse(Edit|Write) hook in the skeleton's `.claude/settings.json` (guards founder writes; instances are read-only so it is moot there).
- [ ] `.claude/rules/skill-hook-pairing.md` records the lessons-validator pairing in its wired-pairings list.
- [ ] `test-lessons-validator.sh` negative tests: kind=scar -> exit 2; an extra frontmatter key -> exit 2; a title containing a client token -> exit 2; a missing required field -> exit 2; a file outside `lessons/` -> exit 0; a valid kind=pattern lesson -> exit 0.
- [ ] required_check passes (`bash q-system/.q-system/scripts/test/test-lessons-validator.sh`).
