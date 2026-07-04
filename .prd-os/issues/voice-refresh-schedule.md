---
id: voice-refresh-schedule
title: Monthly launchd nudge (repo-root) via slack-notify.sh, registered with launchd-health
status: open
priority: p1
parent_prd: prd-voice-refresh-monthly-2026-07-04
allowed_files:
  - automation/voice-refresh-nudge.sh
  - automation/com.kipi.voice-refresh.plist
  - automation/install-voice-refresh.sh
  - automation/test_voice_refresh_schedule.py
disallowed_files: []
required_checks:
  - python3 automation/test_voice_refresh_schedule.py
required_reviews: []
bypass_check: "python3 automation/test_voice_refresh_schedule.py"
---
<!-- generated-by: prd_split.py prd=prd-voice-refresh-monthly-2026-07-04 finding=finding-9 at=2026-07-04T23:47:31Z -->

# Monthly launchd nudge (repo-root) via slack-notify.sh, registered with launchd-health

## Context

Parent PRD: `.prd-os/prds/prd-voice-refresh-monthly-2026-07-04.md`

## Acceptance

plist is valid XML scheduling the nudge on the 1st monthly; nudge routes the founder ping ONLY through slack-notify.sh (no osascript); installer registers with launchd-health; test asserts all three.
