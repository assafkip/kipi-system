---
id: crpr-consulting-fossil-cleanup
title: Delete consulting frozen canonical tree and its two council fossils
status: open
priority: p1
parent_prd: prd-canonical-read-path-repair-2026-08-22
allowed_files:
  - q-system/.q-system/scripts/test/test-canonical-fossil-absent.sh
disallowed_files:
  - .claude/**
  - plugins/**
  - .prd-os/**
required_checks:
  - bash q-system/.q-system/scripts/test/test-canonical-fossil-absent.sh
required_reviews:
  - runtime-owner
bypass_check: "bash q-system/.q-system/scripts/test/test-canonical-fossil-absent.sh"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-canonical-read-path-repair-2026-08-22 finding=finding-25 at=2026-08-22T20:07:44Z -->

# Delete consulting frozen canonical tree and its two council fossils

## Context

Parent PRD: `.prd-os/prds/prd-canonical-read-path-repair-2026-08-22.md`

## Acceptance

RUNS LAST, after crpr-unhook-dead-canonical-consumers has shipped. SCOPE LIMIT, stated plainly (finding-1, finding-26): the issue runner receipts paths in THIS repo only, so it cannot authorize or receipt the consulting deletions. The kipi-system deliverable is the checker; the deletions are performed in /Users/assafkipnis/projects/consulting as tracked git rm commits and are PROVED by this checker. The checker must not be able to pass vacuously (finding-25): an exit 0 body must fail its own negative self-test, so it takes the consulting path as an argument, refuses if that path does not exist, asserts the 10 tracked files under q-system/canonical/ are gone, asserts q-consult/canonical/ still has its 22 files, and asserts the two instance-owned council fossils (.claude/skills/council/ SKILL.md plus workflows/quick.md and workflows/debate.md, and the orphaned .claude/skills/workflows/ pair) no longer name the dead tree. Those .claude/skills/ copies are NOT covered by config_source_manages (kipi-update.sh:1279-1296) so they persist untouched; fixing only the plugin copy leaves two live wrong copies. Deleting consulting/q-system/canonical/ is safe from the updater because canonical is in INSTANCE_OWNED_SUBTREES (kipi-update.sh:64). Show the checker RED against consulting BEFORE the deletion. Afterwards run the fleet updater in DRY mode against consulting and confirm no restore and no reversion of skeleton edits.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Delete consulting frozen canonical tree and its two council fossils
