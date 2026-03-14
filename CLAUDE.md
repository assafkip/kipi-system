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
- `q-system/` - Core operating system
  - `.q-system/` - Commands, preflight, audit harness
  - `canonical/` - Source of truth files (positioning, objections, talk tracks)
  - `marketing/` - Content pipeline, templates, assets, guardrails
  - `methodology/` - Debrief template and workflows
  - `output/` - Generated content, drafts, lead gen results
  - `my-project/` - Current state, relationships, progress
  - `memory/` - Time-stratified memory (working/weekly/monthly)
- `.agents/` - Product marketing context
- `.claude/skills/` - AUDHD executive function + founder voice skills
- `.claude/rules/` - Security, coding standards, content output rules
- `memory/` - Session memory (MEMORY.md index + topic files)

## Conventions
- Never produce fluff - every sentence must carry information or enable action
- Mark unvalidated claims with `{{UNVALIDATED}}` or `{{NEEDS_PROOF}}`
- All written output goes through the founder voice skill
- All actionable output follows AUDHD executive function rules (if enabled)
- No filler phrases ("leverage," "innovative," "cutting-edge," "game-changing")

## Commands
- `/q-morning` - Full morning briefing (11 steps)
- `/q-debrief` - Post-conversation extraction (highest priority)
- `/q-calibrate` - Update canonical files
- `/q-create` - Generate specific output
- `/q-plan` - Review and prioritize actions
- `/q-engage` - Social engagement mode
- `/q-market-*` - Marketing system commands
- `/q-draft` - Ad-hoc output generation
- `/q-wrap` - Evening health check
- `/q-handoff` - Session continuity

## Build and Test
- Build daily schedule: `bash q-system/marketing/templates/build-schedule.sh <json> <html>`
- Audit morning routine: `python3 q-system/.q-system/audit-morning.py q-system/output/morning-log-YYYY-MM-DD.json`

## Tool Preferences
- Use project-scoped Notion API server for CRM (not workspace-wide plugins)
- Use Apify for data scraping, Chrome for interactive/DMs only
- Gamma for decks and one-pagers (if configured)
