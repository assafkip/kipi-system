# Q Founder OS

## About
A portable founder operating system for Claude Code. Strategy, execution, relationship management, content pipeline, and daily routines - all running from your terminal.

@q-system/CLAUDE.md

## Tech Stack
- Claude Code with MCP server integrations
- Notion API for CRM and task management (optional)
- Google Calendar + Gmail for scheduling and email (optional)
- Apify for data scraping - LinkedIn, Reddit, Medium, X (optional)
- Chrome automation for LinkedIn DMs and engagement (optional)
- Gamma API for deck/one-pager generation (optional)
- NotebookLM for research content (optional)

## Project Structure

User data lives outside the repo under `${CLAUDE_PLUGIN_DATA}` (provided by Claude Code plugin system). Read the `kipi://paths` MCP resource to resolve all paths at runtime.

### Git repo (system code only)
- `q-system/` - Core operating system
  - Commands, preflight, audit harness
  - `agent-pipeline/` - Decomposed agent architecture for morning routine
    - `agents/` - 49 agent prompt files (one per task)
    - `orchestrator-design.md` - Phase execution plan
    - `templates/` - Reusable folder structures for repeatable outputs
- `kipi-mcp/` - Python MCP server package (schedule builder, step logger, loop tracker, template creator, validation, instance management)
  - `paths.py` - Path resolution for all user data directories
  - `migrator.py` - Migration tool from legacy in-repo layout to plugin directories
  - `canonical/` - Default/template canonical files
  - `marketing/` - Content pipeline, templates, assets, guardrails
  - `methodology/` - Debrief template and workflows
- `.claude/skills/` - AUDHD executive function + founder voice skills
- `.claude/rules/` - Security, coding standards, content output rules

### User data directories
All user data lives under `${CLAUDE_PLUGIN_DATA}` (provided by Claude Code plugin system). Read the `kipi://paths` MCP resource for resolved paths.

- **Global** (`{base}/global/`): voice DNA, AUDHD profile (shared across instances)
- **Per-instance** (`{base}/instances/{name}/`): founder-profile, canonical/, marketing/, my-project/, memory/, output/, bus/, metrics.db
- **Registry** (`{base}/instance-registry.json`): maps instances to metadata

## Conventions
- Never produce fluff - every sentence must carry information or enable action
- Mark unvalidated claims with `{{UNVALIDATED}}` or `{{NEEDS_PROOF}}`
- All written output goes through the founder voice skill
- All actionable output follows AUDHD executive function rules (if enabled)
- No filler phrases ("leverage," "innovative," "cutting-edge," "game-changing")

## Commands
- `/q-morning` - Full morning briefing (agent pipeline: 9 phases, 49 sub-agents). Reads orchestrator from `agent-pipeline/step-orchestrator.md`, spawns agents per phase, communicates through `bus/` JSON files.
- `/q-debrief` - Post-conversation extraction (highest priority)
- `/q-calibrate` - Update canonical files
- `/q-create` - Generate specific output. Use templates from `agent-pipeline/templates/` for repeatable outputs (deck, outreach, content, debrief).
- `/q-plan` - Review and prioritize actions
- `/q-engage` - Social engagement mode
- `/q-market-*` - Marketing system commands
- `/q-market-review` - Content review runs 4 Sonnet passes (voice, guardrails, anti-AI, actionability) via Agent tool. Review pipeline pass definitions are in `kipi-mcp/server.py` docstrings.
- `/q-draft` - Ad-hoc output generation. Use templates from `agent-pipeline/templates/` when format matches.
- `/q-wrap` - Evening health check
- `/q-handoff` - Session continuity

## Build and Test
- Build daily schedule: Use the `kipi_build_schedule` MCP tool
- Audit morning routine: Use the `kipi_audit_morning` MCP tool with log_file="{state_dir}/output/morning-log-YYYY-MM-DD.json"

## Token Discipline (NON-NEGOTIABLE)

- If a tool call fails, do NOT retry the same call. Diagnose why it failed first. Change the approach.
- After 10 tool calls, pause and check: "Am I closer to the goal than 10 calls ago?" If not, stop and tell the founder.
- Never spawn an Explore/research agent for something a single Grep or Glob could answer.
- Before spawning any Agent, ask: "Is this worth 50K+ tokens?" If the answer is "maybe," use direct tools instead.
- If you've read 5+ files without writing anything, stop and tell the founder what you're looking for and why.
- Never hold large API responses in context. Process and discard immediately.
- When blocked, do NOT brute-force. Try a different approach or ask the founder.

## Tool Preferences
- Use project-scoped Notion API server for CRM (not workspace-wide plugins)
- Use Apify for data scraping, Chrome for interactive/DMs only
- Gamma for decks and one-pagers (if configured)

## Collaboration Workflow

- This is a collaborative project using trunk-based development with short-lived branches.
- Always pull the latest changes before starting work (handled automatically by SessionStart hook).
- Keep commits small and focused. Write clear commit messages.
- Use `git pull --rebase` to keep history linear.
- Do not rebase commits that have already been pushed.

## Code Quality

- Follow TDD for all new code. See `.claude/rules/` for language-specific testing standards.
- Security rules in `.claude/rules/security.md` apply to all code — no exceptions.
- Run the test suite before committing. Do not commit code with failing tests.
