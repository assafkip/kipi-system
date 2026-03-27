# /q-wrap — Evening health check

10-minute end-of-day system health check. Closes open loops, catches missed debriefs, checks canonical drift, previews tomorrow. Auto-chains into `/q-handoff` at the end — never run both separately.

## Preconditions

Read these files:
1. `q-system/my-project/enabled-integrations.md`
2. `q-system/my-project/founder-profile.md`
3. `q-system/output/morning-log-{today}.json` — what happened today
4. `q-system/my-project/relationships.md` — check for unprocessed conversations

## Integration checks

| Integration | Used for | If unavailable |
|------------|----------|----------------|
| Notion | Check for interactions not debriefed | Skip, check local files only |

## Process

1. **Effort log** — Summarize what was accomplished today (track effort, not outcomes)
2. **Debrief check** — Were there conversations today that weren't debriefed? If so, flag them.
3. **Loop review** — Call `loop_list` to surface open loops. Close any that are resolved. Flag stale ones.
4. **Canonical drift check** — Were canonical files changed today? Do they have proper decision tags?
5. **Tomorrow preview** — What's on the calendar? What loops are due? What actions were deferred?
6. **Auto-chain to /q-handoff** — Generate session context note (see `/q-handoff` skill)

## MCP tools used

`loop_list`, `loop_close`, `loop_stats`, `log_step`

## Output rules

- Apply `audhd-executive-function` skill if enabled
- Lead with what went well before surfacing gaps
- No pressure language about missed items — just "carried forward to tomorrow"
- Keep it under 10 minutes of reading time
