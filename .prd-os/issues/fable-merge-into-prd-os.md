---
id: fable-merge-into-prd-os
title: Fold fable-discipline into prd-os as its execution-discipline layer
status: in-progress
priority: p0
parent_prd: prd-fable-discipline-2026-07-04
allowed_files:
  - plugins/prd-os/skills/**
  - plugins/prd-os/hooks/hooks.json
  - plugins/prd-os/scripts/export-fable-mirror.sh
  - plugins/prd-os/tests/**
  - plugins/kipi-core/skills/fable-discipline/**
  - plugins/kipi-core/hooks/hooks.json
  - plugins/kipi-core/.claude-plugin/plugin.json
  - plugins/kipi-dsse/commands/issue-start.md
  - .claude/rules/fable-discipline-auto-invoke.md
  - .claude/rules/rca-mode.md
  - .claude/rules/skill-hook-pairing.md
  - .claude/rules/wiring-check.md
  - .claude/rules/no-orphan-findings.md
  - .claude/rules/quick-plan.md
  - CLAUDE.md
  - settings-template.json
disallowed_files: []
required_checks:
  - pytest -q plugins/prd-os/tests
  - bash plugins/prd-os/scripts/export-fable-mirror.sh --check
  - bash -c '! grep -rn "kipi-core/skills/fable-discipline" .claude/rules/ CLAUDE.md'
required_reviews: []
bypass_check: "bash -c 'grep -q fable-discipline-lint plugins/prd-os/hooks/hooks.json && ! grep -q fable-discipline-lint plugins/kipi-core/hooks/hooks.json'"
---
<!-- generated-by: prd_split.py prd=prd-fable-discipline-2026-07-04 finding=finding-2 at=2026-07-04T01:45:32Z -->

# Fold fable-discipline into prd-os as its execution-discipline layer

## Context

Parent PRD: `.prd-os/prds/prd-fable-discipline-2026-07-04.md`

## Acceptance

Skill content lives in the prd-os plugin, loaded at issue-start; quick-plan fast path still loads it for non-PRD work (load-path proof required: verify the marketplace clone serves the merged copy, not this repo's plugins/). fable-discipline-lint wired in prd-os hooks.json, removed from kipi-core hooks.json, settings-template-sync-check green. All cross-referencing rules updated; no rule refers to fable-discipline and prd-os as separate peers. export-fable-mirror.sh exists with --check mode; founder pushes the mirror manually.
