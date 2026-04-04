# Markdown Hygiene (ENFORCED)

## Line Budgets

Every canonical and my-project markdown file has a line budget. Before appending content to any of these files, check its current line count. If adding your content would push the file over budget, archive older sections first.

| File | Budget |
|------|--------|
| canonical/decisions.md | 150 |
| canonical/discovery.md | 150 |
| canonical/market-intelligence.md | 200 |
| canonical/objections.md | 150 |
| canonical/talk-tracks.md | 150 |
| canonical/engagement-playbook.md | 150 |
| canonical/content-intelligence.md | 150 |
| canonical/verticals.md | 100 |
| canonical/pricing-framework.md | 100 |
| my-project/relationships.md | 200 |
| my-project/competitive-landscape.md | 150 |
| my-project/current-state.md | 100 |
| my-project/progress.md | 100 |

## Rules

1. **Before writing:** Count lines. If within 20 lines of budget, deduplicate or consolidate existing entries before adding new ones.
2. **Over budget:** Move the oldest ## sections to `q-system/memory/archives/<filename>-YYYY-MM-DD.md` before writing new content.
3. **Deduplication over accumulation.** If a new entry updates an existing one (same person, same objection, same decision), replace the old entry. Do not append a second copy.
4. **Merge signals.** Three separate market intelligence entries about the same trend should become one entry with combined evidence.
5. **MEMORY.md** has a hard cap of 200 lines. Prune stale entries before adding new ones.

## Auto-Prune

The `md-prune.py` script runs on SessionStart and auto-archives sections when files exceed budget. It splits on ## headers and keeps the newest sections. If a file has no ## structure, it warns but does not prune (fix the file structure manually).

## Archive Format

Archived content goes to `q-system/memory/archives/` with filename pattern: `<source-file>-YYYY-MM-DD.md`. Archives are append-only and not loaded into context.
