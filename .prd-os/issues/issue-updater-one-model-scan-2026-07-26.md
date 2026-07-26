---
id: issue-updater-one-model-scan-2026-07-26
title: One scan, two projections, for what the disposable copy contains
status: open
priority: p1
parent_prd: prd-updater-consolidation-2026-07-26
allowed_files:
  - kipi-update.sh
  - q-system/.q-system/scripts/test/test-kipi-update-safety.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh
  - bash q-system/.q-system/scripts/test/test-kipi-update-dry-final-state.sh
  - python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design
required_reviews: []
bypass_check: "test \"$(grep -c 'model_skip_scan' kipi-update.sh)\" -ge 3"
---
<!-- generated-by: prd_split.py prd=prd-updater-consolidation-2026-07-26 finding=finding-1 at=2026-07-26T05:57:44Z -->

# One scan, two projections, for what the disposable copy contains

## Context

Parent PRD: `.prd-os/prds/prd-updater-consolidation-2026-07-26.md`

## Acceptance

Runs SECOND. model_skip_scan is the single cached scan; model_rsync_excludes and model_walk_skips are two named projections of it, neither derived from the other; .git is in the rsync projection and NOT in the walk projection, with the asymmetry's reason in a comment; a new fixture plants a dangling symlink under the instance's own .git/ and asserts the run still refuses, pinning today's behaviour rather than introducing new behaviour; the submodule carve-out is preserved verbatim; baseline unchanged.
