---
id: fable-binary-phrasing-audit
title: Rewrite graduated phrasing to zero-or-fail in merged skill + prd-os prose
status: open
priority: p1
parent_prd: prd-fable-discipline-2026-07-04
allowed_files:
  - plugins/prd-os/skills/**
  - plugins/prd-os/hooks/**
  - plugins/prd-os/tests/**
disallowed_files: []
required_checks:
  - pytest -q plugins/prd-os/tests
  - bash plugins/prd-os/scripts/export-fable-mirror.sh --check
required_reviews: []
bypass_check: "pytest -q plugins/prd-os/tests"
---
<!-- generated-by: prd_split.py prd=prd-fable-discipline-2026-07-04 finding=finding-5 at=2026-07-04T01:45:32Z -->

# Rewrite graduated phrasing to zero-or-fail in merged skill + prd-os prose

## Context

Parent PRD: `.prd-os/prds/prd-fable-discipline-2026-07-04.md`

## Acceptance

Grep for graduated verbs (prefer/avoid/sparingly/minimize/keep minimal/usually/generally) applied to actually-binary rules; each rewritten to zero-or-fail. Every regex/count-checkable rewrite gains a lint detector with a red-then-green reproducer. Judgment rules keep graduated phrasing; the audit log in the issue notes which hits were left as judgment and why.
