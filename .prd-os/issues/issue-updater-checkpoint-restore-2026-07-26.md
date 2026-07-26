---
id: issue-updater-checkpoint-restore-2026-07-26
title: Checkpoint the instance and restore it on every give-up path
status: open
priority: p0
parent_prd: prd-updater-consolidation-2026-07-26
allowed_files:
  - kipi-update.sh
  - q-system/.q-system/scripts/test/test-kipi-update-safety.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh
  - bash q-system/.q-system/scripts/test/test-kipi-update-hook-contract.sh
  - bash q-system/.q-system/scripts/test/test-kipi-update-preservation-failure.sh
  - python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design
required_reviews: []
bypass_check: "test \"$(grep -c -F 'FAIL=$((FAIL + 1))' kipi-update.sh)\" -eq 1"
---
<!-- generated-by: prd_split.py prd=prd-updater-consolidation-2026-07-26 finding=finding-3 at=2026-07-26T05:57:44Z -->

# Checkpoint the instance and restore it on every give-up path

## Context

Parent PRD: `.prd-os/prds/prd-updater-consolidation-2026-07-26.md`

## Acceptance

Runs FOURTH, and re-snapshots its scope with /issue-amend after issue 3 closes. checkpoint_instance runs before the first write and copies untracked CONTENT, not only the path list; all 24 give-up paths route through abandon_instance, so FAIL++ appears exactly once in the file; the reproducer for sp-5f2d2a63 and sp-e244e821 is red before and green after; a fixture proves an untracked file deleted by rsync --delete is restored on the :1000 and :1014 bails, which requires restoring before ARCHIVE_TMP teardown; every new assertion is mutation-checked against a deliberately gutted restore; no git reset --hard and no git clean; wc -l kipi-update.sh < 1253 with no scar comment deleted.
