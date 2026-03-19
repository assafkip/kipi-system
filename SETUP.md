# Q Founder OS - Setup Guide

A persistent founder operating system that runs inside Claude Code. It manages your relationships, generates content, tracks pipeline, processes conversations, and eliminates the cognitive overhead of running a startup.

## What You Get

- **Morning briefing** that pulls calendar, email, CRM, and generates your entire day as a copy-paste-ready HTML workbench
- **Conversation debriefs** that extract insights and route them to the right canonical files automatically
- **Social engagement system** that generates copy-paste comments, DMs, and connection requests
- **Relationship progression engine** that manages prospect relationships from cold to partner
- **Content pipeline** with theme rotation, guardrails, and cross-platform publishing
- **Lead sourcing** across LinkedIn, Reddit, X, and Medium with personalized outreach generation
- **Voice engine** that makes everything sound like you, not AI
- **AUDHD executive function mode** (optional) for neurodivergent founders
- **Security hardening** with deny rules, PreToolUse hooks, and path-scoped rules

## Quick Start

### 1. Install Claude Code
Follow the official installation at https://docs.anthropic.com/en/docs/claude-code

### 2. Clone this repo
```bash
git clone https://github.com/assafkip/kipi-system.git
cd kipi-system
```

### 3. Set up environment variables
The system uses environment variable references for secrets. Set these in your shell profile:

```bash
# Required (if using Notion CRM)
export NOTION_TOKEN="your-notion-token"

# Recommended (for lead sourcing)
export APIFY_TOKEN="your-apify-token"
```

Get your Notion token at https://www.notion.so/my-integrations
Get your Apify token at https://apify.com (Account > Integrations)

### 4. Configure Claude Code global settings
Copy `settings-template.json` to `~/.claude/settings.json` (or merge into your existing settings). This configures MCP servers in your global settings.

The project already ships with:
- `.claude/settings.json` - project-level permissions, deny rules, and security hooks
- `.mcp.json` - project-level MCP server config (uses `${ENV_VAR}` references)
- `.claude/rules/` - security, coding standards, and content output rules

**Claude.ai MCP servers (configured in the Claude.ai web interface, not settings.json):**
- Google Calendar
- Gmail
- Chrome (for LinkedIn DMs, GA4)
- Gamma (for slide decks)
- NotebookLM (for research notebooks)

### 5. Install recommended plugins
In Claude Code, enable these plugins:
- `document-skills@anthropic-agent-skills`
- `Notion@claude-plugins-official`
- `github@claude-plugins-official`

### 6. Install marketing skills (optional but recommended)
Clone https://github.com/coreyhaines31/marketingskills into `.agents/skills/`.
These provide 32 specialized marketing skills (cold email, copywriting, SEO, CRO, etc.).

### 7. Start Claude Code in this folder
```bash
cd /path/to/q-founder-os
claude
```

The system will detect `{{SETUP_NEEDED}}` in `founder-profile.md` and walk you through setup interactively. It asks questions one category at a time:

1. **Who are you?** (name, role, company, stage)
2. **Who do you sell to?** (buyer, pain, alternatives)
3. **What's your positioning?** (one-liner, metaphors, misclassifications, objections)
4. **Your voice** (writing style, words you use/avoid, samples)
5. **Your tools** (which MCP servers to configure)
6. **Your CRM** (Notion database setup or local-only mode)
7. **Your network** (top 10 contacts to seed the system)

### 8. Run your first morning
```
/q-morning
```

This generates the daily schedule HTML and opens it in your browser.

## Directory Structure

```
q-founder-os/
  CLAUDE.md                          # Entry point with @imports to q-system/CLAUDE.md
  .mcp.json                          # MCP server config (env var refs, no secrets)
  .claude/
    settings.json                    # Deny rules, PreToolUse hooks, effort level
    rules/
      security.md                    # Blocks .env/credentials/key file access
      coding-standards.md            # Code style rules (path-scoped to code files)
      content-output.md              # Content generation rules (path-scoped to output/)
    skills/
      audhd-executive-function/      # ADHD/ASD accommodations (optional)
        SKILL.md
        references/
          research.md                # Academic research (Barkley, Mahan, Dodson)
          user-profile.md            # Your AUDHD behavioral profile
      founder-voice/                 # Your writing voice
        SKILL.md
        references/
          voice-dna.md               # Your voice profile
          writing-samples.md         # Real examples of your writing
  .agents/
    product-marketing-context.md     # Marketing foundation
    skills/                          # Marketing skills (32 skills from Corey Haines)
  q-system/
    CLAUDE.md                        # Full behavioral rules + setup wizard
    .q-system/
      commands.md                    # All slash commands defined here
      preflight.md                   # Tool manifest + fail-fast protocol
      audit-morning.py               # Post-morning audit harness
      log-step.sh                    # Step completion logger
      state-model.md                 # Progress tracking model
    canonical/                       # Your positioning knowledge base
      objections.md                  # Pushback heard + responses
      discovery.md                   # Questions asked + answers
      talk-tracks.md                 # Proven language
      decisions.md                   # Active decision rules
      engagement-playbook.md         # Social engagement rules
      lead-lifecycle-rules.md        # Lead management rules
      market-intelligence.md         # Buyer language + market signals
      content-intelligence.md        # Content performance data
    my-project/                      # Your project state
      founder-profile.md             # Who you are (triggers setup wizard)
      current-state.md               # What works today vs. vision
      relationships.md               # All contacts + conversation history
      competitive-landscape.md       # Alternatives and substitutes
      progress.md                    # Session log
      notion-ids.md                  # Notion database IDs
    methodology/
      debrief-template.md            # Conversation extraction template (12 lenses)
    marketing/
      README.md                      # Marketing system overview
      content-guardrails.md          # Quality gates
      content-themes.md              # Theme rotation
      brand-voice.md                 # Channel-specific voice rules
      templates/
        daily-schedule-template.html # The daily HTML workbench (LOCKED)
        build-schedule.sh            # JSON to HTML builder
        schedule-data-schema.md      # JSON schema for daily data
        linkedin-thought-leadership.md
        outreach-email.md
        follow-up-email.md
      assets/
        boilerplate.md               # Reusable copy blocks
        founder-bio.md               # Your bio
        stats-sheet.md               # Numbers and proof points
        proof-points.md              # Evidence and validation
        competitive-one-liners.md    # Competitive positioning
    output/                          # Generated files go here
      drafts/
      lead-gen/
      design-partner/
      marketing/linkedin/
    seed-materials/                  # Drop docs here for /q-ingest-feedback
    memory/
      working/                       # Session-scoped (<48h, auto-cleaned)
      weekly/                        # 7-day rolling (reviewed Mondays)
      monthly/                       # Persistent insights (reviewed 1st)
      graph.jsonl                    # Entity-relationship knowledge graph
      last-handoff.md                # Session continuity note
      morning-state.md               # Morning routine state
      marketing-state.md             # Content system state
  memory/
    MEMORY.md                        # Memory index (auto-managed)
```

## Security

The project ships with three layers of security hardening:

1. **Permission deny rules** (`.claude/settings.json`): Blocks reading/writing `.env`, credentials, `.pem`, `.key` files. Blocks `rm -rf`, `sudo`, `git push --force`, `curl | bash`.

2. **PreToolUse hooks** (`.claude/settings.json`): Runtime interception that kills any Edit/Write action targeting sensitive files before it executes.

3. **Rules directory** (`.claude/rules/`): Path-scoped instructions that reinforce security, coding standards, and content output rules.

## Daily Workflow

1. Start Claude Code in this folder
2. Run `/q-morning` - gets your calendar, email, CRM, generates content, produces the HTML schedule
3. Open the HTML file - it's your entire day, copy-paste ready
4. After meetings, paste the transcript - the system auto-debriefs
5. Report engagement actions ("commented on X's post") - system auto-logs
6. End of day: run `/q-wrap` for health check (auto-chains into `/q-handoff`)

## Commands Reference

| Command | What it does |
|---------|-------------|
| `/q-morning` | Full morning briefing + HTML schedule |
| `/q-debrief [person]` | Process a conversation |
| `/q-create [type] [audience]` | Generate talk track, email, slides |
| `/q-draft [type]` | Quick one-off output |
| `/q-engage` | Social engagement hitlist |
| `/q-plan` | Prioritize next actions |
| `/q-calibrate` | Update positioning from new info |
| `/q-market-create [type]` | Generate content |
| `/q-market-plan` | Weekly content planning |
| `/q-status` | Quick snapshot |
| `/q-reality-check` | Stress-test your positioning |
| `/q-investor-update` | Draft investor update email |
| `/q-wrap` | End-of-day health check |

## Optional Add-ons

### Threat Intelligence MCP Server
If your work involves security consulting, due diligence, or domain/URL investigation:

```bash
git clone https://github.com/assafkip/threat-intel-mcp.git ~/threat-intel-mcp
claude mcp add threat-intel -s user -- uv run ~/threat-intel-mcp/server.py
```

Adds 4 tools: `vt_lookup` (VirusTotal), `urlhaus_lookup`, `threatfox_lookup`, `crt_lookup` (cert transparency). Requires free API keys -- see `q-system/tools/threat-intel-mcp/README.md`.

### OSINT Infrastructure MCP Server
Already included in `q-system/tools/osint-infra-mcp/`. Adds: `whois_lookup`, `dns_lookup`, `reverse_dns`, `wayback_snapshots`, `wayback_fetch`.

```bash
claude mcp add osint-infra -s user -- uv run --with "fastmcp>=2.0.0" --with "httpx>=0.27.0" q-system/tools/osint-infra-mcp/server.py
```
