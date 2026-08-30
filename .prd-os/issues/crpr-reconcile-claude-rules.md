---
id: crpr-reconcile-claude-rules
title: Reconcile the rules that mandate the dead path, via the sanctioned path
status: open
priority: p1
parent_prd: prd-canonical-read-path-repair-2026-08-22
allowed_files:
  - q-system/.q-system/scripts/test/test-claude-rules-canonical-reconciled.sh
disallowed_files:
  - plugins/**
  - .prd-os/**
required_checks:
  - bash q-system/.q-system/scripts/test/test-claude-rules-canonical-reconciled.sh
required_reviews:
  - runtime-owner
bypass_check: "bash q-system/.q-system/scripts/test/test-claude-rules-canonical-reconciled.sh"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-canonical-read-path-repair-2026-08-22 finding=finding-21 at=2026-08-22T20:07:44Z -->

# Reconcile the rules that mandate the dead path, via the sanctioned path

## Context

Parent PRD: `.prd-os/prds/prd-canonical-read-path-repair-2026-08-22.md`

## Acceptance

folder-structure.md:257-264 actively mandates that all scripts MUST resolve QROOT to q-system/, a direct contradiction of this PRD; four skeleton-synced rules carry frontmatter globs on the dead path (md-hygiene.md:4, anti-misclassification.md:4, sycophancy.md:5, folder-structure.md:236). No other entry can touch these: every one disallows .claude/** (finding-21, finding-5). The EDITS go through apply-claude-changes.sh, the sanctioned proposal path enforced by the claude-path-write-guard hook - do NOT write .claude/ directly and do NOT weaken the hook. This entry allowed_files holds only the checker, which asserts the contradiction is gone and the four globs resolve through the resolver. Show it RED first. Also enumerate the ~20 agent-pipeline prompts under q-system/.q-system/agent-pipeline/agents/ that reference the path and report them explicitly; if this entry does not repoint them, say so rather than implying coverage (finding-11).

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Reconcile the rules that mandate the dead path, via the sanctioned path
