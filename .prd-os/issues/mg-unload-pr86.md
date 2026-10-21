---
id: mg-unload-pr86
title: Unload com.kipi.pr86-review and drop its exemption (ASK-2396)
status: open
priority: p1
parent_prd: prd-model-gate-2026-10-02
allowed_files:
  - q-system/.q-system/scripts/test/test-loaded-label-has-template.py
  - AUTONOMOUS-SYSTEMS.md
disallowed_files: []
required_checks:
  - "bash -c '! grep -qF \"\\\"com.kipi.pr86-review\\\": (\" q-system/.q-system/scripts/test/test-loaded-label-has-template.py'"
required_reviews: []
bypass_check: "bash -c '! launchctl list 2>/dev/null | grep -q com.kipi.pr86-review'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-model-gate-2026-10-02 finding=finding-7 at=2026-10-02T06:19:39Z -->

# Unload com.kipi.pr86-review and drop its exemption (ASK-2396)

## Context

Parent PRD: `.prd-os/prds/prd-model-gate-2026-10-02.md`

## Acceptance

With the allowlist entry removed the check is red while the job is loaded and green once it is unloaded.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Unload com.kipi.pr86-review and drop its exemption (ASK-2396)
