---
id: autocapture-recall-artifact
title: Session-scoped .session-recall.json: single-writer producer + schema + atomic keyed write
status: open
priority: p0
parent_prd: prd-memory-autocapture-2026-07-04
allowed_files:
  - q-system/.q-system/scripts/session_recall.py
  - q-system/.q-system/scripts/memory-scores-surface.py
  - q-system/.q-system/scripts/memory-confidence-surface.py
  - q-system/.q-system/scripts/test_session_recall.py
  - q-system/memory/schemas/session-recall.schema.json
  - .gitignore
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test_session_recall.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test_session_recall.py"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-memory-autocapture-2026-07-04 finding=finding-5 at=2026-07-04T21:08:45Z -->

# Session-scoped .session-recall.json: single-writer producer + schema + atomic keyed write

## Context

Parent PRD: `.prd-os/prds/prd-memory-autocapture-2026-07-04.md`

## Acceptance

Surface scripts append surfaced memory_ids via a single-writer helper. .session-recall.json is keyed by session_id and written atomically (temp+rename); overlapping sessions never mix or truncate each other. A test drives a surface script with a seeded sidecar and asserts .session-recall.json lists exactly the surfaced ids for that session_id. Artifact is gitignored. Schema documented.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Session-scoped .session-recall.json: single-writer producer + schema + atomic keyed write
