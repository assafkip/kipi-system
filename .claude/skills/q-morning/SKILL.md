# /q-morning — Daily morning briefing

The only command you need to start a day. Runs an 8-phase agent pipeline: calendar, email, Notion, social, lead sourcing, engagement hitlist, synthesis, and schedule build. Auto-checkpoints previous session, catches missed debriefs, loads canonical state.

## Preconditions

Read these files FIRST, in this order:
1. `q-system/.q-system/preflight.md` — tool manifest, known issues, fallback chains. **MANDATORY before anything else.**
2. `q-system/my-project/enabled-integrations.md` — which tools are available
3. `q-system/my-project/founder-profile.md` — user context and accommodations
4. `q-system/.q-system/steps/step-orchestrator.md` — full phase execution plan
5. `memory/last-handoff.md` — prior session context (if exists)

## Integration checks

All integrations are OPTIONAL. Check `enabled-integrations.md` and skip unavailable ones:

| Integration | Used in | If unavailable |
|------------|---------|----------------|
| Notion | Pipeline pull, CRM sync, Notion push | Skip those phases, work from local files |
| Google Calendar | Calendar pull | Skip, note "no calendar data" |
| Gmail | Email pull | Skip, note "no email data" |
| Apify | LinkedIn/X scraping, lead sourcing | Skip social scraping, user provides posts manually |
| Playwright | LinkedIn DMs | Skip DM automation |

Report what was skipped in the morning briefing summary.

## Process

1. **Read preflight.md** — verify all required tools are reachable. If any REQUIRED tool fails, STOP (fail-fast).
2. **Read step-orchestrator.md** — this is the full phase plan with agent assignments
3. **Create bus directory:** `q-system/.q-system/agent-pipeline/bus/{today's date}/`
4. **Initialize morning log:** Call `log_init` MCP tool with today's date
5. **Run phases 0-8** per step-orchestrator.md:
   - Spawn sub-agents via the Agent tool per phase
   - Agents communicate through JSON files in bus/, not through context
   - Parallel phases: dispatch multiple Agent calls in a single message
   - Each agent reads only the bus/ files it needs and writes one JSON result
6. **Log each step** via `log_step` MCP tool as phases complete
7. **Build daily schedule** via `build_schedule` MCP tool
8. **Run audit harness:** `python3 q-system/.q-system/audit-morning.py q-system/output/morning-log-{date}.json`
9. **Show audit results** to the founder. This is NOT optional.

## Model allocation

- **Sonnet:** All data pulls and checks (phases 0-4, 6, 8)
- **Opus:** Engagement hitlist (phase 5) and synthesis (phase 7) ONLY

## Fail-fast rule

If any MCP server is unavailable or any step fails during execution, STOP the entire routine immediately. Report what broke. Do NOT continue with partial data. The founder fixes the issue and re-runs.

## MCP tools used

`log_init`, `log_step`, `log_add_card`, `log_deliver_cards`, `log_gate_check`, `log_checksum`, `log_verify`, `loop_escalate`, `loop_list`, `loop_stats`, `load_step`, `build_schedule`

## Output rules

- Apply `founder-voice` skill to all written output
- Apply `audhd-executive-function` skill if enabled in founder-profile.md — this governs ALL output from Step 0e onward
- Schedule HTML is generated ONLY via `build_schedule` MCP tool from JSON data. Claude NEVER writes raw HTML.
- Full post text rule: agents reading social posts MUST save actual post text, not summaries

## Fallback

If the agent pipeline fails, the old monolithic steps in `.q-system/steps/` still work via the `load_step` MCP tool.
