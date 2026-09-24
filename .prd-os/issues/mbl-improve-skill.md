---
id: mbl-improve-skill
title: The improve skill with an explicit corpora contract and the shared roadmap classifier
status: closed
priority: p2
parent_prd: prd-morning-brief-learns-2026-09-01
allowed_files:
  - plugins/kipi-core/skills/improve/SKILL.md
  - plugins/kipi-core/skills/improve/scripts/improve_ground.py
  - plugins/kipi-core/skills/improve/scripts/test_improve_ground.py
  - q-system/.q-system/capability/expected_tests/plugins__kipi-core__skills__improve__scripts__test_improve_ground.py.json
  - CLAUDE.md
  - plugins/kipi-core/.claude-plugin/plugin.json
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
required_checks:
  - python3 -m pytest -q plugins/kipi-core/skills/improve/scripts/test_improve_ground.py
required_reviews: []
bypass_check: "python3 -m pytest -q plugins/kipi-core/skills/improve/scripts/test_improve_ground.py -k 'corpora or already_built'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-morning-brief-learns-2026-09-01 finding=finding-11 at=2026-09-01T22:00:59Z -->

# The improve skill with an explicit corpora contract and the shared roadmap classifier

## Context

Parent PRD: `.prd-os/prds/prd-morning-brief-learns-2026-09-01.md`

## Acceptance

improve_ground.py reads KIPI_LESSONS_CORPORA (colon-separated directories; default: this instance's q-system/lessons resolved relative to the script) and reports each corpus as read (with count) / missing / unreadable in its output; nothing hardcodes a sibling checkout. RED first: (1) with one missing corpus the verdict still prints and names it missing; (2) 'risk-scored auto-merge' returns already-built naming review-tier.py; (3) any case the roadmap classifier calls roadmap or unknown returns skip with that reason (uses roadmap_scope.py by import, no second classifier). SKILL.md carries a ## Changelog header. /improve is listed in CLAUDE.md commands.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] The improve skill with an explicit corpora contract and the shared roadmap classifier (SKILL.md + improve_ground.py; a corpus is `read` only when the engine consumed it, an unopenable file marks it unreadable, adopt cites only what was read, no readable corpus is skip; /improve registered on the /q-draft line of CLAUDE.md; kipi-core 1.9.2 via a recorded amendment; 15 tests red-first; mutation proof in the closing commit; 3 Codex findings accepted and patched)

## Amendments

### 2026-09-01T23:41:21Z
Reason: Same gate as mbl-changelog-convention: the plugin-version-bump pre-commit check refuses any change under plugins/kipi-core without a plugin.json bump, and the PRD manifest omitted plugins/kipi-core/.claude-plugin/plugin.json. Release state is Sana's call per the founder's routing note; recorded here, kipi-core 1.9.1 -> 1.9.2.

Before:
- allowed_files: ['plugins/kipi-core/skills/improve/SKILL.md', 'plugins/kipi-core/skills/improve/scripts/improve_ground.py', 'plugins/kipi-core/skills/improve/scripts/test_improve_ground.py', 'q-system/.q-system/capability/expected_tests/plugins__kipi-core__skills__improve__scripts__test_improve_ground.py.json', 'CLAUDE.md']
- required_checks: ['python3 -m pytest -q plugins/kipi-core/skills/improve/scripts/test_improve_ground.py']
- disallowed_files: ['.claude/**', 'plugins/prd-os/**', '.prd-os/**', 'q-consult/**']

After:
- allowed_files: ['plugins/kipi-core/skills/improve/SKILL.md', 'plugins/kipi-core/skills/improve/scripts/improve_ground.py', 'plugins/kipi-core/skills/improve/scripts/test_improve_ground.py', 'q-system/.q-system/capability/expected_tests/plugins__kipi-core__skills__improve__scripts__test_improve_ground.py.json', 'CLAUDE.md', 'plugins/kipi-core/.claude-plugin/plugin.json']
- required_checks: ['python3 -m pytest -q plugins/kipi-core/skills/improve/scripts/test_improve_ground.py']
- disallowed_files: ['.claude/**', 'plugins/prd-os/**', '.prd-os/**', 'q-consult/**']
