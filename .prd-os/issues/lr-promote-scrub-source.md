---
id: lr-promote-scrub-source
title: The promotion scrub reads production term sources: registry codenames, the instance's clients.json names and slugs, and the single-sourced tripwire terms
status: closed
priority: p1
parent_prd: prd-lessons-rail-and-up-rail-2026-09-02
allowed_files:
  - kipi-promote.sh
  - kipi-push-upstream.sh
  - q-system/.q-system/scripts/tripwire-terms.txt
  - q-system/.q-system/scripts/lessons_scrub.py
  - q-system/.q-system/scripts/test/test-lessons-push-guard.sh
  - q-system/.q-system/scripts/trigger-inventory.py
  - q-system/.q-system/tests/test_trigger_inventory.py
  - q-system/.q-system/tests/test_promotion_receipt.py
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
  - kipi-update.sh
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py -k 'client_name_refused or clients_file_missing'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-lessons-rail-and-up-rail-2026-09-02 finding=finding-3 at=2026-09-02T00:25:35Z -->

# The promotion scrub reads production term sources: registry codenames, the instance's clients.json names and slugs, and the single-sourced tripwire terms

## Context

Parent PRD: `.prd-os/prds/prd-lessons-rail-and-up-rail-2026-09-02.md`

## Acceptance

RED first: the scrub roster is lessons_scrub.codenames_from_registry(instance-registry.json) plus the name and slug of every record in the instance's my-project/clients.json (located through the registry's instance_q_dir for the instance being promoted from; a fixture clients.json with the producer's keys is used in tests) plus every line of q-system/.q-system/scripts/tripwire-terms.txt, which kipi-push-upstream.sh now reads for its pre-push grep instead of its inline list (a test asserts the inline list is gone and the file holds the same seven terms); a file carrying a planted client name or slug or tripwire term exits 2 with no copy and no receipt; a missing clients.json refuses (fail-closed) and says which path it looked for; KIPI_SCRUB_TERMS is removed from the design.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] The promotion scrub reads production term sources: registry codenames, the instance's clients.json names and slugs, and the single-sourced tripwire terms

## Amendments

### 2026-09-02T01:46:34Z
Reason: kipi-push-upstream.sh now reads its tripwire terms from q-system/.q-system/scripts/tripwire-terms.txt and fails closed without it; the pre-existing shell test test-lessons-push-guard.sh seeds an instance with no .q-system tree, so its clean case is refused. The fixture must carry the file production carries; adding that test to allowed_files.

Before:
- allowed_files: ['kipi-promote.sh', 'kipi-push-upstream.sh', 'q-system/.q-system/scripts/tripwire-terms.txt', 'q-system/.q-system/scripts/lessons_scrub.py', 'q-system/.q-system/tests/test_promotion_receipt.py']
- required_checks: ['python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py']
- disallowed_files: ['.claude/**', 'plugins/prd-os/**', '.prd-os/**', 'q-consult/**', 'kipi-update.sh']

After:
- allowed_files: ['kipi-promote.sh', 'kipi-push-upstream.sh', 'q-system/.q-system/scripts/tripwire-terms.txt', 'q-system/.q-system/scripts/lessons_scrub.py', 'q-system/.q-system/tests/test_promotion_receipt.py']
- required_checks: ['python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py']
- disallowed_files: ['.claude/**', 'plugins/prd-os/**', '.prd-os/**', 'q-consult/**', 'kipi-update.sh']

### 2026-09-02T01:53:45Z
Reason: pre-commit verify.sh: issue 6's test_trigger_inventory now reads kipi-push-upstream.sh as triggered because issue 8's test_promotion_receipt.py names it and the manifest-triggered test propagates through the transitive closure. A test exercising a script is not a production trigger; the closure must not propagate through test files. Adding trigger-inventory.py and its test to allowed_files.

Before:
- allowed_files: ['kipi-promote.sh', 'kipi-push-upstream.sh', 'q-system/.q-system/scripts/tripwire-terms.txt', 'q-system/.q-system/scripts/lessons_scrub.py', 'q-system/.q-system/tests/test_promotion_receipt.py']
- required_checks: ['python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py']
- disallowed_files: ['.claude/**', 'plugins/prd-os/**', '.prd-os/**', 'q-consult/**', 'kipi-update.sh']

After:
- allowed_files: ['kipi-promote.sh', 'kipi-push-upstream.sh', 'q-system/.q-system/scripts/tripwire-terms.txt', 'q-system/.q-system/scripts/lessons_scrub.py', 'q-system/.q-system/scripts/test/test-lessons-push-guard.sh', 'q-system/.q-system/tests/test_promotion_receipt.py']
- required_checks: ['python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py']
- disallowed_files: ['.claude/**', 'plugins/prd-os/**', '.prd-os/**', 'q-consult/**', 'kipi-update.sh']
