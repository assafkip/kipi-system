---
id: crpr-skeleton-resolves-live-canonical
title: Council and wiring-check call the resolver instead of hardcoding a path
status: open
priority: p1
parent_prd: prd-canonical-read-path-repair-2026-08-22
allowed_files:
  - plugins/kipi-ops/skills/council/SKILL.md
  - plugins/kipi-ops/skills/council/workflows/quick.md
  - plugins/kipi-ops/skills/council/workflows/debate.md
  - plugins/kipi-core/commands/wiring-check.md
  - q-system/.q-system/scripts/test/test-council-resolves-canonical.sh
disallowed_files:
  - .claude/**
  - .prd-os/**
required_checks:
  - bash q-system/.q-system/scripts/test/test-council-resolves-canonical.sh
required_reviews:
  - runtime-owner
bypass_check: "bash q-system/.q-system/scripts/test/test-council-resolves-canonical.sh"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-canonical-read-path-repair-2026-08-22 finding=finding-19 at=2026-08-22T20:07:44Z -->

# Council and wiring-check call the resolver instead of hardcoding a path

## Context

Parent PRD: `.prd-os/prds/prd-canonical-read-path-repair-2026-08-22.md`

## Acceptance

THIRTEEN references, not nine (finding-12, finding-30, recounted: SKILL.md 4, quick.md 4, debate.md 4, wiring-check.md 1). The check must assert the resolver is REACHED, not that a substring is absent: a literal negated grep on q-system/canonical/ is a false green because q-system//canonical/ or a concatenated path keeps the dead tree while passing (finding-19). Write test-council-resolves-canonical.sh to (a) assert every one of the 13 sites names the resolver, and (b) run a positive control against a fixture instance whose domain dir is NOT q-system and assert the resolved path is that dir. Show it RED before the edit. NEVER hardcode q-consult/: 8 registered instances have instance_q_dir null. ALSO IN SCOPE (finding-20): council's q-system/my-project/ references (SKILL.md:37,39 relationships.md and competitive-landscape.md) are the same defect in the same files and are left pointing at a fossil if only canonical is fixed.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Council and wiring-check call the resolver instead of hardcoding a path
