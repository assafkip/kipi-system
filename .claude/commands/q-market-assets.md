Refresh all reusable assets in q-system/marketing/assets/ from canonical files. Flag stale items.

Workflow:
1. Read memory/marketing-state.md Asset Freshness table
2. For each asset, check source file modifications since last refresh
3. For stale assets: regenerate from current canonical sources
4. Check Gamma Deck Tracker: compare canonical dates against deck generation dates
5. Optionally re-generate Gamma decks via mcp__gamma__generate_gamma
6. Update memory/marketing-state.md with new refresh dates
7. Update Asset Library DB (DS 3f4dd46b-3aa0-4cee-af79-831ed8d3c27d) in Notion
8. Output refresh report
