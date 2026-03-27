# /q-morning — Daily morning briefing

The only command you need to start a day. Runs an 8-phase agent pipeline: calendar, email, Notion, social, lead sourcing, engagement hitlist, synthesis, and schedule build. Auto-checkpoints previous session, catches missed debriefs, loads canonical state.

## Setup guard

**FIRST:** Read `~/.config/kipi/founder-profile.md`. If it contains `{{SETUP_NEEDED}}`, STOP and tell the user:

> This system hasn't been configured yet. Run `/q-setup` first to set up your profile, integrations, and canonical files.

Do not proceed with any other steps.

## Path resolution

Read the `kipi://paths` MCP resource to get resolved directories. Key directories:
- **Config** (`~/.config/kipi/`): founder-profile, enabled-integrations, canonical/, voice/, marketing/
- **Data** (`~/.local/share/kipi/`): my-project/, memory/
- **State** (`~/.local/state/kipi/`): output/, bus/
- **Repo**: system code (agents, templates, steps) stays in the git repo

## Preconditions

Read these files FIRST, in this order:
1. `q-system/.q-system/preflight.md` — tool manifest, known issues, fallback chains. **MANDATORY before anything else.**
2. `~/.config/kipi/enabled-integrations.md` — which tools are available
3. `~/.config/kipi/founder-profile.md` — user context and accommodations
4. `q-system/.q-system/steps/step-orchestrator.md` — full phase execution plan
5. `~/.local/share/kipi/memory/last-handoff.md` — prior session context (if exists)

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
7. **Build daily schedule** via `kipi_build_schedule` MCP tool
8. **Run audit harness:** `python3 q-system/.q-system/audit-morning.py ~/.local/state/kipi/output/morning-log-{date}.json`
9. **Show audit results** to the founder. This is NOT optional.

## Model allocation

- **Sonnet:** All data pulls and checks (phases 0-4, 6, 8)
- **Opus:** Engagement hitlist (phase 5) and synthesis (phase 7) ONLY

## Fail-fast rule

If any MCP server is unavailable or any step fails during execution, STOP the entire routine immediately. Report what broke. Do NOT continue with partial data. The founder fixes the issue and re-runs.

## MCP tools used

`log_init`, `log_step`, `log_add_card`, `log_deliver_cards`, `log_gate_check`, `log_checksum`, `log_verify`, `loop_escalate`, `kipi://loops/open` (resource), `kipi://loops/stats` (resource), `kipi_load_step`, `kipi_build_schedule`

## Output rules

- Apply `founder-voice` skill to all written output
- Apply `audhd-executive-function` skill if enabled in founder-profile.md — this governs ALL output from Step 0e onward
- Schedule HTML is generated ONLY via `kipi_build_schedule` MCP tool from JSON data. Claude NEVER writes raw HTML.
- Full post text rule: agents reading social posts MUST save actual post text, not summaries

## Fallback

If the agent pipeline fails, the old monolithic steps in `.q-system/steps/` still work via the `kipi_load_step` MCP tool.
