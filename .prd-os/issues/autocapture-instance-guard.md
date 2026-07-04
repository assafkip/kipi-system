---
id: autocapture-instance-guard
title: Design-partner-only enforcement: self-gating allowlist + guarded advisory Stop-hook wiring (settings + template sync)
status: open
priority: p1
parent_prd: prd-memory-autocapture-2026-07-04
allowed_files:
  - .claude/settings.json
  - settings-template.json
  - q-system/.q-system/scripts/autocapture_config.json
  - q-system/.q-system/scripts/test_autocapture_wiring.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test_autocapture_wiring.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test_autocapture_wiring.py"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-memory-autocapture-2026-07-04 finding=finding-3 at=2026-07-04T21:08:45Z -->

# Design-partner-only enforcement: self-gating allowlist + guarded advisory Stop-hook wiring (settings + template sync)

## Context

Parent PRD: `.prd-os/prds/prd-memory-autocapture-2026-07-04.md`

## Acceptance

autocapture_config.json is the allowlist (enabled_instances: [4_points_consulting]); the Stop-hook capture no-ops on any instance not listed (default off) so wiring the guarded advisory entry (test -f && python3 ... 2>/dev/null || true) into BOTH .claude/settings.json and settings-template.json cannot enable capture beyond the design partner. Test proves: the hook writes nothing when the current-instance identity is not in the allowlist, and the settings-template-sync invariant holds (entry present in both files). Wiring is advisory, never exit-2.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Design-partner-only enforcement: self-gating allowlist + guarded advisory Stop-hook wiring (settings + template sync)
