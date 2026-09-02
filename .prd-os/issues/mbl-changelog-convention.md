---
id: mbl-changelog-convention
title: Changelog header convention documented once and asserted on the skill this PRD creates
status: closed
priority: p2
parent_prd: prd-morning-brief-learns-2026-09-01
allowed_files:
  - plugins/kipi-core/skills/README.md
  - plugins/kipi-core/.claude-plugin/plugin.json
  - q-system/.q-system/tests/test_skill_changelog.py
  - q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_skill_changelog.py.json
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - plugins/kipi-core/skills/*/SKILL.md
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_skill_changelog.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_skill_changelog.py -k no_wildcard"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-morning-brief-learns-2026-09-01 finding=finding-3 at=2026-09-01T22:00:59Z -->

# Changelog header convention documented once and asserted on the skill this PRD creates

## Context

Parent PRD: `.prd-os/prds/prd-morning-brief-learns-2026-09-01.md`

## Acceptance

README.md states the convention (a '## Changelog' section with dated lines, newest first). RED first: the test asserts plugins/kipi-core/skills/improve/SKILL.md carries the header once it exists (skips with an explicit reason until issue mbl-improve-skill lands) and asserts, by reading git-tracked paths, that NO existing SKILL.md was modified by this issue. No wildcard allowed_files; existing skills are untouched.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Changelog header convention documented once and asserted on the skill this PRD creates (README + test_skill_changelog.py; test_no_existing_skill_file_was_modified_by_this_issue reads git log and the working tree; kipi-core 1.9.1 via a recorded scope amendment; 3 Codex findings accepted and patched)

## Amendments

### 2026-09-01T22:40:06Z
Reason: pre-commit gate plugin-version-bump refuses any change under plugins/kipi-core without a plugin.json version bump; the PRD manifest omitted plugins/kipi-core/.claude-plugin/plugin.json for both plugin-touching issues (this one and mbl-improve-skill). Release state is Sana's call per the founder's routing note (plan Phase 3), so the amendment is recorded here rather than routed to the founder.

Before:
- allowed_files: ['plugins/kipi-core/skills/README.md', 'q-system/.q-system/tests/test_skill_changelog.py', 'q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_skill_changelog.py.json']
- required_checks: ['python3 -m pytest -q q-system/.q-system/tests/test_skill_changelog.py']
- disallowed_files: ['.claude/**', 'plugins/prd-os/**', '.prd-os/**', 'plugins/kipi-core/skills/*/SKILL.md']

After:
- allowed_files: ['plugins/kipi-core/skills/README.md', 'plugins/kipi-core/.claude-plugin/plugin.json', 'q-system/.q-system/tests/test_skill_changelog.py', 'q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_skill_changelog.py.json']
- required_checks: ['python3 -m pytest -q q-system/.q-system/tests/test_skill_changelog.py']
- disallowed_files: ['.claude/**', 'plugins/prd-os/**', '.prd-os/**', 'plugins/kipi-core/skills/*/SKILL.md']
