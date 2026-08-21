---
id: skill-hook-audit-drop-local-settings
title: Skeleton skill-hook-manifest.json, and stop treating settings.local.json as authoritative wiring
status: open
priority: p0
parent_prd: prd-enforced-claim-verification-2026-08-21
allowed_files:
  - plugins/kipi-core/scripts/skill-hook-audit.py
  - q-system/.q-system/proposals/*.json
  - q-system/.q-system/scripts/test_skill_hook_audit_local.py
disallowed_files: []
required_checks:
  - python3 plugins/kipi-core/scripts/skill-hook-audit.py
  - python3 -m pytest q-system/.q-system/scripts/test_skill_hook_audit_local.py -q
required_reviews: []
bypass_check: "settings.local.json is not read as wiring: grep -c 'settings.local.json' plugins/kipi-core/scripts/skill-hook-audit.py returns only commentary lines, and the audit prints PASS not 'not onboarded'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-enforced-claim-verification-2026-08-21 finding=finding-13 at=2026-08-21T17:23:12Z -->

# Skeleton skill-hook-manifest.json, and stop treating settings.local.json as authoritative wiring

## Context

Parent PRD: `.prd-os/prds/prd-enforced-claim-verification-2026-08-21.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Skeleton skill-hook-manifest.json, and stop treating settings.local.json as authoritative wiring
