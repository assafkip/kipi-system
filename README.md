# Q Instance

A decision-execution system built on Claude Code. It closes the gap between knowing what to do and actually doing it.

Most tools help you organize information. This one makes you act on it. Every output is copy-paste ready, pre-decided, and friction-ordered. The human's job is reduced to: execute or skip.

I built this for myself. I'm a solo founder with ADHD running a pre-seed startup. I was drowning in follow-ups, avoiding phone calls, and watching every open loop slowly die. So I built a system that tracks every loop, escalates what's going cold, writes the follow-up text for me, and produces a single HTML file every morning that IS my entire workday.

Then I realized the pattern isn't founder-specific. It's for anyone who manages concurrent relationships and can't afford to drop one.

## The pattern

Every knowledge worker does the same thing:

1. Process inputs (emails, meetings, reports, messages)
2. Decide what matters
3. Figure out what to do about it
4. Write the email, make the call, send the message
5. Track whether it worked

Most software helps with step 1 and 5. Nobody helps with 2, 3, and 4. That's the gap this system fills.

```
Unstructured input
    -> Extract what matters
        -> Store in canonical source of truth
            -> Track every open loop
                -> Produce executable daily output
                    -> Compound over time
```

## What it actually does

**Closes loops.** Every DM, email, connection request, and follow-up opens a tracked loop. 3 days without a response: warning. 7 days: prominent. 14 days: the system forces you to act, park, or kill the loop. Nothing gets forgotten.

**Debriefs conversations.** Paste a meeting transcript. The system extracts what resonated, what got pushback, new objections, and next steps. Insights route automatically to the right canonical files. After 50 conversations, your talk tracks are battle-tested without you maintaining them.

**Produces a daily action plan.** One HTML file with every task for the day. Each item has the actual copy-paste text, a link to where to send it, a time estimate, and an energy tag. Items sorted by friction: 2-minute tasks first for momentum, deep work later. You open the file, start at the top, and work down.

**Compounds knowledge.** What you learned from a conversation last month changes what the system suggests this week. Canonical files (positioning, objections, relationships, competitive landscape) are the source of truth that every workflow reads from. The system gets smarter with every interaction.

**Matches your voice.** Feed it writing samples and it learns how you communicate. Every DM, email, comment, and post sounds like you. Not like AI. It knows your vocabulary, your sentence rhythm, your pet peeves about words like "leverage" and "synergy."

**Tracks relationships.** Every person has a state: what they care about, what they pushed back on, when you last talked, what you owe them. The system surfaces the 3 warmest relationships that haven't been touched in 5+ days and drafts the follow-up for you.

## ADHD mode

If you have ADHD/ASD, this system was built for you. Literally. I have AUDHD (combined ADHD + Autism) and every design decision comes from that.

- Items ordered by friction, lowest first. 2-minute wins build dopamine before hard tasks.
- Energy tags on everything: Quick Win, Deep Focus, People, Admin. Batch similar-energy tasks.
- No shame language. Never "overdue." Always "carried forward." Never "you forgot." Always "not yet done."
- Effort tracking, not outcome tracking. "You sent 4 messages today" instead of "nobody responded."
- The system decides who to contact, what to say, in what order, through which channel. You copy-paste and check boxes. Decision fatigue eliminated.
- Based on research: Barkley's executive function model, Dodson's RSD framework, 30+ peer-reviewed sources.

This isn't an optional add-on. It's the default design philosophy.

## The architecture

```
q-instance/
├── .q-system/
│   ├── commands.md          # Every workflow defined (35+ steps in morning routine)
│   ├── preflight.md         # Tool manifest, known issues, execution gates
│   ├── loop-tracker.sh      # Opens, closes, escalates loops. Forces decisions at 14 days.
│   ├── log-step.sh          # Flight recorder. Every step logged to disk.
│   ├── session-start.py     # Auto-loads handoff + open loops on first tool use of the day
│   ├── token-guard.py       # Circuit breaker for runaway AI token consumption
│   └── audit-morning.py     # Post-execution audit. Catches skipped steps and missing content.
│
├── canonical/               # Source of truth. Updated by debriefs, calibration, research.
│   ├── talk-tracks.md       # What to say, to whom, tested and tagged by audience
│   ├── objections.md        # Every pushback heard, with the response that worked
│   ├── discovery.md         # Questions asked and answered, gaps identified
│   ├── decisions.md         # Every positioning decision with origin tag
│   ├── market-intelligence.md  # Buyer language, competitive intel, category signals
│   └── content-intelligence.md # What content performs, what doesn't, why
│
├── my-project/              # Your specific context
│   ├── current-state.md     # What works today (not vision, not roadmap)
│   ├── relationships.md     # Every person, what they care about, next step
│   ├── competitive-landscape.md  # Substitutes, adjacents, positioning against each
│   └── progress.md          # Log of decisions, debriefs, canonical changes
│
├── methodology/
│   ├── debrief-template.md  # 12-lens conversation extraction with signal quality check
│   └── modes.md             # 4 operating modes: CALIBRATE, CREATE, DEBRIEF, PLAN
│
├── marketing/
│   ├── templates/           # LinkedIn, X, Medium, email, outreach templates
│   ├── assets/              # Boilerplate, bio, stats, proof points, competitive one-liners
│   └── content-guardrails.md # Rules every piece of content must pass
│
├── memory/
│   ├── working/             # Expires in 48 hours
│   ├── weekly/              # 7-day rolling patterns
│   ├── monthly/             # Persistent insights
│   ├── graph.jsonl          # Entity-relationship knowledge graph
│   └── last-handoff.md      # Session continuity
│
├── hooks/
│   └── session-start.py     # Loads context on first tool use each day
│
└── output/
    ├── open-loops.json      # Every tracked loop with escalation state
    ├── daily-schedule-*.html # The daily action plan
    └── morning-log-*.json   # Flight recorder for the morning routine
```

## How loops work

```bash
# Open a loop when you send something
bash .q-system/loop-tracker.sh open dm_sent "Jane Smith" "Sent governance framework question"

# System auto-escalates daily
bash .q-system/loop-tracker.sh escalate
# Output: 12 open (L0:5 L1:4 L2:2 L3:1)

# Level 3 = 14+ days. System forces a decision:
# ACT (send follow-up), PARK (re-engage on trigger), or KILL (close permanently)
bash .q-system/loop-tracker.sh force-close L-2026-03-01-003 park

# Loops auto-close when evidence is found
# (Gmail reply detected, LinkedIn DM reply, connection accepted)
bash .q-system/loop-tracker.sh close L-2026-03-16-001 "DM reply detected" "auto_gmail"
```

9 loop types: `dm_sent`, `email_sent`, `materials_sent`, `comment_posted`, `action_created`, `debrief_next_step`, `dp_offer_sent`, `connection_request_sent`, `lead_sourced`. Each has a defined opener step, closer step, and the state file that connects them.

## Commands

**Daily:**
- `/q-morning` - generates your entire day as an HTML file
- `/q-wrap` - 10-minute end-of-day health check
- `/q-handoff` - save context for next session

**After conversations:**
- `/q-debrief` - extract insights from any conversation (or just paste a transcript)
- `/q-draft` - quick email, DM, or talking points

**Outreach:**
- `/q-engage` - engagement hitlist with copy-paste comments for prospects' posts
- `/q-create` - generate talk tracks, emails, slides for a specific audience
- `/q-plan` - review pipeline, relationships, prioritize next actions

**Content:**
- `/q-market-create` - LinkedIn, X, Medium content in your voice
- `/q-market-plan` - weekly planning against theme rotation

**System:**
- `/q-calibrate` - update canonical files with new information
- `/q-reality-check` - stress-test your positioning against evidence
- `/q-status` - quick snapshot of where things stand

## Setup

```bash
# 1. Install Claude Code
npm install -g @anthropic-ai/claude-code

# 2. Clone
git clone https://github.com/assafkip/q-founder-os.git
cd q-founder-os

# 3. Start
claude
```

The system walks you through setup: who you are, who you sell to, your positioning, your voice, your tools. One category at a time.

## Integrations

Works without any integrations (local markdown files). Each tool you connect adds capability:

- **Notion** - CRM, pipeline, engagement tracking
- **Google Calendar** - meeting detection, prep generation
- **Gmail** - email monitoring, reply detection for loop auto-close
- **Apify** - LinkedIn/X/Reddit scraping for lead sourcing
- **Chrome** - LinkedIn DMs, interactive browsing, analytics
- **Slack** - notifications, approval workflows

## Security

- Deny rules block `.env`, credentials, `.pem`, `.key` files
- PreToolUse hooks intercept dangerous operations at runtime
- No hardcoded secrets in committed files
- Destructive commands (`rm -rf`, `sudo`, `git push --force`) blocked by default

## Beyond founders

The pattern (unstructured input -> canonical state -> loop tracking -> executable output -> compounding) applies to any domain where humans manage concurrent relationships and compound knowledge:

- Lawyers managing cases
- Account managers running portfolios
- Doctors managing patient loads
- Therapists tracking caseloads
- Real estate agents juggling deals
- Teachers managing classrooms

The founder context is where I built it. The architecture is domain-agnostic. Fork it and adapt the canonical files, debrief template, and commands to your domain.

## Built by

[Assaf Kipnis](https://www.linkedin.com/in/assafkipnis/) - 12 years in threat intelligence at LinkedIn, Google, Meta, and ElevenLabs. Built this to manage the cognitive overhead of running a pre-seed startup solo with ADHD. Building [KTLYST](https://ktlystlabs.com) - the nervous system for enterprise security.

The system that runs KTLYST's operations (morning routine, CRM, outreach, content, investor pipeline) is a production instance of this skeleton. Everything in this repo is the general-purpose framework without domain-specific content.
