---
id: pff-dereferenced-sources
title: Scan what rsync actually copies, including dereferenced symlinks
status: open
priority: p0
parent_prd: prd-prevent-fact-fanout-2026-07-25
allowed_files:
  - q-system/.q-system/scripts/propagation-leak-gate.py
  - q-system/.q-system/scripts/test/test-propagation-leak-sources.py
disallowed_files:
  - kipi-update.sh
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/scripts/test/test-propagation-leak-sources.py
required_reviews:
  - security
bypass_check: "python3 -m pytest -q q-system/.q-system/scripts/test/test-propagation-leak-sources.py -k 'symlink and refused'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-prevent-fact-fanout-2026-07-25 finding=finding-2 at=2026-07-25T18:11:12Z -->

# Scan what rsync actually copies, including dereferenced symlinks

## Context

Parent PRD: `.prd-os/prds/prd-prevent-fact-fanout-2026-07-25.md`

## Acceptance

Write the failing symlinked-plugin reproducer first. A fact behind a tracked symlink that rsync dereferences must be found, and a source the gate cannot scan must refuse to propagate.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Scan what rsync actually copies, including dereferenced symlinks
