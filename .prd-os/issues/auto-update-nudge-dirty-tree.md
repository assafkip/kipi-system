---
id: auto-update-nudge-dirty-tree
title: auto-update nudge fires on a dirty tree (remove dead pull-era skip)
status: closed
priority: p2
parent_prd: prd-goal3-cleanup-2026-06-20
allowed_files:
  - q-system/hooks/auto-update.sh
  - q-system/.q-system/scripts/test/test-auto-update-nudge.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-auto-update-nudge.sh
required_reviews: []
bypass_check: "bash q-system/.q-system/scripts/test/test-auto-update-nudge.sh"
---
<!-- generated-by: prd_split.py prd=prd-goal3-cleanup-2026-06-20 finding=finding-1 at=2026-06-20T02:24:41Z -->

# auto-update nudge fires on a dirty tree (remove dead pull-era skip)

## Context

Parent PRD: `.prd-os/prds/prd-goal3-cleanup-2026-06-20.md`

## Acceptance

Delete the dirty-tree skip block (lines 57-62) in full, including its in-block sentinel touch; nudge emits regardless of working-tree state; test asserts nudge fires on a dirty fixture and exits 0; sentinel throttle preserved; no auto-pull reintroduced.
