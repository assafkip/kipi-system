---
id: dr-capability-gate-green-2026-07-28
title: Return kipi check to green: declare the six grounding tests, drop the phantom instance
status: closed
priority: p0
parent_prd: prd-deterministic-reading-2026-07-28
allowed_files:
  - q-system/.q-system/capability-manifest.json
  - instance-registry.json
  - .claude/rules/evidence-ledger.md
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/capability-gate.py
  - python3 -c "import json;d=json.load(open('instance-registry.json'));import os;assert all(os.path.isdir(os.path.expanduser(i['path'])) for i in d['instances'])"
required_reviews: []
bypass_check: "test \"$(python3 -c \"import json;print(len(json.load(open('q-system/.q-system/capability-manifest.json'))['expected_tests']))\")\" -ge 84"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-deterministic-reading-2026-07-28 finding=finding-10 at=2026-07-28T22:58:38Z -->

# Return kipi check to green: declare the six grounding tests, drop the phantom instance

## Context

Parent PRD: `.prd-os/prds/prd-deterministic-reading-2026-07-28.md`

## Acceptance

expected_tests declares all six grounding tests with no pre-existing entry lost; provenance_vocabulary.py resolves via a real wiring surface rather than a false declared_inert; every registered instance path exists. kipi check FAIL 5 -> FAIL 0. ASK-230, ASK-234.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Return kipi check to green: declare the six grounding tests, drop the phantom instance
