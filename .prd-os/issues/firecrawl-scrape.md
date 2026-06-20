---
id: firecrawl-scrape
title: Firecrawl scrape-to-FILE lane (H7): firecrawl-scrape.py (stdlib, onlyMainContent, fail-closed on empty body, safe filename), env-key stanza (no committed secret), wired into research-mode; required_check OFFLINE (HTTP mocked)
status: closed
priority: p1
parent_prd: prd-brief-adopt-items-2026-06-20
allowed_files:
  - q-system/.q-system/scripts/firecrawl-scrape.py
  - .mcp.json
  - plugins/kipi-core/skills/research-mode/SKILL.md
  - q-system/.q-system/scripts/test/test-firecrawl-scrape.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-firecrawl-scrape.sh
required_reviews: []
bypass_check: "bash q-system/.q-system/scripts/test/test-firecrawl-scrape.sh"
---
<!-- generated-by: prd_split.py prd=prd-brief-adopt-items-2026-06-20 finding=finding-5 at=2026-06-20T01:42:14Z -->

# Firecrawl scrape-to-FILE lane (H7): firecrawl-scrape.py (stdlib, onlyMainContent, fail-closed on empty body, safe filename), env-key stanza (no committed secret), wired into research-mode; required_check OFFLINE (HTTP mocked)

## Context

Parent PRD: `.prd-os/prds/prd-brief-adopt-items-2026-06-20.md`

## Acceptance

- [ ] `q-system/.q-system/scripts/firecrawl-scrape.py`: stdlib `urllib` POST to the Firecrawl API using `${FIRECRAWL_API_KEY}` (env-var ONLY, no committed secret), `formats=["markdown"]` + `onlyMainContent`, writes the FULL markdown to `<output-dir>/<sanitized-name>.md`. Fail-CLOSED on an empty body (non-zero exit, persist NOTHING). No key -> clear non-zero exit. A `FIRECRAWL_MOCK_RESPONSE` env hook lets tests inject a canned response (no live call).
- [ ] Wired into research-mode (`plugins/kipi-core/skills/research-mode/SKILL.md`) as an explicit "persist full source" rung, documenting the `FIRECRAWL_API_KEY` requirement. (Standalone script -- no MCP server; `.mcp.json` left untouched.)
- [ ] `test-firecrawl-scrape.sh`: OFFLINE -- no key -> non-zero exit; good mock response -> writes a file containing the full markdown; empty body -> fail-closed (non-zero, no file); filename sanitized (no ?/&// in the name).
- [ ] required_check passes.
