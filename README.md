# The Kipi System

**Your AI brain. Externalized.**

It remembers everything you do. Then it becomes whatever you need.

Today it might run as your chief of staff. Tomorrow your lawyer. Next week your investigator. Same system, different role, because it remembers every decision, every conversation, every project you've ever brought it.

Most AI tools handle one job. This one handles every job you used to do yourself.

It runs in Claude Code. Plain markdown all the way down. No vector database, no embeddings, no black box. You read it with `cat`, search it with `rg`, version it with `git`.

---

## What it actually does

Three things, repeatedly.

**Remembers.** Every conversation, decision, debrief, and artifact lives in plain markdown files. A new session reads them. The system arrives with full context of what you've been doing.

**Reasons across.** Connections between projects, people, decisions, and patterns get logged in a knowledge graph (JSONL). When you ask a question, the system pulls from the right files automatically. Insights from one project apply to another without you wiring it.

**Becomes any role.** The same skeleton can run as a chief of staff, a lawyer, a PM, an investigator, a content operator, a researcher. You configure what role each instance plays through a `canonical/` directory. The system adapts its behavior, voice, and outputs to the role.

---

## Six real deployments

Six instances running across one person's work right now. All six share the same skeleton. They differ only in their canonical content.

- **Chief of staff.** Tracks conversations, talk tracks, decisions, positioning. Drafts updates, debriefs, follow-ups.
- **PM for a client engagement.** Coordinates multiple projects, logs every decision, drafts deliverables, tracks stakeholder context.
- **Lawyer.** Generates separation packages, contract redlines, compliance memos. Citations to relevant code on every position.
- **Investigator.** Manages active OSINT cases, evidence artifacts, published intel reports. Cross-platform source orchestration.
- **Operator for a consulting business.** Pipeline tracking, content cadence, deliverable production.
- **Architect for itself.** Manages its own PRDs, issues, reviews. The system builds the system.

---

## How memory compounds

Three layers, time-aware.

| Layer | What it holds | Lifecycle |
|---|---|---|
| **Working** | Active session notes, scratch work | Auto-cleaned after 48h |
| **Canonical** | Decisions, positioning, frameworks that persist | Updated on every conversation, never auto-deleted |
| **Graph** | Who/what/when triples linking entities across projects | Append-only |

Insights flow upward. A pattern noticed in scratch notes gets promoted to weekly. A repeated weekly pattern becomes canonical. The system gets sharper the longer you run it.

---

## Cross-instance memory

Each deployment is its own instance with its own directory, canonical files, and graph. But instances can share state through a bridge directory.

A real example: an investigation instance pulled positioning context from a separate strategy instance mid-task, and produced a synthesized advisory across two projects that had never been connected manually.

That's not storage. That's compounding across role-specific deployments.

---

## Install

```bash
npm install -g @anthropic-ai/claude-code
git clone https://github.com/assafkip/kipi-system.git
cd kipi-system && claude
```

Setup walks you through who you are, what you work on, how you write, and who you know. Takes about 20 minutes. After that the system runs.

---

## Commands

Optional. Most usage is just talking to the system in Claude Code.

| Command | What it does |
|---|---|
| `/q-debrief` | Extract insights from a conversation or paste a transcript |
| `/q-draft` | Quick email, DM, or content draft in your voice |
| `/q-engage` | Generate engagement on someone else's post |
| `/q-research` | Citation-only research mode |
| `/q-morning` | Build a daily action plan (full routine, optional) |
| `/q-wrap` | End-of-day health check |
| `/q-handoff` | Save context for next session |

---

## Architecture

```
kipi-system/
├── canonical/              # Source of truth, updated by every conversation
│   ├── decisions.md
│   ├── positioning.md
│   ├── insights.md
│   └── ...
├── memory/
│   ├── working/            # 48h scratch
│   ├── weekly/             # 7-day rollups
│   ├── monthly/            # Persistent
│   └── graph.jsonl         # Entity-relationship triples
├── output/                 # Generated artifacts (drafts, reports, schedules)
├── plugins/                # MCP tools, hooks, skills
└── .claude/                # Agents, rules, settings
```

Each instance you spin up has its own copy of this structure.

---

## Connects to

Works standalone with local files. Each integration adds capability.

| Tool | Adds |
|---|---|
| Notion | CRM, project tracking |
| Google Calendar | Meeting detection, auto-prep |
| Gmail | Email monitoring |
| Linear | Issue tracking, PRD workflow |
| Slack | Notifications |
| Chrome (DevTools MCP) | Web automation, LinkedIn |
| Apify | X/Twitter scraping |
| Reddit | Search and post tracking |

---

## ADHD-aware, not ADHD-only

I have AUDHD. Some design choices reflect that. Friction-ordered actions. No shame language. Effort tracking. Decision elimination. If you have executive function challenges, the system removes a lot of cognitive load by default.

If you don't, you still get an AI that doesn't make you decide who to contact, what order to do things in, or how to phrase the message.

---

## How the AI stays focused

The AI running this system has the same context-loss problems a human brain does. Research calls it "Lost in the Middle." In long conversations, LLMs forget instructions from earlier context, skip middle steps, and self-report completion without verifying.

The system has guardrails for that.

**Verification gates.** Scripts check output before claiming done.

**Re-injected step requirements.** Each step's instructions get fresh context.

**No self-authorized skipping.** The AI cannot decide on its own to skip steps.

**Structured logs.** What was actually produced, not just "completed."

Research basis: "Lost in the Middle" (Stanford), "LLMs Get Lost in Multi-Turn Conversation" (Laban et al. 2025).

---

## Security

- `.env`, credentials, and key files blocked from read/write
- PreToolUse hooks intercept dangerous operations
- No secrets in committed files
- `rm -rf`, `sudo`, `git push --force` denied by default

---

## Origin

I'm [Assaf Kipnis](https://www.linkedin.com/in/assafkipnis/). 12 years in threat intelligence at LinkedIn, Google, Meta, and ElevenLabs. I burned out fighting the same problems over and over. Left corporate. Started [KTLYST](https://ktlystlabs.com), a security product that turns threat reports into governed, deployable artifacts.

Running a company solo with ADHD meant my brain couldn't hold everything it needed to hold. So I built a second one. It manages my work, writes in my voice, remembers what I forget, and compounds what I learn.

Right now it runs as six different roles across my work. This repo is the general-purpose version. Fork it and teach it yours.
