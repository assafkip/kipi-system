---
id: voice-refresh-orchestrator
title: Repo-root orchestrator chaining Stages 2-3 over a corpus, idempotent and retry-safe
status: closed
priority: p1
parent_prd: prd-voice-refresh-monthly-2026-07-04
allowed_files:
  - automation/voice_refresh.py
  - automation/test_voice_refresh.py
disallowed_files: []
required_checks:
  - python3 -m pytest automation/test_voice_refresh.py -q
required_reviews: []
bypass_check: "python3 -m pytest automation/test_voice_refresh.py -q -k contamination_or_headless"
---
<!-- generated-by: prd_split.py prd=prd-voice-refresh-monthly-2026-07-04 finding=finding-4 at=2026-07-04T23:47:31Z -->

# Repo-root orchestrator chaining Stages 2-3 over a corpus, idempotent and retry-safe

## Context

Parent PRD: `.prd-os/prds/prd-voice-refresh-monthly-2026-07-04.md`

## Acceptance

WRAPS (never modifies) granola-voice-synthesize.py + granola-voice-fingerprint.py; checks claude -p availability and stops with an environmental-trigger diagnosis if absent; REFUSES Stage 2 on any corpus containing a review-flagged (>700-word turn) meeting; logs each step; a second run on an unchanged corpus is a no-op.
