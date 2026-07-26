---
id: issue-updater-one-plugin-answer-2026-07-26
title: One answer to what is a plugin
status: open
priority: p1
parent_prd: prd-updater-consolidation-2026-07-26
allowed_files:
  - kipi-update.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh
  - bash q-system/.q-system/scripts/test/test-kipi-update-build-artifacts.sh
  - python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design
required_reviews: []
bypass_check: "test \"$(grep -c 'SCRIPT_DIR/plugins' kipi-update.sh)\" -eq 1"
---
<!-- generated-by: prd_split.py prd=prd-updater-consolidation-2026-07-26 finding=finding-7 at=2026-07-26T05:57:44Z -->

# One answer to what is a plugin

## Context

Parent PRD: `.prd-os/prds/prd-updater-consolidation-2026-07-26.md`

## Acceptance

Runs FIRST. SKELETON_PLUGIN_ROOT defined once; managed_plugin_names and is_managed_plugin_path are the only deciders; the staging enumeration is re-rooted per managed plugin and :301's [ -d ] guard is deleted; the three behaviour-identity cases (loose file under plugins/, dangling top-level symlink, symlink-to-real-directory) are each demonstrated unchanged before and after; no test added; baseline unchanged.
