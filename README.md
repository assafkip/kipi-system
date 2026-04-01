## The Kipi System

**Your AI brain. Externalized.**

Your brain knows who you need to follow up with. It just doesn't remind you. Your brain knows what that person said last month that mattered. It just can't find it. Your brain knows exactly what email to write. It just won't write it for you.

The Kipi System is the part of your brain that remembers everything, connects everything, and turns everything into the next action. It runs in Claude Code. It learns from every conversation you have. It produces your entire day as a single file: every action pre-written, every follow-up drafted, every open thread tracked.

You copy, paste, check the box, move on.

---

## Quick Start

```bash
/plugin marketplace add assafkip/kipi-system
/plugin install kipi-system@kipi
```

Then run `/q-setup` to create your instance. Takes about 20 minutes.

### Required MCP servers

Install these before using the plugin:

```bash
claude mcp add google-calendar -- npx -y @anthropic/google-calendar-mcp
claude mcp add gmail -- npx -y @anthropic/gmail-mcp
claude mcp add apify -e APIFY_TOKEN=your_token -- npx -y @apify/actors-mcp-server
```

### Optional MCP servers

```bash
claude mcp add notion -e NOTION_TOKEN=your_token -- npx -y @notionhq/notion-mcp-server
claude mcp add reddit -- uvx --from git+https://github.com/adhikasp/mcp-reddit.git mcp-reddit
```

Chrome MCP is configured in Claude.ai settings (needed for LinkedIn data).

### First run

```
/q-morning full
```

The `full` flag does a complete data harvest from all sources. After the first run, normal `/q-morning` uses incremental mode with smart resume.

---

## Daily Workflow

1. Run `/q-morning` — harvests your calendar, email, CRM, social platforms. Runs analysis agents. Produces an HTML schedule.
2. Open the HTML file — your entire day, copy-paste ready. Start at the top, work down.
3. After meetings, paste the transcript — the system auto-debriefs.
4. End of day: `/q-wrap` for health check.

### What `/q-morning` produces

- **Copy-paste actions sorted by friction.** 2-minute replies first, deep work later.
- **Every follow-up pre-written in your voice.** Not AI voice. YOUR voice.
- **Open loops with escalation.** Sent a DM 7 days ago with no reply? Follow-up already drafted. 14 days? Forces a decision.
- **Meeting prep with context.** Who you're meeting, what you discussed last time, suggested talking points.

---

## Commands

| Command | What it does |
|---------|-------------|
| `/q-morning` | Generate your entire day (incremental harvest) |
| `/q-morning full` | Full re-harvest from all sources (first run, config changes) |
| `/q-debrief` | Process a conversation (or just paste a transcript) |
| `/q-health` | System diagnostic — check all dependencies and data health |
| `/q-backup` | Create, list, restore, or export backups |
| `/q-setup` | First-time setup wizard |
| `/q-create` | Generate a structured deliverable |
| `/q-draft` | Draft a quick email or DM |
| `/q-plan` | Prioritize next actions |
| `/q-engage` | Get engagement actions for prospects' posts |
| `/q-calibrate` | Update your positioning from new info |
| `/q-reality-check` | Stress-test your positioning |
| `/q-market-create` | Generate marketing content |
| `/q-market-review` | Review content before publishing |
| `/q-market-plan` | Plan your week's content |
| `/q-market-publish` | Mark content as published |
| `/q-content-intel` | Scrape and score content across platforms |
| `/q-research` | Citation-verified research mode |
| `/q-investor-update` | Draft investor update email |
| `/q-wrap` | End-of-day health check |
| `/q-handoff` | Save context for next session |

---

## Nothing Gets Forgotten

Every outbound action opens a loop. Every loop has a timer.

| Days open | What happens |
|-----------|-------------|
| 0-2 | Quiet. Listed in your dashboard. |
| 3-6 | Follow-up drafted. Shows in your action plan. |
| 7-13 | Flagged. Shows at the top. "This is going cold." |
| 14+ | Forced decision. Act now, park, or kill it. |

Loops auto-close when the system detects a response. Gmail reply? Closed. LinkedIn DM reply? Closed. Connection accepted? Closed.

---

## Built for ADHD. Works for Everyone.

Every design decision comes from AUDHD (ADHD + Autism):

- **No decisions.** The system picks who to contact, what to say, in what order.
- **No shame.** Never "overdue." Always "carried forward."
- **Friction-ordered.** Quick wins first. Dopamine before discipline.
- **Effort-tracked.** "You sent 4 messages today" matters more than "nobody responded yet."

Enable AUDHD mode during `/q-setup` or toggle it in `enabled-integrations.md`.

---

## Data Architecture

### Three databases

| Database | Purpose | Retention |
|----------|---------|-----------|
| `metrics.db` | Content performance, outreach logs, behavioral signals, A/B tests | Permanent |
| `harvest.db` | Harvest runs, source cursors, agent metrics, Notion queue | 7-day TTL on harvest data |
| `system.db` | Open loops, session handoffs | Loops: permanent until closed |

### Data sources (22 configured)

Sources are defined as YAML files in `kipi-mcp/sources/`. Add a new source by creating a YAML file — no code changes needed.

| Method | Sources | Cost |
|--------|---------|------|
| Python HTTP | GA4, VC pipeline, Medium RSS, Substack API | Free |
| Python Apify | X/Twitter (own posts + lead search) | ~$0.60-1.50/mo (free tier) |
| MCP (agent) | Gmail, Calendar, Reddit, Notion | Free |
| Chrome (agent) | LinkedIn (feed, DMs, notifications, analytics, prospects, outbound) | Free |
| Local file | Knowledge graph (graph.jsonl) | Free |

### Harvest flow

```
/q-morning
  → kipi_morning_init (Python: preflight, bootstrap, canonical digest, cleanup, backup)
  → kipi_harvest (Python: HTTP/Apify/local sources in parallel)
  → Chrome agent + MCP agent (LinkedIn + Gmail/Calendar/Reddit/Notion)
  → All data stored in SQLite via kipi_store_harvest
  → 30 analysis/content/synthesis agents read via kipi_get_harvest
  → 07-synthesize (opus) builds schedule JSON
  → kipi_build_schedule renders HTML
```

### Reliability features

- **Auto-backup:** 5 most recent backups rotated daily
- **Smart resume:** Partial runs auto-continue where they left off
- **Harvest health gate:** Warns if data is incomplete before synthesis
- **Notion write queue:** Failed writes retry next morning
- **SQLite integrity check:** Runs at every morning init
- **Canonical drift detection:** Alerts on unexpected file changes between sessions
- **Session handoff:** Split long runs across context windows

---

## Plugin Architecture

```
kipi-system/
├── .claude-plugin/plugin.json     Plugin manifest
├── .mcp.json                      MCP server config
├── skills/                        Slash commands + behavioral rules
│   ├── q-morning/SKILL.md         /q-morning
│   ├── q-health/SKILL.md          /q-health
│   ├── q-backup/SKILL.md          /q-backup
│   ├── founder-voice/SKILL.md     Voice enforcement
│   ├── audhd-executive-function/  AUDHD accommodations
│   └── ...                        34 skills total
├── kipi-mcp/                      MCP server (Python)
│   ├── src/kipi_mcp/
│   │   ├── server.py              66 MCP tools
│   │   ├── harvest_store.py       Harvest SQLite layer
│   │   ├── harvest_orchestrator.py Source execution engine
│   │   ├── source_registry.py     YAML source loader
│   │   ├── morning_init.py        Deterministic init (Python)
│   │   ├── metrics_store.py       Permanent metrics
│   │   ├── loop_tracker.py        Follow-up loop tracking
│   │   ├── executors/             HTTP, Apify, local, prompt generators
│   │   └── ...
│   ├── sources/                   22 YAML source configs
│   │   ├── linkedin-feed.yaml
│   │   ├── gmail.yaml
│   │   ├── chrome/                Chrome extraction instructions
│   │   └── ...
│   └── tests/                     619 tests
└── q-system/
    ├── agent-pipeline/
    │   ├── step-orchestrator.md   Phase execution plan
    │   └── agents/                30 agent prompts
    ├── marketing/                 Templates, brand voice
    └── hooks/                     Session start, token guard
```

Instance data lives outside the plugin in platform-appropriate directories, resolved via `kipi://paths`.

---

## Contributing

See `CLAUDE.md` for development setup, coding standards, and architecture details. Key rules:

- **TDD mandatory.** Write tests first: `uv run pytest tests/ --ignore=tests/test_git_ops.py -v`
- **Follow existing patterns.** Read `harvest_store.py` before writing store code.
- **Parameterized SQL only.** Never concatenate user input into queries.
- **No bus files.** All data through SQLite ledger.
- **Add sources via YAML**, not code. New `.yaml` file in `sources/` = new data source.

---

## Security

- No secrets in committed files — tokens configured per MCP server or via environment variables
- SQL injection protection via column whitelists and parameterized queries
- HTML sanitization on all user-facing output
- Path traversal protection on local file reads
- SQLite integrity checks at every startup
- Auto-rotating encrypted backups (5 most recent)

---

## Origin

Built by [Assaf Kipnis](https://www.linkedin.com/in/assafkipnis/). 12 years in threat intelligence at LinkedIn, Google, Meta, and ElevenLabs. Running a startup solo with ADHD meant building a second brain that manages investor pipeline, writes outreach in the founder's voice, preps meetings, tracks every open loop, and produces a daily HTML file that IS the workday.

Fork it and teach it yours.
