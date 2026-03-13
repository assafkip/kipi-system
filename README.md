# Q Founder OS

An AI-powered operating system for startup founders. It runs inside [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and manages your entire day: relationships, pipeline, content, outreach, meeting prep, and follow-ups.

You talk to it. It remembers everything. It writes in your voice. It tells you exactly what to do next and gives you the copy-paste text to do it.

## Who this is for

Solo founders and tiny teams who are doing sales, marketing, content, investor outreach, and product at the same time. Especially founders who:

- Lose track of follow-ups and conversations
- Spend too much time context-switching between tools
- Want their outreach to sound like them, not like AI
- Have ADHD/ASD and need external structure (optional AUDHD mode built in)

## What it does

**Morning routine (`/q-morning`):** One command generates your entire day. Calendar, email, CRM, social posts, engagement hitlists, lead sourcing, meeting prep, pipeline health. Everything lands in a single HTML file with checkboxes, copy buttons, and time estimates. You copy, paste, and check things off.

**Relationship engine:** The system tracks every prospect through a 5-stage ladder (warm up, connect, first DM, conversation, demo). It generates the next action for each person, pre-written and copy-paste ready. You never decide who to contact or what to say. You just execute.

**Voice matching:** Feed it your writing samples and it learns how you actually communicate. Every DM, email, comment, and post sounds like you, not like AI. It knows your vocabulary, your patterns, your pet peeves.

**Conversation memory:** Paste a meeting transcript and the system extracts what resonated, what got pushback, what you owe them, and what to say next time. Insights route automatically to the right files. After 50 conversations, your talk tracks are battle-tested.

**Content engine:** Daily social posts, weekly thought leadership, engagement hitlists with copy-paste comments for your prospects' posts. All in your voice, all grounded in what you've actually learned from conversations.

**AUDHD mode (optional):** If you have ADHD/ASD, the system becomes your external executive function. Items ordered by friction (lowest first for dopamine momentum). Energy-tagged tasks (Quick Win / Deep Focus / People / Admin). No shame language. Effort tracking, not outcome tracking. The system decides, you execute.

## Setup

### 1. Install Claude Code

```bash
npm install -g @anthropic-ai/claude-code
```

You need an Anthropic API key. Get one at https://console.anthropic.com

### 2. Clone this repo

```bash
git clone https://github.com/assafkip/q-founder-os.git
cd q-founder-os
```

### 3. Start Claude Code

```bash
claude
```

That's it. The system detects it's a fresh install and walks you through setup one step at a time.

## What the setup wizard asks

The wizard asks one category at a time. You answer, it confirms, you move to the next.

| Step | What it asks | Where it saves |
|------|-------------|----------------|
| 1. Who are you? | Name, role, company, stage, co-founder | `founder-profile.md` |
| 2. Who do you sell to? | Buyer, industry, pain, alternatives, price | `current-state.md`, `discovery.md` |
| 3. Your positioning | One-liner, metaphors, what you're NOT, top objections | `talk-tracks.md`, `objections.md` |
| 4. Your voice | Style, words you use, words you hate, writing samples | `voice-dna.md`, `writing-samples.md` |
| 5. Your tools | Notion, Google Calendar, Gmail, LinkedIn, Apify | `settings.json` snippets |
| 6. Your CRM | Notion databases or local markdown files | `notion-ids.md` |
| 7. Your network | Top 10 contacts, investors, partners, advisors | `relationships.md` |
| 8. Confirmation | Summary review, verify everything loaded | Removes setup flag |

## Commands

### Daily workflow

| Command | What it does |
|---------|-------------|
| `/q-morning` | Full morning briefing + daily HTML schedule. The only command you need to start a day. |
| `/q-wrap` | 10-minute end-of-day health check. Effort log, debrief check, tomorrow preview. |
| `/q-handoff` | Save session context so the next session picks up where you left off. |

### After conversations

| Command | What it does |
|---------|-------------|
| `/q-debrief` | Process a conversation. Or just paste a transcript and it runs automatically. |
| `/q-draft` | Quick one-off email, DM, or talking points. |

### Outreach and engagement

| Command | What it does |
|---------|-------------|
| `/q-engage` | Social engagement hitlist. Copy-paste comments for your prospects' posts. |
| `/q-create` | Generate talk tracks, emails, slides for a specific audience. |
| `/q-plan` | Review pipeline, relationships, and proof gaps. Prioritize next actions. |

### Content

| Command | What it does |
|---------|-------------|
| `/q-market-create` | Generate LinkedIn, X, Medium, or email content. |
| `/q-market-plan` | Weekly content planning against your theme rotation. |
| `/q-market-publish` | Mark content as published, update tracking. |

### System

| Command | What it does |
|---------|-------------|
| `/q-status` | Quick snapshot of where things stand. |
| `/q-reality-check` | Challenger mode. Stress-tests your positioning against evidence. |
| `/q-investor-update` | Draft a milestone-triggered investor update for your full VC list. |

## How the system learns

Every conversation makes the system smarter. The debrief template extracts what resonated, what got pushback, and what you couldn't answer. Those extractions route to canonical files:

- **Objections** get logged with responses that worked
- **Talk tracks** get tagged by audience and updated with phrases that landed
- **Discovery questions** track what buyers ask and how you answered
- **Relationship files** remember what each person cares about
- **A knowledge graph** maps who knows whom, who cares about what, and how people connect

The system also predicts what each conversation will surface before you describe it. When predictions are wrong, it reveals gaps in what it knows. Over time, predictions get more accurate.

## How outreach improves

Every outreach message is tagged with a style code (value drop, genuine question, peer observation, content reference, warm intro). The system tracks which styles get replies and shifts toward what works for your specific audience.

Monthly calibration reports show prediction accuracy and reply rates by style. If your high-confidence predictions are wrong more than half the time, the system tells you.

## File structure

```
q-founder-os/
├── CLAUDE.md                    # System brain (behavioral rules, setup wizard)
├── q-system/
│   ├── .q-system/
│   │   └── commands.md          # All command definitions and workflows
│   ├── canonical/               # What you've learned (objections, talk tracks, decisions)
│   ├── my-project/              # Your context (profile, relationships, state)
│   ├── methodology/             # Debrief template, process docs
│   ├── marketing/               # Content system (templates, guardrails, themes)
│   ├── memory/
│   │   ├── working/             # Session-scoped scratch (auto-cleaned after 48h)
│   │   ├── weekly/              # 7-day rolling insights (reviewed Mondays)
│   │   ├── monthly/             # Persistent patterns (reviewed 1st of month)
│   │   ├── graph.jsonl          # Entity-relationship knowledge graph
│   │   ├── last-handoff.md      # Session continuity note
│   │   └── morning-state.md     # Morning routine state tracker
│   └── output/                  # Generated files (HTML schedules, drafts, outreach)
├── .claude/
│   └── skills/
│       ├── audhd-executive-function/  # ADHD accommodation rules
│       └── founder-voice/             # Voice matching engine
└── .agents/
    └── product-marketing-context.md   # Marketing foundation
```

## Optional integrations

The system works without any integrations (local files only). Each tool you connect makes it more powerful:

| Tool | What it enables |
|------|----------------|
| **Notion** | CRM with contacts, interactions, pipeline, engagement tracking |
| **Google Calendar** | Meeting detection, prep generation, schedule awareness |
| **Gmail** | Email monitoring, unlogged conversation detection |
| **Apify** | LinkedIn/X/Reddit/Medium scraping for lead sourcing and engagement |
| **Chrome** | LinkedIn DM reading, Google Analytics, interactive browsing |
| **Telegram** | Push notifications for top daily actions |

## Built by

[Assaf Kipnis](https://www.linkedin.com/in/assafkipnis/) - founder of [KTLYST](https://ktlystlabs.com), 12 years in threat intelligence (LinkedIn, Google, Meta, ElevenLabs). Built this to manage the cognitive overhead of running a pre-seed startup solo with ADHD. Then open-sourced it because the problem is universal.
