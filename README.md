# The Kipi System

**Your AI brain. Externalized.**

You had 4 meetings this week. You owe follow-ups to 3 of them. One person replied to your DM from last Tuesday and you haven't noticed. A warm intro is going cold because you forgot to send the deck. Your to-do list has 30 items, 12 are stale, and you're not sure which ones still matter.

The Kipi System fixes this. One command in Claude Code produces your entire day: every action pre-written, every follow-up drafted, every open thread tracked. You copy, paste, check the box, move on.

```
One command. Your whole day. Every action ready to go.
```

---

## What happens when you run `/q-morning`

The system pulls from your calendar, email, CRM, and social platforms. It reads every open loop. It checks what went cold. Then it produces a single HTML file:

- **Copy-paste actions sorted by friction.** 2-minute replies first, deep work later. Momentum builds before the hard stuff.
- **Every follow-up pre-written in your voice.** Not AI voice. YOUR voice. Fed from your writing samples, your word choices, your pet peeves.
- **Open loops with escalation.** Sent a DM 7 days ago with no reply? The system drafted the follow-up already. 14 days? It forces you to decide: send, park, or kill.
- **Meeting prep with context.** Who you're meeting, what you discussed last time, what they care about, suggested talking points.

You open the HTML. Start at the top. Work down. Done.

---

## Paste a conversation. Get your next 10 actions.

Had a call? Paste the transcript. The system extracts:
- What resonated (their exact words)
- What got pushback
- What you owe them
- New objections to prepare for

Then it routes each insight to the right file automatically. Your talk tracks update. Your relationship file updates. Your follow-up email is drafted and waiting in tomorrow's HTML.

After 50 conversations, the system knows your market better than you do. Because it remembers everything. You don't have to.

---

## Nothing gets forgotten

Every outbound action opens a loop. Every loop has a timer.

| Days open | What happens |
|-----------|-------------|
| 0-2 | Quiet. Listed in your dashboard. |
| 3-6 | Follow-up drafted. Shows in your action plan. |
| 7-13 | Flagged. Shows at the top. "This is going cold." |
| 14+ | Forced decision. Act now, park for later, or kill it. No more open loops draining mental energy. |

Loops auto-close when the system detects a response. Gmail reply? Closed. LinkedIn DM reply? Closed. Connection accepted? Closed. You don't track anything. The system tracks everything.

---

## Built for ADHD. Works for everyone.

I have AUDHD (ADHD + Autism). Every design decision comes from that.

**No decisions.** The system picks who to contact, what to say, in what order, through which channel. You copy-paste and check boxes.

**No shame.** Never "overdue." Always "carried forward." Never "you forgot." Always "not yet done." Language matters when your brain punishes you for every dropped ball.

**Friction-ordered.** Quick wins first. Dopamine before discipline. The hardest task is never at the top.

**Effort-tracked.** "You sent 4 messages today" matters more than "nobody responded yet." Progress is actions taken, not outcomes received.

This isn't a feature toggle. It's how the whole system thinks. If you don't have ADHD, you still get a system that eliminates decision fatigue and orders your day by what's easiest to start.

---

## The system gets smarter every day

Traditional tools are static. You put data in, you get data out. The Kipi System compounds.

**Canonical files** are the source of truth: your positioning, your objections and the responses that worked, your competitive landscape, every relationship and what each person cares about. Every workflow reads from them. Every conversation updates them.

**Time-stratified memory.** Working memory expires in 48 hours (you don't need yesterday's scratch notes). Weekly patterns roll up. Monthly insights persist. The system forgets what doesn't matter and holds onto what does.

**A knowledge graph** connects people, companies, what they said, and how they relate. "Who in my network works at a company that runs Okta?" is a question the system can answer.

---

## Three commands to start

```bash
npm install -g @anthropic-ai/claude-code
git clone https://github.com/assafkip/kipi-system.git
cd kipi-system && claude
```

The system walks you through setup. Who you are, what you're building, how you talk, who you know. Takes about 20 minutes. Then run `/q-morning` and see your first daily action plan.

---

## Architecture

```
kipi-system/
├── .q-system/
│   ├── commands.md          # 35+ step morning routine and all workflows
│   ├── loop-tracker.sh      # Opens, escalates, and closes loops
│   ├── session-start.py     # Auto-loads context on first use each day
│   ├── audit-morning.py     # Catches skipped steps and missing content
│   ├── token-guard.py       # Stops runaway AI token consumption
│   ├── log-step.sh          # Flight recorder for every step
│   └── preflight.md         # Tool manifest and known issues
│
├── canonical/               # Source of truth (updates from every conversation)
│   ├── talk-tracks.md       # What to say, tested and tagged by audience
│   ├── objections.md        # Every pushback, with the response that worked
│   ├── market-intelligence.md  # Buyer language and competitive signals
│   └── decisions.md         # Every decision with origin and rationale
│
├── my-project/              # Your specific context
│   ├── relationships.md     # Every person and what you owe them
│   ├── current-state.md     # What's true today (not vision)
│   └── progress.md          # Decision log and change history
│
├── memory/
│   ├── working/             # 48-hour scratch (auto-cleaned)
│   ├── weekly/              # 7-day patterns
│   ├── monthly/             # Persistent insights
│   └── graph.jsonl          # Who knows whom, who cares about what
│
├── marketing/               # Content templates, guardrails, voice matching
├── methodology/             # Debrief template, operating modes
│
└── output/
    ├── open-loops.json      # Every tracked loop with escalation state
    ├── daily-schedule-*.html # Your daily action plan
    └── morning-log-*.json   # Audit trail
```

---

## Commands

| What you want to do | Command |
|---------------------|---------|
| Generate your entire day | `/q-morning` |
| Process a conversation | `/q-debrief` (or just paste a transcript) |
| Draft a quick email or DM | `/q-draft` |
| Get engagement actions for prospects' posts | `/q-engage` |
| Plan your week's content | `/q-market-plan` |
| Update your positioning from new info | `/q-calibrate` |
| Stress-test your positioning | `/q-reality-check` |
| End-of-day health check | `/q-wrap` |
| Save context for next session | `/q-handoff` |

---

## Connects to

Works standalone with local files. Each integration adds capability:

| Tool | What it adds |
|------|-------------|
| Notion | CRM, pipeline, relationship tracking |
| Google Calendar | Meeting detection, auto-prep |
| Gmail | Email monitoring, loop auto-close on reply |
| Apify | LinkedIn/X/Reddit scraping for lead sourcing |
| Chrome | LinkedIn DMs, analytics, interactive browsing |
| Slack | Notifications, approval workflows |

---

## Not just for founders

The pattern works anywhere humans manage concurrent relationships and compound knowledge:

**Lawyers** - case files as canonical state, filing deadlines as loops, client conversations as debriefs.

**Sales teams** - accounts as relationships, proposals as loops, call notes as debriefs.

**Doctors** - patients as relationships, referrals and labs as loops, visit notes as debriefs.

**Consultants** - clients as relationships, deliverables as loops, stakeholder meetings as debriefs.

The founder context is where I built it. Fork it and replace the canonical files with your domain.

---

## Security

- `.env`, credentials, and key files blocked from read/write
- PreToolUse hooks intercept dangerous operations at runtime
- No secrets in committed files
- `rm -rf`, `sudo`, `git push --force` denied by default

---

## Origin

I'm [Assaf Kipnis](https://www.linkedin.com/in/assafkipnis/). 12 years in threat intelligence at LinkedIn, Google, Meta, and ElevenLabs. I burned out at Google fighting the same problems over and over. Left corporate. Started building [KTLYST](https://ktlystlabs.com), a security product that turns threat reports into governed, deployable artifacts for every team.

Running a pre-seed startup solo with ADHD meant everything was falling through the cracks. So I built this system for myself. It manages my investor pipeline, writes my outreach, preps my meetings, tracks every open loop, and produces a daily HTML file that IS my workday.

KTLYST's operations run on a production instance of this system. This repo is the general-purpose skeleton without domain-specific content. Fork it and make it yours.
