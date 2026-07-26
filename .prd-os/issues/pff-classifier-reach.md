---
id: pff-classifier-reach
title: State and measure how much of a leak the classifier can see
status: closed
priority: p0
parent_prd: prd-prevent-fact-fanout-2026-07-25
allowed_files:
  - q-system/.q-system/tests/separation/test_semantic_client_leakage.py
  - q-system/.q-system/tests/separation/fixtures/fact-grammar.json
disallowed_files:
  - kipi-update.sh
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/separation/test_semantic_client_leakage.py
required_reviews:
  - security
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/separation/test_semantic_client_leakage.py -k 'reach or (blind_spot and measured)'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-prevent-fact-fanout-2026-07-25 finding=finding-1 at=2026-07-25T18:11:12Z -->

# State and measure how much of a leak the classifier can see

## Context

Parent PRD: `.prd-os/prds/prd-prevent-fact-fanout-2026-07-25.md`

## Acceptance

Write the failing prose-leak fixture first. Pin the classifier's blind spots (prose, headings, JSON, code, config) as explicit RED fixtures so the coverage bound is measured and visible rather than assumed.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] State and measure how much of a leak the classifier can see

## Amendments

### 2026-07-26T02:04:32Z
Reason: The registered bypass_check selected only test_blind_spot_coverage_is_measured_not_assumed, which is the one reach test that never calls the classifier -- and the one an adversarial review fully gutted while it stayed green. The permanent gate in gates.jsonl therefore never touched validate-separation.py. Widened to also select test_classifier_reach_is_pinned_per_form, the test that actually runs the classifier against every probe form.

Before:
- allowed_files: ['q-system/.q-system/tests/separation/test_semantic_client_leakage.py', 'q-system/.q-system/tests/separation/fixtures/fact-grammar.json']
- required_checks: ['python3 -m pytest -q q-system/.q-system/tests/separation/test_semantic_client_leakage.py']
- disallowed_files: ['kipi-update.sh', 'instance-registry.json', '.prd-os/**']

After:
- allowed_files: ['q-system/.q-system/tests/separation/test_semantic_client_leakage.py', 'q-system/.q-system/tests/separation/fixtures/fact-grammar.json']
- required_checks: ['python3 -m pytest -q q-system/.q-system/tests/separation/test_semantic_client_leakage.py']
- disallowed_files: ['kipi-update.sh', 'instance-registry.json', '.prd-os/**']
