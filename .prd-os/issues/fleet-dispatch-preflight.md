---
id: fleet-dispatch-preflight
title: Piece C: no repo is dispatched into until a preflight passes, and selection is round-robin
status: in-progress
priority: p2
parent_prd: prd-terminal-state-redrive-2026-08-01
allowed_files:
  - kipi-dispatch.sh
  - instance-registry.json
  - q-system/.q-system/scripts/repo-preflight.sh
  - q-system/.q-system/scripts/test/test-repo-preflight.sh
  - q-system/.q-system/capability-manifest.json
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-repo-preflight.sh
required_reviews: []
bypass_check: "The dispatcher REFUSES a registry repo whose preflight fails, proven by a fixture repo that fails one preflight item and is then absent from the dispatcher's dry-run pick list. There is no flag, env var, or registry field that skips the preflight."
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-terminal-state-redrive-2026-08-01 finding=finding-8 at=2026-08-01T19:41:22Z -->

# Piece C: no repo is dispatched into until a preflight passes, and selection is round-robin

## Context

Parent PRD: `.prd-os/prds/prd-terminal-state-redrive-2026-08-01.md`

## Acceptance

STARTS ONLY after needs-scope-redrive and terminal-states-validator are green. Preflight covers control-code version, hook presence, remote identity, branch protection, credentials, dirty state, and a per-repo kill switch -- opt-in plus a project filter is NOT protection for Alice or Prodigy_Gold, which this dispatcher would otherwise push to and auto-merge in. Selection is round-robin with a recorded cursor, not registry order, so a nonempty early repo cannot starve later client repos -- finding-9. 'Lists ready issues from two repos' is explicitly NOT sufficient; the check must show eventual pickup of a repo that sorts last.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Piece C: no repo is dispatched into until a preflight passes, and selection is round-robin
