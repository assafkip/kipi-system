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

## Quick Start

### 1. Install Claude Code
Follow the official installation at https://docs.anthropic.com/en/docs/claude-code

### 2. Clone/copy this folder
Put `q-founder-os/` wherever you want on your machine.

### 3. Configure Claude Code settings
Copy `settings-template.json` to `~/.claude/settings.json` (or merge into your existing settings).

**Required tokens (get these first):**
- **Notion** (recommended): Create an integration at https://www.notion.so/my-integrations
- **Apify** (recommended for lead sourcing): Sign up at https://apify.com, get token from Account > Integrations

**Optional tokens:**
- **Telegram:** Get credentials at https://my.telegram.org
- **Reddit:** No token needed for the MCP buddy

**Claude.ai MCP servers (configured in the Claude.ai web interface, not settings.json):**
- Google Calendar
- Gmail
- Chrome (for LinkedIn DMs, GA4)
- Gamma (for slide decks)
- NotebookLM (for research notebooks)

### 4. Install recommended plugins
In Claude Code, enable these plugins:
- `document-skills@anthropic-agent-skills`
- `Notion@claude-plugins-official`
- `github@claude-plugins-official`

### 5. Install marketing skills (optional but recommended)
Clone https://github.com/coreyhaines31/marketingskills into `.agents/skills/`.
These provide 32 specialized marketing skills (cold email, copywriting, SEO, CRO, etc.).

### 6. Start Claude Code in this folder
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

### 7. Run your first morning
```
/q-morning
```

This generates the daily schedule HTML and opens it in your browser.

## Directory Structure

```
q-founder-os/
  CLAUDE.md                          # The brain - behavioral rules + setup wizard
  SETUP.md                           # This file
  settings-template.json             # Claude Code settings (copy to ~/.claude/)
  .claude/
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
    skills/                          # Marketing skills (32 skills from Corey Haines)
  q-system/
    .q-system/
      commands.md                    # All slash commands defined here
    canonical/                       # Your positioning knowledge base
      objections.md                  # Pushback heard + responses
      discovery.md                   # Questions asked + answers
      talk-tracks.md                 # Proven language
      decisions.md                   # Active decision rules
      engagement-playbook.md         # Social engagement rules
      lead-lifecycle-rules.md        # Lead management rules
      content-intelligence.md        # Content performance data
    my-project/                      # Your project state
      founder-profile.md             # Who you are (triggers setup wizard)
      current-state.md               # What works today vs. vision
      relationships.md               # All contacts + conversation history
      competitive-landscape.md       # Alternatives and substitutes
      progress.md                    # Session log
      notion-ids.md                  # Notion database IDs
    methodology/
      debrief-template.md            # Conversation extraction template
    marketing/
      README.md                      # Marketing system overview
      content-guardrails.md          # Quality gates
      content-themes.md              # Theme rotation
      brand-voice.md                 # Channel-specific voice rules
      templates/
        daily-schedule-template.html # The daily HTML workbench
        linkedin-thought-leadership.md
        cold-outreach.md
      assets/
        boilerplate.md               # Reusable copy blocks
        stats-sheet.md               # Numbers and proof points
    output/                          # Generated files go here
      drafts/
      lead-gen/
      design-partner/
      marketing/linkedin/
    seed-materials/                  # Drop docs here for /q-ingest-feedback
  memory/
    MEMORY.md                        # Memory index (auto-managed)
```

## Daily Workflow

1. Start Claude Code in this folder
2. Run `/q-morning` - gets your calendar, email, CRM, generates content, produces the HTML schedule
3. Open the HTML file - it's your entire day, copy-paste ready
4. After meetings, paste the transcript - the system auto-debriefs
5. Report engagement actions ("commented on X's post") - system auto-logs
6. End of day: the system checkpoints automatically

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
