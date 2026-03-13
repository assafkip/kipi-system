# Q Founder OS

An AI-powered operating system for startup founders. It runs inside Claude Code and manages your entire day: relationships, pipeline, content, outreach, meeting prep, and follow-ups.

You talk to it. It remembers everything. It writes in your voice. It tells you exactly what to do next and gives you the copy-paste text to do it.

## Who this is for

Solo founders and tiny teams who are doing sales, marketing, content, investor outreach, and product at the same time. Especially founders who:

- Lose track of follow-ups and conversations
- Spend too much time context-switching between tools
- Want their outreach to sound like them, not like AI
- Have ADHD/ASD and need external structure (optional AUDHD mode built in)

## Setup

### 1. Install Claude Code

```bash
npm install -g @anthropic-ai/claude-code
```

You need an Anthropic API key. Get one at https://console.anthropic.com

### 2. Download this repo

```bash
git clone https://github.com/assafkip/q-founder-os.git
cd q-founder-os
```

### 3. Start Claude Code

```bash
claude
```

That's it. The system detects it's a fresh install and walks you through setup.

## What the setup wizard asks

### Step 1: Who are you?
- Your name
- Your role (founder, CEO, etc.)
- Your company name
- What you're building (one sentence)
- What stage you're at (pre-seed, seed, etc.)
- Co-founder name and role (if any)

### Step 2: Who do you sell to?
- Target buyer title and department
- Industry
- The pain you solve (in their words)
- What they use today instead of you
- Price point or deal size

### Step 3: Your positioning
- Your one-liner
- Metaphors or analogies that have worked
- What you are NOT (common misclassifications)
- Top 3 objections you hear

### Step 4: Your voice
- How you'd describe your writing style
- Words and phrases you naturally use
- Words and phrases you hate
- Any communication patterns (ESL, neurodivergent, etc.)
- 2-3 real examples of your writing (paste them in)

### Step 5: Your tools
- Do you use Notion? (CRM setup)
- Do you use Google Calendar? Gmail?
- Do you want LinkedIn/X management? (Apify setup)
- Each tool gets a guided config snippet for your settings file

### Step 6: Your CRM
- If Notion: creates 7 databases (Contacts, Interactions, Pipeline, Actions, LinkedIn Tracker, Content Pipeline, Editorial Calendar)
- If no Notion: works with local markdown files

### Step 7: Your network
- Your top 10 contacts (name, role, company, status)
- Investors you're talking to
- Design partners or early customers
- Advisors or connectors

### Step 8: Confirmation
- Shows a summary of everything
- Verifies it all loaded correctly
- Suggests running `/q-morning` the next day

## After setup

Run `/q-morning` to get your first daily schedule. It pulls your calendar, email, CRM, generates social posts, builds engagement hitlists, and produces an HTML file that is your entire workday laid out action by action with copy-paste text and checkboxes.

## Commands

| Command | What it does |
|---------|-------------|
| `/q-morning` | Full morning briefing + daily HTML schedule |
| `/q-debrief` | Process a conversation (or just paste a transcript) |
| `/q-engage` | Social engagement hitlist |
| `/q-create` | Generate talk tracks, emails, slides |
| `/q-draft` | Quick one-off email or DM |
| `/q-plan` | Review pipeline, prioritize actions |
| `/q-market-create` | Generate LinkedIn/X/Medium content |
| `/q-status` | Quick snapshot of where things stand |
| `/q-wrap` | End-of-day health check (10 min) |
| `/q-handoff` | Save context for next session |
| `/q-reality-check` | Stress-test your positioning and claims |
