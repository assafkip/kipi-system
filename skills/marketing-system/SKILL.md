---
description: "Marketing system — content guardrails, brand voice, theme rotation"
user-invocable: false
paths:
  - "**/marketing/**"
  - "**/content-*.md"
---

# Marketing System

**Gate check:** Read `{config_dir}/enabled-integrations.md`. If `marketing-system` is NOT explicitly set to `true`, SKIP this rule file.


## Content Rules

- All content must pass `marketing/content-guardrails.md` before publishing
- Voice rules per channel in `marketing/brand-voice.md`
- Themes rotate on a configurable cycle in `marketing/content-themes.md`
- Reusable assets in `marketing/assets/` (boilerplate, bios, stats, proof points, competitive one-liners)
- State tracked in `{data_dir}/memory/marketing-state.md`

## Data Sources

Content metrics and engagement data are harvested automatically via `kipi_harvest`. Use `kipi_get_harvest` to query content performance across platforms.
