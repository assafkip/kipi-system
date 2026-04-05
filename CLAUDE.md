# Q Entrepreneur OS

## About
A portable entrepreneur operating system for Claude Code. Strategy, execution, relationship management, content pipeline, and daily routines - all running from your terminal.

@q-system/CLAUDE.md

## Tech Stack
- Claude Code with MCP server integrations
- Marketplace-distributed plugins (kipi-core, kipi-ops, kipi-design)
- Notion API for CRM and task management (optional)
- Google Calendar + Gmail for scheduling and email (optional)
- Apify for X/Twitter scraping only (optional)
- Reddit MCP for Reddit data (no auth needed)
- Chrome automation for LinkedIn (profiles, posts, DMs, engagement) (optional)
- RSS feeds for Medium, Substack content (free, no auth needed)
- Gamma API for deck/one-pager generation (optional)

## Project Structure
- `plugins/` - Plugin groups (loaded directly from disk)
  - `kipi-core/` - AUDHD executive function + founder voice + research mode (every instance)
  - `kipi-ops/` - Council debates + customer fit reviews (GTM instances)
  - `kipi-design/` - UI/UX, brand identity, visual assets (design instances)
- `.claude/agents/` - Custom agent definitions (preflight, data-ingest, synthesizer, etc.)
- `.claude/output-styles/` - Entrepreneur OS output style (always-on voice baseline)
- `.claude/rules/` - Path-scoped instruction files (14 rules)
- `q-system/` - Core operating system
  - `.q-system/agent-pipeline/` - 9-phase morning routine (50+ agent prompts)
  - `canonical/` - Source of truth files (positioning, objections, talk tracks)
  - `marketing/` - Content pipeline, templates, assets
  - `methodology/` - Debrief template and workflows
  - `output/` - Generated content, schedules, logs
  - `my-project/` - Current state, relationships, progress
  - `memory/` - Session state (last-handoff.md, sycophancy-log.json)
  - `hooks/` - Session lifecycle scripts (context injection, compaction recovery, effort logging)
- `kipi` - CLI for instance management
- `settings-template.json` - Template for new instances

## Conventions
- Never produce fluff - every sentence must carry information or enable action
- Mark unvalidated claims with `{{UNVALIDATED}}` or `{{NEEDS_PROOF}}`
- All written output goes through the founder voice skill
- All actionable output follows AUDHD executive function rules (if enabled)
- No filler phrases ("leverage," "innovative," "cutting-edge," "game-changing")

## Commands
- `/q-morning` - Full morning briefing (9-phase agent pipeline, 50+ sub-agents)
- `/q-debrief` - Post-conversation extraction (highest priority)
- `/q-calibrate` - Update canonical files
- `/q-create` - Generate specific output (talk tracks, emails, slides, decks)
- `/q-plan` - Review and prioritize actions
- `/q-engage` - Social engagement mode
- `/q-market-*` - Marketing system commands
- `/q-market-review` - Content review (4 Sonnet passes via content-reviewer agent)
- `/q-draft` - Ad-hoc output generation
- `/q-wrap` - Evening health check
- `/q-handoff` - Session continuity
- `/q-research` - Anti-hallucination research mode (citation-enforced, token-budgeted)

## Hooks
- **SessionStart** - Injects date, last handoff, founder context
- **UserPromptSubmit** - Resets token guard per-message counters
- **PreToolUse** - Token guard circuit breaker (retry limits, volume ceiling, agent limits)
- **PostCompact** - Re-injects mode, loop count, voice reminders after compaction
- **Stop** - Async session effort logging

## Build and Test
- Build daily schedule: `python3 q-system/marketing/templates/build-schedule.py <json> <html>`
- Audit morning routine: `python3 q-system/.q-system/audit-morning.py q-system/output/morning-log-YYYY-MM-DD.json`
- Develop with plugins: `kipi dev` (loads all 3 plugin groups)

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
- Use Chrome for all LinkedIn data (profiles, posts, DMs, engagement). Use Reddit MCP for Reddit. Use Apify for X/Twitter only. Use RSS feeds (WebFetch) for Medium, Substack.
- Gamma for decks and one-pagers (if configured)
