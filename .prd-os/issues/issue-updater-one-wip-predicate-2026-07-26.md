---
id: issue-updater-one-wip-predicate-2026-07-26
title: One predicate for the two untracked-collision guards
status: open
priority: p1
parent_prd: prd-updater-consolidation-2026-07-26
allowed_files:
  - kipi-update.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh
  - bash q-system/.q-system/scripts/test/test-kipi-update-preservation-failure.sh
  - python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design
required_reviews: []
bypass_check: "test \"$(grep -c 'is_instance_wip' kipi-update.sh)\" -eq 3 && grep -q 'refusing to commit unrelated work' kipi-update.sh"
---
<!-- generated-by: prd_split.py prd=prd-updater-consolidation-2026-07-26 finding=finding-2 at=2026-07-26T05:57:44Z -->

# One predicate for the two untracked-collision guards

## Context

Parent PRD: `.prd-os/prds/prd-updater-consolidation-2026-07-26.md`

## Acceptance

Runs THIRD. is_instance_wip is the single predicate behind :452 and :894 ONLY; the tracked-tree check at :808-821 is NOT touched, and why is comment-anchored (a modified TRACKED .pyc must keep failing that guard, else git add -u at :226 stages it into the updater's own commit); the config site passes an empty counterpart so it does not gain the byte-identical carve-out; the q-system site's new build-artifact carve-out is argued no-op case by case; the deferred config-site byte-identical fix is captured in spillover; no test added; baseline unchanged.
