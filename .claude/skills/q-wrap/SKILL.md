# /q-wrap — Evening health check

10-minute end-of-day system health check. Closes open loops, catches missed debriefs, checks canonical drift, previews tomorrow. Auto-chains into `/q-handoff` at the end — never run both separately.

## Setup guard

**FIRST:** Call `kipi_paths_info` MCP tool to get resolved directory paths. Use these paths for all file operations below.

Read `{config_dir}/founder-profile.md`. If it contains `{{SETUP_NEEDED}}`, STOP and tell the user:

> This system hasn't been configured yet. Run `/q-setup` first to set up your profile, integrations, and canonical files.

Do not proceed with any other steps.

## Preconditions

Read these files:
1. `{config_dir}/enabled-integrations.md`
2. `{config_dir}/founder-profile.md`
3. `{state_dir}/output/morning-log-{today}.json` — what happened today
4. `{data_dir}/my-project/relationships.md` — check for unprocessed conversations

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
