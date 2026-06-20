---
id: voice-lint-topups
title: voice-lint emphasis-opener detector (H8) across voice-lint.py + the MCP linter, and voice-substance-lint single-proper-noun loophole fix requiring >=2 anchors on both word-count branches (H10), each with a paired test
status: closed
priority: p1
parent_prd: prd-brief-adopt-items-2026-06-20
allowed_files:
  - q-system/.q-system/scripts/voice-lint.py
  - q-system/.q-system/scripts/voice-substance-lint.py
  - plugins/kipi-core/kipi-mcp/**
  - q-system/.q-system/scripts/test/test-voice-lint-topups.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-voice-lint-topups.sh
required_reviews: []
bypass_check: "bash q-system/.q-system/scripts/test/test-voice-lint-topups.sh"
---
<!-- generated-by: prd_split.py prd=prd-brief-adopt-items-2026-06-20 finding=finding-4 at=2026-06-20T01:42:14Z -->

# voice-lint emphasis-opener detector (H8) across voice-lint.py + the MCP linter, and voice-substance-lint single-proper-noun loophole fix requiring >=2 anchors on both word-count branches (H10), each with a paired test

## Context

Parent PRD: `.prd-os/prds/prd-brief-adopt-items-2026-06-20.md`

## Acceptance

- [ ] `voice-lint.py` AND the MCP linter (`plugins/kipi-core/kipi-mcp/.../linter.py`) gain emphasis-opener detectors: "it's/it is worth mentioning|noting|highlighting" and opener-anchored "Importantly,/Notably,". Added as BLOCK-class tells consistent with the existing banned-phrase mechanism.
- [ ] `voice-substance-lint.py`: the single-proper-noun loophole closed -- BOTH word-count branches require >=2 anchors (a draft with one dropped brand name no longer passes anchorless). The rule STAYS WARN-class (exit 0, never hard-blocks published content).
- [ ] `test-voice-lint-topups.sh`: asserts the new emphasis-opener tells are caught by voice-lint; asserts a single-proper-noun draft now WARNs (not passes) in both word-count bands AND that voice-substance stays exit-0/WARN.
- [ ] required_check passes.
