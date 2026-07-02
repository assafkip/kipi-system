---
id: lint-hook-ownership-dedupe
title: Remove kipi-core's six q-system lint wirings; ownership test bans CLAUDE_PROJECT_DIR q-system references in plugin hooks (sp-700047ff)
status: closed
priority: p2
parent_prd: prd-lint-hook-ownership-dedupe-2026-07-02
allowed_files:
  - plugins/kipi-core/hooks/hooks.json
  - settings-template.json
  - plugins/kipi-core/.claude-plugin/plugin.json
  - q-system/.q-system/scripts/test/test-plugin-hook-ownership.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-plugin-hook-ownership.sh
required_reviews: []
bypass_check: "bash q-system/.q-system/scripts/test/test-plugin-hook-ownership.sh"
---
<!-- generated-by: prd_split.py prd=prd-lint-hook-ownership-dedupe-2026-07-02 finding=finding-2 at=2026-07-02T19:38:23Z -->

# Remove kipi-core's six q-system lint wirings; ownership test bans CLAUDE_PROJECT_DIR q-system references in plugin hooks (sp-700047ff)

## Context

Parent PRD: `.prd-os/prds/prd-lint-hook-ownership-dedupe-2026-07-02.md`

## Acceptance

kipi-core/hooks/hooks.json contains only CLAUDE_PLUGIN_ROOT hook commands (rca-lint + fable-discipline-lint on Edit|Write|MultiEdit, rca-notify on Bash). The ownership test parses every plugins/*/hooks/hooks.json json-aware and fails on any hook command referencing a CLAUDE_PROJECT_DIR path under q-system/ (covering ${} and bare variable forms via raw-string scan); it was shown failing against the pre-fix hooks.json (negative self-test) and passes after.

## Amendments

### 2026-07-02T19:43:34Z
Reason: Codex adversarial finding-1: settings-template.json wires voice-lint and voice-substance-lint with || true, masking exit-2; the removed plugin copies were the only unmasked wirings in instances. Scope grows to fix both template wirings to the if-then form; ownership test grows a template-PostToolUse no-'|| true' section.

Before:
- allowed_files: ['plugins/kipi-core/hooks/hooks.json', 'plugins/kipi-core/.claude-plugin/plugin.json', 'q-system/.q-system/scripts/test/test-plugin-hook-ownership.sh']
- required_checks: ['bash q-system/.q-system/scripts/test/test-plugin-hook-ownership.sh']
- disallowed_files: []

After:
- allowed_files: ['plugins/kipi-core/hooks/hooks.json', 'settings-template.json', 'plugins/kipi-core/.claude-plugin/plugin.json', 'q-system/.q-system/scripts/test/test-plugin-hook-ownership.sh']
- required_checks: ['bash q-system/.q-system/scripts/test/test-plugin-hook-ownership.sh']
- disallowed_files: []
