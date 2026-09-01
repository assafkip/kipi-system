---
id: mbl-improve-skill
title: The improve skill with an explicit corpora contract and the shared roadmap classifier
status: in-progress
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
- [ ] The improve skill with an explicit corpora contract and the shared roadmap classifier
