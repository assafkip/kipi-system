---
id: vg-k1a-guard-contract
title: Pin the instance existence-guard contract through apply and the settings merge
status: closed
priority: p1
parent_prd: prd-voicegate-skeleton-2026-11-09
allowed_files:
  - q-system/.q-system/scripts/test/test-settings-merge.sh
  - q-system/.q-system/scripts/test/test-apply-claude-changes.sh
  - kipi-settings-merge.py
  - q-system/lessons/a-hook-that-fails-closed-on-a-missing-script-blocks-the-fix-too.md
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-settings-merge.sh
  - bash q-system/.q-system/scripts/test/test-apply-claude-changes.sh
required_reviews: []
bypass_check: "bash q-system/.q-system/scripts/test/test-settings-merge.sh"
gate_lifecycle: historical-receipt
deliverables_count: 5
---
<!-- generated-by: prd_split.py prd=prd-voicegate-skeleton-2026-11-09 finding=finding-5 at=2026-11-09T18:24:23Z -->

# Pin the instance existence-guard contract through apply and the settings merge

## Context

Parent PRD: `.prd-os/prds/prd-voicegate-skeleton-2026-11-09.md`

## Acceptance

The guard shape is: test -f "$CLAUDE_PROJECT_DIR/<p>" || { echo "<basename> missing: the gate cannot run" >&2; exit 2; } in the same PostToolUse event and matcher as the gate's own hook. No new apply op and no ratchet exemption. kipi-settings-merge.py may gain a why-comment at hook_key naming this contract; its behaviour does not change unless the tests show the guard is dropped.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Merge test: the guard beside an if-test-f hook for the same instance script survives merge_settings twice with no DROPPED line
- [x] Negative self-test: the bare [ -f X ] || exit 2 form keys like the real hook and is dropped with a DROPPED line, proving the test sees a drop
- [x] Apply test: an instance-mode proposal inserting the guard into a temp instance settings.json applies, ratchet growth only
- [x] Shell test: on a temp tree the guard exits 2 with its message on stderr when the script is missing and exits 0 when present
- [x] The lesson on fail-closed hooks gains its limit: the no-op existence guard is for hooks that run before the action; a PostToolUse gate uses the separate exit-2 guard
