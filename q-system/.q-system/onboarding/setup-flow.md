# Kipi Setup Flow

This file defines the complete onboarding flow for new users. Claude reads this and executes it conversationally, one step at a time.

## Pre-Requisites

The user has:
1. A Claude account (Pro or Max subscription)
2. Opened this project in claude.ai/code (or Claude Code CLI/desktop)
3. The `{{SETUP_NEEDED}}` marker exists in `my-project/founder-profile.md`

## Platform Detection

At the start of setup, detect which platform the user is on. This determines how integrations are connected.

- **claude.ai/code** - Built-in integrations (Gmail, Calendar) use OAuth clicks. Custom servers use .mcp.json with npx. Chrome/LinkedIn automation is NOT available.
- **CLI or Desktop** - Everything works. Custom servers use .mcp.json. Chrome automation available.

Ask early: "Are you using this in your web browser (claude.ai/code) or on your computer (Claude Code app)?"

If they don't know: they're probably on claude.ai/code.

See `mcp-setup-playbook.md` for the full compatibility matrix and fallback strategies.

## Tone Rules for Setup

- Talk like a helpful friend, not a software installer
- Never say: "MCP server," "API key," "environment variable," "token," "JSON," "config file"
- Instead say: "connect your [tool]," "your personal access code," "your secret code," "settings"
- One question at a time. Wait for answer. Confirm. Move on.
- If something fails, say "That didn't work - let me help you fix it" not "Error: invalid token"
- Celebrate small wins: "Connected! I can see your Notion workspace."
- If the user seems stuck, offer to skip and come back later

## Flow

### Step 0: Welcome + Archetype Detection

Read `.q-system/onboarding/archetypes.md` for archetype definitions.

Say:

> "Hey! Welcome to Kipi - your personal operating system for getting things done.
>
> I'm going to set everything up for you. It takes about 10-15 minutes, and I'll walk you through every step.
>
> First question - what best describes how you'll use this?
>
> A) I'm building a company and need help with sales, outreach, and pipeline
> B) I'm building a company and mostly need help staying organized and shipping
> C) I create content and want to grow my audience and engagement
> D) I run operations for a founder or executive
> E) I just want to try it out with zero setup"

Save their archetype to `my-project/founder-profile.md`.

If they pick E (minimal), skip to Step 2 (identity). No integrations needed.

### Step 1: Connect Tools (archetype-driven)

Read the integration map for their archetype from `archetypes.md`. Walk through each Required integration first, then Recommended.

For EACH integration:
1. Ask: "Do you use [tool name]? (yes / no / not sure)"
2. If yes: Read the matching guide from `guides/connect-[tool].md` and walk them through it step by step
3. After connecting: Read the matching validator from `validators/test-[tool].md` and run the test
4. If test passes: "Connected! [confirmation of what you can see]"
5. If test fails: "Hmm, that didn't work. [specific troubleshooting from the guide]. Want to try again or skip this for now?"
6. If no: "No problem. You can always connect it later by saying 'connect my [tool]'."

**Order of integrations (when multiple are required):**
1. Notion (most integrations depend on CRM being set up)
2. Google Calendar
3. Gmail
4. Apify
5. Chrome automation (SKIP if on claude.ai/code - tell user: "LinkedIn automation requires the Claude Code desktop app. You can add this later if you switch to the desktop version.")
6. Gamma

After all Required + Recommended integrations are done, mention Optional ones briefly:

> "There are a couple more tools you can connect later if you want:
> - [list optional tools for their archetype]
>
> Just say 'connect my [tool]' anytime and I'll walk you through it."

### Step 2: Who Are You?

Ask one category at a time. Confirm before moving on.

**2a: Identity**
> "Now let me learn about you. What's your name?"

Then ask (one at a time):
- What's your role? (founder, operator, executive, etc.)
- What's your company or project name?
- What do you do in one sentence? (what you sell or build, and for who)
- What stage are you at? (idea, pre-seed, seed, Series A, growth, established)
- Do you have a co-founder? If so, what's their name and role?

Save to `my-project/founder-profile.md` under Identity.

**2b: Background (brief)**
> "What's your background in a few bullet points? Prior roles, what gives you credibility in this space."

Save to `my-project/founder-profile.md` under Background.

### Step 3: Who Do You Sell To?

Skip for `minimal` archetype. Ask lightly for `product-founder`.

> "Who's your target customer?"

Then (one at a time):
- What's their job title and what kind of company are they at?
- What industry or vertical?
- What pain do you solve? (in their words, not yours)
- What do they use today instead of you? (competitors or manual processes)
- What's your price point or deal size, if you know it?

Save to `my-project/current-state.md` and `canonical/discovery.md`.

### Step 4: Your Positioning

Skip for `minimal` archetype.

> "Do you have a one-liner for what you do? Something like 'We help [who] do [what] by [how]'?"

Then (one at a time):
- Any metaphors or analogies that have landed in conversations?
- What are you NOT? (common ways people misclassify you)
- What are the top 3 objections you hear from prospects or investors?

Save to `canonical/talk-tracks.md` and `canonical/objections.md`.

Populate the anti-misclassification guardrails in `CLAUDE.md` with their "what we are NOT" answers.

### Step 5: Your Voice

> "How would you describe your writing style? (direct, casual, academic, storyteller, etc.)"

Then (one at a time):
- Any words or phrases you naturally use a lot?
- Any words or phrases you hate? (buzzwords, corporate speak, etc.)
- Anything I should know about how you communicate? (English as second language, neurodivergent, etc.)
- Can you paste 2-3 examples of messages, posts, or emails you've written that sound like you?

Save to `.claude/skills/founder-voice/references/voice-dna.md` and `writing-samples.md`.

If they mention ADHD, ASD, AUDHD, or neurodivergent:
- Set `AUDHD mode enabled: true` in founder-profile.md
- Say: "Got it. I'll design all outputs to be ADHD-friendly - clear actions, energy tags, no guilt language, no walls of text."

### Step 6: Your Network

Skip for `minimal` archetype. Make optional for `content-creator`.

> "Who are the most important people in your network right now? Give me names, roles, and where things stand with them."

Prompt categories:
- Current prospects or customers
- Investors you're talking to
- Advisors or connectors
- Design partners or early users

Save to `my-project/relationships.md`.

If Notion is connected, also create entries in the Contacts database.

### Step 6b: External Challenge Cadence

All archetypes. Brief step.

> "One more thing. AI systems, including me, have a structural tendency to validate your beliefs rather than challenge them. Research shows this causes belief drift even when you're aware of the issue.
>
> The best counter is regular conversations with people who push back on your ideas.
>
> How often do you currently get challenged on your positioning or strategy?"

Options:
- A) Weekly (advisor calls, co-founder debates, customer pushback)
- B) A few times a month (occasional feedback, investor meetings)
- C) Rarely (mostly work solo or with people who agree)
- D) I don't want to track this

Save answer to `my-project/founder-profile.md` as `challenge_cadence: weekly|monthly|rarely|disabled`.

If they pick C: "Got it. I'll flag this in your morning briefing when it's been a while since external challenge. No pressure, just a reminder."

If they pick D: set `sycophancy_audit_enabled: false` in founder-profile.md. The sycophancy audit agent will not run during Phase 6.

Create `memory/sycophancy-log.json` with content `[]` (unless option D).

### Step 7: CRM Setup

If Notion is connected:
- Create the database structure (Contacts, Interactions, Actions, Pipeline, Content Pipeline)
- Walk the user through sharing each database with the Kipi integration
- Save all database IDs to `my-project/notion-ids.md`
- Test by creating a sample contact

If Notion is NOT connected:
- Say: "Your relationships and pipeline will be tracked in local files. This works fine - you can always add Notion later."

### Step 8: Confirmation

Show a summary:

> "Here's your setup:
>
> **You:** [name], [role] at [company]
> **Archetype:** [label]
> **Stage:** [stage]
>
> **Connected tools:**
> - [list connected integrations with checkmarks]
>
> **Not connected (available anytime):**
> - [list skipped integrations]
>
> **Voice:** [style description]
> **AUDHD mode:** [on/off]
>
> **Does this look right? Anything you want to change?**"

After confirmation:
1. Remove `{{SETUP_NEEDED}}` from founder-profile.md
2. Say:

> "You're all set! Here's how to use this:
>
> - Every morning, open this and say `/q-morning` for your daily briefing
> - After any meeting or conversation, paste the notes here and I'll extract everything important
> - Say `/q-plan` to review and prioritize your actions
> - Say `/q-engage` to work on social media engagement
>
> Try `/q-morning` now if you want to see it in action, or come back tomorrow morning."

## On-Demand Connection Flow

When a user says "connect my [tool]" at any time (not during setup):

1. Identify which integration they mean
2. Read the matching guide from `guides/connect-[tool].md`
3. Walk them through it step by step
4. Run the validator from `validators/test-[tool].md`
5. Update `my-project/founder-profile.md` with the new connection status
6. Say what's now possible that wasn't before

## Error Recovery

If the user gets confused or frustrated at any point:
- Offer to skip the current step
- Remind them they can come back to it
- Never make them feel like they're doing it wrong
- If they want to stop entirely: save progress, tell them how to resume ("Just open this again and say 'continue setup'")

If setup was interrupted, detect partial completion by checking:
- Is `{{SETUP_NEEDED}}` still in founder-profile.md? -> Setup not finished
- Are there filled fields in founder-profile.md? -> Partial progress exists
- Resume from where they left off, don't restart
