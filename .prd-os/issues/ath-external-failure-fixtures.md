---
id: ath-external-failure-fixtures
title: Lock current external failures as Kipi acceptance fixtures
status: open
priority: p1
parent_prd: prd-automation-terminal-health-2026-07-24
allowed_files:
  - q-system/.q-system/tests/fixtures/automation-failures/**
  - q-system/.q-system/tests/test_automation_failure_scenarios.py
disallowed_files:
  - q-system/.q-system/scripts/**
  - instance-registry.json
  - .prd-os/**
  - /Users/assafkipnis/projects/cole-gtm/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_automation_failure_scenarios.py
required_reviews:
  - automation-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_automation_failure_scenarios.py -k external_repo_untouched"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-automation-terminal-health-2026-07-24 finding=finding-5 at=2026-07-24T21:08:00Z -->

# Lock current external failures as Kipi acceptance fixtures

## Context

Parent PRD: `.prd-os/prds/prd-automation-terminal-health-2026-07-24.md`

## Acceptance

Write failing fixtures first for daily-social lint failure, zero delivery, missing first comment, stranded draft, and absent Playwright Chromium. Point external repairs to dependencies or spillover only.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Lock current external failures as Kipi acceptance fixtures
