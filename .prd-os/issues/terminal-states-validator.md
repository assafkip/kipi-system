---
id: terminal-states-validator
title: Piece B: a validator that enumerates exits from source and proves each consumer is live, not merely present
status: open
priority: p1
parent_prd: prd-terminal-state-redrive-2026-08-01
allowed_files:
  - q-system/.q-system/terminal-states.json
  - q-system/.q-system/scripts/test/test-terminal-states.sh
  - q-system/.q-system/capability-manifest.json
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-terminal-states.sh
required_reviews: []
bypass_check: "The validator has a negative self-test that FAILS on a fixture row whose only actor is the founder, and a second that FAILS on a row naming a consumer whose liveness_check reports no run inside its interval. A gate that cannot be shown failing is not a gate."
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-terminal-state-redrive-2026-08-01 finding=finding-2 at=2026-08-01T19:41:22Z -->

# Piece B: a validator that enumerates exits from source and proves each consumer is live, not merely present

## Context

Parent PRD: `.prd-os/prds/prd-terminal-state-redrive-2026-08-01.md`

## Acceptance

Exits are enumerated FROM q-system/.q-system/scripts/linear-worker.sh at runtime (every continue in the issue loop, every label-apply, every ready() exclusion predicate), never from a hand list -- finding-4. An unregistered exit makes kipi check RED and names the site. Each row declares a consumer AND a liveness_check proving the consumer ran inside its interval, not a plist present on disk -- finding-14. A row may instead declare terminal:true with a written rationale; an honest dead end passes, an unexamined one does not. Rows key on stable markers (label name, sentinel filename, predicate function name), never line numbers -- finding-15, whose mis-cited sites (:1297 resets variables, :1295 is a comment, the real stuck gate is :680) are the evidence. Registered in capability-manifest.json and wired into kipi check.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Piece B: a validator that enumerates exits from source and proves each consumer is live, not merely present
