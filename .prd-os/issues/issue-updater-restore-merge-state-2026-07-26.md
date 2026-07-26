---
id: issue-updater-restore-merge-state-2026-07-26
title: Restore clears merge and rebase state the checkpoint did not record
status: open
priority: p1
parent_prd: prd-updater-consolidation-2026-07-26
allowed_files:
  - kipi-update.sh
  - q-system/.q-system/scripts/test/test-kipi-update-safety.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh
  - bash q-system/.q-system/scripts/test/test-kipi-update-hook-contract.sh
  - python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design
required_reviews: []
bypass_check: "grep -q 'CHERRY_PICK_HEAD' kipi-update.sh"
---
<!-- generated-by: prd_split.py prd=prd-updater-consolidation-2026-07-26 finding=finding-5 at=2026-07-26T05:57:44Z -->

# Restore clears merge and rebase state the checkpoint did not record

## Context

Parent PRD: `.prd-os/prds/prd-updater-consolidation-2026-07-26.md`

## Acceptance

Runs LAST, after the restore chokepoint exists. restore_instance removes MERGE_HEAD, CHERRY_PICK_HEAD, rebase-merge/ and rebase-apply/ when the checkpoint did not record them; a fixture leaves the instance mid-merge on the direct-clone fall-through path (:840-846 has no continue, so bails :1083/:1178 run with MERGE_HEAD set whenever git merge --abort fails), runs the restore, and asserts the NEXT commit has one parent rather than two; the assertion checks commit parents, not `git status`, because status reports clean with MERGE_HEAD set, which is the whole defect.
