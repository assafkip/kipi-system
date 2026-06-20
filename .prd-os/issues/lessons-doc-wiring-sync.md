---
id: lessons-doc-wiring-sync
title: Sync H0 docs/wiring: add q-system/lessons/ to folder-structure.md tree + Placement Rule, add authoring instruction to README, wire lessons-index.py into skeleton .claude/settings.json; a grep test keeps them in sync
status: closed
priority: p1
parent_prd: prd-lessons-hardening-2026-06-20
allowed_files:
  - .claude/rules/folder-structure.md
  - q-system/lessons/README.md
  - .claude/settings.json
  - q-system/.q-system/scripts/test/test-lessons-doc-wiring.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-lessons-doc-wiring.sh
required_reviews: []
bypass_check: "bash q-system/.q-system/scripts/test/test-lessons-doc-wiring.sh"
---
<!-- generated-by: prd_split.py prd=prd-lessons-hardening-2026-06-20 finding=finding-2 at=2026-06-20T01:18:13Z -->

# Sync H0 docs/wiring: add q-system/lessons/ to folder-structure.md tree + Placement Rule, add authoring instruction to README, wire lessons-index.py into skeleton .claude/settings.json; a grep test keeps them in sync

## Context

Parent PRD: `.prd-os/prds/prd-lessons-hardening-2026-06-20.md`

## Acceptance

- [ ] `.claude/rules/folder-structure.md`: `q-system/lessons/` added to the canonical directory tree (sibling of `canonical/`; contents README.md + `<lesson>.md`) AND a Placement Rule line ("New cross-instance lesson? -> q-system/lessons/<id>.md").
- [ ] `q-system/lessons/README.md`: an explicit authoring instruction ("To add a lesson, create q-system/lessons/<id>.md with frontmatter id/kind/title/date and a HOW-only body; copy single-writer-chokepoint.md as a template").
- [ ] `.claude/settings.json`: the `lessons-index.py` SessionStart line added (mirroring settings-template.json, advisory `2>/dev/null || true` form), valid JSON.
- [ ] `test-lessons-doc-wiring.sh`: asserts folder-structure.md references q-system/lessons/, README.md has the authoring instruction, and .claude/settings.json registers lessons-index.py. Fails if any is missing (keeps the three in sync).
- [ ] required_check passes (`bash q-system/.q-system/scripts/test/test-lessons-doc-wiring.sh`).
