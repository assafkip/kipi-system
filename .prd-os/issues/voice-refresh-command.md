---
id: voice-refresh-command
title: /voice-refresh interactive command: Granola pull, harvest, orchestrate, gated merge proposal
status: closed
priority: p1
parent_prd: prd-voice-refresh-monthly-2026-07-04
allowed_files:
  - plugins/kipi-core/commands/voice-refresh.md
  - automation/test_voice_refresh_command.py
disallowed_files: []
required_checks:
  - python3 automation/test_voice_refresh_command.py
required_reviews: []
bypass_check: "python3 automation/test_voice_refresh_command.py"
---
<!-- generated-by: prd_split.py prd=prd-voice-refresh-monthly-2026-07-04 finding=finding-7 at=2026-07-04T23:47:31Z -->

# /voice-refresh interactive command: Granola pull, harvest, orchestrate, gated merge proposal

## Context

Parent PRD: `.prd-os/prds/prd-voice-refresh-monthly-2026-07-04.md`

## Acceptance

Pulls since-last-refresh Granola meetings, runs harvest, invokes the orchestrator, emits a voice-delta.md proposal; NEVER writes voice-dna.md directly; test asserts frontmatter, CLAUDE.md registration, and no voice-dna.md write path.
