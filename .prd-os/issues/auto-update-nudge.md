---
id: auto-update-nudge
title: De-fang auto-update.sh (remove the dangerous git subtree pull --squash) and rewrite to a never-blocking SessionStart nudge, then wire into settings-template.json + .claude/settings.json (H5)
status: closed
priority: p1
parent_prd: prd-brief-adopt-items-2026-06-20
allowed_files:
  - q-system/hooks/auto-update.sh
  - settings-template.json
  - .claude/settings.json
  - q-system/.q-system/scripts/test/test-auto-update-nudge.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-auto-update-nudge.sh
required_reviews: []
bypass_check: "bash q-system/.q-system/scripts/test/test-auto-update-nudge.sh"
---
<!-- generated-by: prd_split.py prd=prd-brief-adopt-items-2026-06-20 finding=finding-2 at=2026-06-20T01:42:14Z -->

# De-fang auto-update.sh (remove the dangerous git subtree pull --squash) and rewrite to a never-blocking SessionStart nudge, then wire into settings-template.json + .claude/settings.json (H5)

## Context

Parent PRD: `.prd-os/prds/prd-brief-adopt-items-2026-06-20.md`

## Acceptance

- [ ] `q-system/hooks/auto-update.sh`: the `git subtree pull --prefix=q-system ... --squash` block (lines 57-65) is REMOVED. When the remote has updates, the script NUDGES only -- prints "Run: kipi update", touches the daily sentinel, exits 0, never blocks. The file contains no `subtree pull`.
- [ ] `auto-update.sh` registered as a SessionStart hook in BOTH `settings-template.json` (propagates to instances) and the skeleton's `.claude/settings.json`, in the advisory `2>/dev/null || true` form like its sibling SessionStart hooks.
- [ ] `test-auto-update-nudge.sh`: asserts the script contains no `subtree pull`; that with a simulated skew it prints the nudge and exits 0; and that it is registered in both settings files.
- [ ] required_check passes (`bash q-system/.q-system/scripts/test/test-auto-update-nudge.sh`).
