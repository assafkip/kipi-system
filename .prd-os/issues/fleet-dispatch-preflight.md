---
id: fleet-dispatch-preflight
title: Piece C: no repo is dispatched into until a preflight passes, and selection is round-robin
status: closed
priority: p2
parent_prd: prd-terminal-state-redrive-2026-08-01
allowed_files:
  - kipi-dispatch.sh
  - instance-registry.json
  - q-system/.q-system/scripts/repo-preflight.sh
  - q-system/.q-system/scripts/test/test-repo-preflight.sh
  - q-system/.q-system/capability-manifest.json
  - q-system/.q-system/scripts/linear-worker.sh
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

## Amendments

### 2026-08-01T20:52:52Z
Reason: The stated outcome is that the 18 out-of-repo owner:sana issues become pickable. A rotation that reaches an opted-in repo and then skips it does not meet that, and codex finding-1 (blocker) says the same: no external repo is ever dispatched. linear-worker.sh takes no target-repo argument and was previously fenced off by in-flight ASK-281; that run has since ended at converge exit-5 and is parked at blocked:capability, so the file is free to edit. Widening allowed_files to include q-system/.q-system/scripts/linear-worker.sh to add the --repo argument and the identity resolution the picker needs. sp-09c61b20 is the captured record of this gap.

Before:
- allowed_files: ['kipi-dispatch.sh', 'instance-registry.json', 'q-system/.q-system/scripts/repo-preflight.sh', 'q-system/.q-system/scripts/test/test-repo-preflight.sh', 'q-system/.q-system/capability-manifest.json']
- required_checks: ['bash q-system/.q-system/scripts/test/test-repo-preflight.sh']
- disallowed_files: []

After:
- allowed_files: ['kipi-dispatch.sh', 'instance-registry.json', 'q-system/.q-system/scripts/repo-preflight.sh', 'q-system/.q-system/scripts/test/test-repo-preflight.sh', 'q-system/.q-system/capability-manifest.json', 'q-system/.q-system/scripts/linear-worker.sh']
- required_checks: ['bash q-system/.q-system/scripts/test/test-repo-preflight.sh']
- disallowed_files: []
