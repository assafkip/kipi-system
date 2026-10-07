---
description: Marketing system rules for content pipeline
paths:
  - "q-system/marketing/**"
  - "q-system/memory/marketing-state.md"
---

# Marketing System

A full marketing automation system lives in `marketing/`. See `marketing/README.md` for overview.

**Key rules:**
- All content must pass `marketing/content-guardrails.md` before publishing
- Voice rules per channel in `marketing/brand-voice.md`
- Themes rotate on a configurable cycle in `marketing/content-themes.md`
- Reusable assets in `marketing/assets/` (boilerplate, bios, stats, proof points, competitive one-liners)
- State tracked in `memory/marketing-state.md`
- Gamma MCP for decks/one-pagers/social cards (if configured)

**Notion rule:** Before any CRM write, fetch the CRM parent page with the Notion server you plan to use. If it returns not-found, that server's token cannot see the page; use the other Notion server (the claude.ai connector or the project-scoped API server).

**Notion databases (configured during setup):**
- Content Pipeline DB: {{CONTENT_PIPELINE_DB_ID}}
- Editorial Calendar DB: {{EDITORIAL_CALENDAR_DB_ID}}
- Asset Library DB: {{ASSET_LIBRARY_DB_ID}}

**Commands:** `/q-market-plan`, `/q-market-create`, `/q-market-review`, `/q-market-publish`, `/q-market-assets`, `/q-market-status`
