---
description: "Memory architecture — time-stratified memory (working/weekly/monthly), session continuity"
user-invocable: false
paths:
  - "**/memory/**"
  - "**/last-handoff.md"
---

# Memory Architecture

**Gate check:** Read `{config_dir}/enabled-integrations.md`. If `memory-architecture` is NOT explicitly set to `true`, SKIP this rule file.


Time-stratified memory in `{data_dir}/memory/`:

- `working/` — session-scoped, ephemeral (<48h). Auto-cleaned during `/q-morning` Step 0a.
- `weekly/` — 7-day rolling window. Reviewed during Monday morning routine.
- `monthly/` — persistent insights. Reviewed on 1st of month.
- `graph.jsonl` — entity-relationship triples for cross-contact queries.
- `last-handoff.md` — session continuity note from `/q-handoff`.

During Step 0c, read `{data_dir}/memory/last-handoff.md` for prior session context.

## Session Continuity

`/q-wrap` at end of day runs a 10-minute health check (effort log, debrief check, canonical drift, tomorrow preview). `/q-wrap` auto-chains into `/q-handoff` — the founder never needs to run both separately.

`/q-morning` auto-detects missed wraps and runs a lightweight retroactive wrap.
