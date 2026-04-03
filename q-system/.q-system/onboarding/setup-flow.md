# Kipi Setup Flow

This file defines the complete onboarding flow for new users. Claude reads this and executes it conversationally, one step at a time.

## Pre-Requisites

The user has:
1. A Claude account (Pro or Max subscription)
2. Opened this project in claude.ai/code (or Claude Code CLI/desktop)
3. The `{{SETUP_NEEDED}}` marker exists in `my-project/founder-profile.md`

## Platform Detection

Detect which platform the user is on. This determines how integrations are connected. **Ask this as the FIRST question in Step 0, before archetype.**

- **claude.ai/code** - Built-in integrations (Gmail, Calendar) use OAuth clicks. Custom servers use .mcp.json with npx. Chrome/LinkedIn automation is NOT available.
- **CLI or Desktop** - Everything works. Custom servers use .mcp.json. Chrome automation available.

If they don't know: they're probably on claude.ai/code.

See `mcp-setup-playbook.md` for the full compatibility matrix and fallback strategies.

## Context Firewall (ENFORCED)

**The ONLY source of truth for setup state is `my-project/founder-profile.md`.** Do NOT use any other context to determine what is "already configured":
- Ignore `~/.claude/CLAUDE.md` (global user instructions)
- Ignore conversation history from other projects
- Ignore anything you "know" about the user from system prompts or prior sessions

If `founder-profile.md` has `{{SETUP_NEEDED}}` and its fields are blank/templated, this is a **fresh install**. Start from Step 0. Ask every question. Do not pre-fill answers from external context.

Even if you know the user's name, role, or preferences from other sources, ASK them during setup. The user may want different settings for this instance.

## Ask-First Rule (ENFORCED)

**Never assume. Never pre-fill. Never skip a question.**
- Every field must be explicitly asked and answered by the user before it is saved
- Before each selection: explain what the option means and how it affects behavior
- After each answer: confirm what you understood before saving
- Do NOT show a "here's what's configured" summary until the user has answered every question
- If a step has multiple options (archetype, stage, AUDHD, etc.), explain each one briefly so the user makes an informed choice

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
> Quick thing first - are you using this in your web browser (claude.ai/code) or on your computer (Claude Code app or CLI)?"

Wait for answer. Save platform to `my-project/founder-profile.md`. Then ask:

> "Now - what best describes how you'll use this? Each option changes which tools I connect and what kind of outputs I generate for you.
>
> A) **GTM Founder** - You're building a company and need help with sales, outreach, pipeline tracking, and investor relationships. I'll set up CRM, email tracking, LinkedIn engagement, and lead scoring.
>
> B) **Product Founder** - You're building a company but mostly need help staying organized, shipping product, and keeping track of decisions. Lighter on sales tools, heavier on planning and execution.
>
> C) **Content Creator** - You create content (writing, posts, newsletters) and want to grow your audience, track engagement, and stay consistent. I'll focus on content pipeline, scheduling, and social engagement.
>
> D) **Operator** - You run operations for a founder or executive. I'll help you track their relationships, manage their pipeline, and prepare their outputs.
>
> E) **Minimal** - You just want to try it out with zero setup. No integrations, no CRM. You can add things later."

Confirm their choice: "So you're a [label] - [one-line description]. That means I'll [what changes]. Sound right?"

Save their archetype and today's date to `my-project/founder-profile.md`.

If they pick E (minimal), skip to Step 2 (identity). No integrations needed.

### Step 1: Connect Tools (archetype-driven)

Read the integration map for their archetype from `archetypes.md`. Walk through each Required integration first, then Recommended.

For EACH integration, explain what it does in Kipi before asking:

| Tool | What it does in Kipi |
|------|---------------------|
| Notion | Your CRM - tracks contacts, interactions, pipeline, and content status |
| Google Calendar | Pulls your schedule into morning briefings so I can plan your day |
| Gmail | Reads recent emails to surface follow-ups and conversation context |
| Chrome/LinkedIn | Reads LinkedIn profiles, posts, and DMs for engagement and lead research |
| Apify | Scrapes X/Twitter posts and replies (the only way to get X data) |
| Gamma | Generates slide decks and one-pagers from your talk tracks |

For EACH integration:
1. Explain what it does (from the table above), then ask: "Do you use [tool name]? Want to connect it? (yes / no / not sure)"
2. If yes: Read the matching guide from `guides/connect-[tool].md` and walk them through it step by step
3. After connecting: Read the matching validator from `validators/test-[tool].md` and run the test
4. If test passes: "Connected! [confirmation of what you can see]"
5. If test fails: "Hmm, that didn't work. [specific troubleshooting from the guide]. Want to try again or skip this for now?"
6. If no: "No problem. You can always connect it later by saying 'connect my [tool]'."
7. If not sure: Briefly explain when they'd use it (from the table), then ask: "Want to try connecting it now, or skip and add it later?"

**Order of integrations (when multiple are required):**
1. Notion (most integrations depend on CRM being set up)
2. Google Calendar
3. Gmail
4. Chrome automation (SKIP if on claude.ai/code - tell user: "LinkedIn automation requires the Claude Code desktop app. You can add this later if you switch to the desktop version.")
5. Apify (optional - only needed for X/Twitter scraping)
6. Gamma

After all Required + Recommended integrations are done, mention Optional ones briefly:

> "There are a couple more tools you can connect later if you want:
> - [list optional tools for their archetype]
> - **Research Mode** -- already included in kipi-core. Say `/research <topic>` anytime you need Claude to back up claims with real sources instead of guessing.
>
> Just say 'connect my [tool]' anytime and I'll walk you through it."

### Step 2: Who Are You?

Ask one category at a time. Confirm before moving on.

**2a: Identity**
> "Now let me learn about you. What's your name?"

Then ask (one at a time, explain each before asking):
- What's your role? (founder, operator, executive, etc.)
- What's your company or project name?
- In plain language, what does your company/project do? (Keep it simple - we'll refine your positioning statement later in Step 4)
- What stage are you at? Explain each:
  - **Idea** - you're exploring, no product yet
  - **Pre-seed** - building something, no funding yet
  - **Seed** - early product, first funding round
  - **Series A** - product-market fit signals, scaling
  - **Growth** - established revenue, growing team
  - **Established** - mature business, optimizing
- Do you have a co-founder? If so, what's their name and role?

Save to `my-project/founder-profile.md` under Identity.

**2b: Background (brief)**

Ask one at a time:
- What's your relevant prior experience? (roles, companies - just the ones that matter for what you're doing now)
- What gives you credibility in this space? (domain expertise, years in the field, specific knowledge)
- What's your unique insight? (What do you know or believe that most people in your space don't? This is the seed of your content and positioning.)

Save to `my-project/founder-profile.md` under Background (map answers to: Prior experience, Domain expertise, Unique insight).

**2c: Preferences**

> "A few quick ones so I can plan your day better:"

Ask one at a time:
- What timezone are you in? (e.g. US/Eastern, Europe/London, Asia/Jerusalem)
- What are your typical working hours? (e.g. 9am-6pm, or "it varies")
- When are you sharpest? (This helps me schedule deep-focus tasks at the right time. e.g. "mornings", "late night", "after coffee")

Save to `my-project/founder-profile.md` under Preferences.

### Step 3: Who Is Your Audience?

Skip for `minimal` archetype.

Explain why this matters:
> "This helps me write outreach, content, and talk tracks in the language your audience actually uses - not marketing speak."

**For GTM founders and operators:**
> "Who's your target customer?"

Then (one at a time):
- What's their job title and what kind of company are they at?
- What industry or vertical?
- What pain do you solve? (in their words, not yours)
- What do they use today instead of you? (competitors or manual processes)
- What's your price point or deal size, if you know it?

**For product founders** (lighter version):
- Who uses your product? (job title, company type)
- What problem does it solve for them?
- Skip pricing/deal size unless they volunteer it

**For content creators:**
- Who's your audience? (who reads/watches/listens)
- What topics do they care about?
- What do they struggle with that your content helps?
- Who else creates content for this audience? (not competitors - fellow creators)

Save to `my-project/current-state.md` and `canonical/discovery.md`.

### Step 4: Your Positioning

Skip for `minimal` archetype.

Explain why this matters:
> "I use this to generate talk tracks, outreach, and content. The better your positioning, the less I hallucinate about what you do."

**For GTM founders, product founders, and operators:**

> "Do you have a one-liner for what you do? Something like 'We help [who] do [what] by [how]'? Don't worry if it's not perfect - we can refine it later."

Then (one at a time):
- Any metaphors or analogies that have landed in conversations? (These are gold - I'll reuse them in content and outreach)
- What are you NOT? (How do people misclassify you? e.g. "people think we're a CRM but we're actually..." - I'll use this to prevent myself from making the same mistake)
- What are the top 2-3 objections or pushbacks you hear? (From prospects, investors, or anyone - I'll draft responses for you)

**For content creators:**

> "How do you describe what you do to someone who's never seen your content? One sentence."

Then (one at a time):
- What makes your perspective different from other creators in your space? (Your angle, background, or take that others don't have)
- What do people get wrong about your work? (e.g. "people think I'm a tech blogger but I actually write about the human side of engineering")
- What's the most common feedback or pushback you get from your audience?

Save to `canonical/talk-tracks.md` and `canonical/objections.md`.

Populate anti-misclassification guardrails with their "what we are NOT" answers:
- Update `q-system/CLAUDE.md` Language Rules section: replace `{{YOUR_METAPHOR}}`, `{{YOUR_CATEGORY}}`, `{{KEY_PHRASE_1-3}}` placeholders with their actual metaphors/phrases
- Add their "what we are NOT" items to the "Avoid" list in Language Rules
- Update `.claude/rules/anti-misclassification.md` if it exists with the same guardrails

### Step 5: Your Voice

> "How would you describe your writing style? (direct, casual, academic, storyteller, etc.)"

Then (one at a time):
- Any words or phrases you naturally use a lot?
- Any words or phrases you hate? (buzzwords, corporate speak, etc.)
- What's your primary language? If you write in multiple languages, which ones? (This affects how I draft content for you)
- Can you paste 2-3 examples of messages, posts, or emails you've written that sound like you? (I'll analyze these to learn your patterns - sentence length, word choices, how you open and close. This is the single most important input for making my writing sound like yours, not like AI.)

**Then explicitly ask about neurodivergent accommodations:**

> "One more thing about how I communicate with you. I have an AUDHD mode that changes how I structure everything I give you. When it's on:
>
> - Every output is copy-paste ready or checkable - no walls of text
> - Tasks are tagged with energy level (Quick Win / Deep Focus / People / Admin) and time estimates
> - I batch similar-energy tasks together
> - No pressure, shame, urgency, or guilt language ever
> - I track effort not outcomes, present choices not commands
>
> Do you want AUDHD mode on? (yes / no / tell me more)"

Save voice data to:
- `plugins/kipi-core/skills/founder-voice/references/voice-dna.md` (style, phrases, banned words)
- `plugins/kipi-core/skills/founder-voice/references/writing-samples.md` (pasted examples)
- `my-project/founder-profile.md` under Communication Style (writing style, primary language)

If they say yes to AUDHD mode, ask one follow-up:
> "Got it. For my records - is this ADHD, ASD, AUDHD (both), or something else? This helps me fine-tune the accommodations."

- Set `Neurodivergent accommodations: [their answer]` in founder-profile.md
- Set `AUDHD mode enabled: true` in founder-profile.md
- Say: "On. Everything I give you will follow those rules."

If they say no:
- Set `Neurodivergent accommodations: none` in founder-profile.md
- Set `AUDHD mode enabled: false` in founder-profile.md

### Step 5b: Your Platforms

Skip for `minimal` archetype. Ask for all others.

> "Where are you active online? I'll use these to track your content performance, find engagement opportunities, and source leads."

Ask one at a time. For each, explain what Kipi does with it:
- **LinkedIn** - What's your profile URL? (I use this to track your posts' performance, find people to engage with, and draft connection requests)
- **X/Twitter** - What's your handle? e.g. @yourhandle (I scrape your posts and replies to measure reach, and monitor relevant conversations)
- **Medium** - Do you write on Medium? What's your handle? e.g. @yourname (I pull your articles via RSS to track performance and repurpose content)
- **Reddit** - Do you post on Reddit? What's your username? (I monitor subreddits for lead signals and engagement opportunities)
- **Substack** - Do you have a newsletter? What's the name? e.g. yourname.substack.com (I pull via RSS to track and repurpose)
- **GitHub** - What's your username? (For monitoring repos and open source activity)

Save to `my-project/founder-profile.md` under Platform Handles.

Also populate `my-project/lead-sources.md`:
- X handles go into "X Accounts to Monitor" if they want to track competitors
- Reddit subreddits: ask "What subreddits do your target customers hang out in?" and populate the table
- Medium tags: ask "What topics should I search for on Medium?" and convert to kebab-case tags

### Step 6: Your Network

Skip for `minimal` archetype.

For `content-creator` archetype, ask before starting:
> "This next step is about tracking professional relationships - collaborators, sponsors, editors, etc. Some content creators find this useful, others don't. Want to do this step or skip it?"

If they skip, move to Step 6b.

Explain what this is for:
> "I track your relationships so I can remind you to follow up, prepare you before meetings, and notice when someone goes cold. Nothing leaves this system - it's all local files (or your private Notion if you connected it)."
>
> "Who are the most important people in your professional network right now? For each person, I need: name, their role/company, and where things stand."

Prompt categories vary by archetype:

**For GTM founders, product founders, and operators:**
- **Prospects or customers** - people who might buy or already use what you're building
- **Investors** - anyone you're talking to about funding
- **Advisors or connectors** - people who open doors or give you feedback
- **Design partners or early users** - people testing your product or giving detailed feedback

**For content creators (if they opted in):**
- **Collaborators** - people you co-create with, guest on each other's shows, cross-promote
- **Sponsors or partners** - brands or people who pay for or support your content
- **Editors or advisors** - people who review your work or give you strategic feedback
- **Fellow creators** - peers in your space you have a relationship with

Save to `my-project/relationships.md`.

If Notion is connected, also create entries in the Contacts database.

### Step 6b: External Challenge Cadence

All archetypes except `minimal` (skip for minimal - they can enable this later).

> "One more thing. AI systems, including me, have a structural tendency to validate your beliefs rather than challenge them. Research shows this causes belief drift even when you're aware of the issue.
>
> The best counter is regular conversations with people who push back on your ideas.
>
> How often do you currently get challenged on your positioning or strategy?"

Explain what this means, then offer options:

> "Here's why I ask: if you mostly get agreement from the people around you, I'll nudge you to seek external pushback more often. If you already get challenged regularly, I won't nag."

Options:
- A) **Weekly** - advisor calls, co-founder debates, customer pushback. I won't remind you.
- B) **A few times a month** - occasional feedback, investor meetings. I'll flag it if it's been a while.
- C) **Rarely** - mostly work solo or with people who agree. I'll include a gentle reminder in morning briefings.
- D) **Don't track this** - I won't monitor or mention it at all.

Save answer to `my-project/founder-profile.md` as `challenge_cadence: weekly|monthly|rarely|disabled`.

If they pick C: "Got it. I'll flag this in your morning briefing when it's been a while since external challenge. No pressure, just a reminder."

If they pick D: set `sycophancy_audit_enabled: false` in founder-profile.md. The sycophancy audit agent will not run during Phase 6.

Create `memory/sycophancy-log.json` with content `[]` (unless option D).

### Step 7: CRM Setup

If Notion is connected, explain what you'll create before creating it. Database list varies by archetype:

**For GTM founders and operators:**
> - **Contacts** - everyone you're tracking (prospects, investors, partners, etc.)
> - **Interactions** - log of conversations, meetings, and touchpoints with each contact
> - **Actions** - follow-ups and tasks tied to specific people (what to do, by when)
> - **Pipeline** - deals and opportunities with stages (lead, qualified, proposal, closed)
> - **Content Pipeline** - your content ideas, drafts, and published pieces with status tracking

**For product founders:**
> - **Contacts** - everyone you're tracking (users, investors, partners)
> - **Interactions** - log of conversations and feedback sessions
> - **Actions** - follow-ups and tasks tied to specific people
> - **Content Pipeline** - your content ideas, drafts, and published pieces

(Skip Pipeline unless they request it - product founders often don't have a traditional sales pipeline)

**For content creators:**
> - **Contacts** - collaborators, sponsors, editors, fellow creators
> - **Content Pipeline** - your content ideas, drafts, and published pieces with status tracking
> - **Actions** - follow-ups and tasks (publish dates, sponsor deliverables, etc.)

(Skip Interactions and Pipeline - too heavy for most content workflows)

> "Want me to create all of these, or just some?"

Then:
- Create the databases the user approved
- Walk the user through sharing each database with the Kipi integration
- Save all database IDs to `my-project/notion-ids.md`
- Test by creating a sample contact, then ask: "I created a test contact to verify the connection. Want me to delete it or keep it?"

If Notion is NOT connected:
- Say: "Your relationships and pipeline will be tracked in local files. This works fine - you can always add Notion later."

### Step 8: Confirmation

Show a summary:

> "Here's your setup:
>
> **You:** [name], [role] at [company]
> **Co-founder:** [name and role, or "solo"]
> **Archetype:** [label] - [one-line description of what this means]
> **Stage:** [stage]
> **Platform:** [web / CLI / desktop]
> **Timezone:** [timezone] | **Hours:** [working hours] | **Peak energy:** [when sharpest]
> **Language(s):** [primary language(s)]
>
> **Background:** [2-3 bullet summary of experience, expertise, unique insight]
> **One-liner:** [their positioning one-liner, or "not set yet"]
> **Audience:** [brief summary of target audience from Step 3]
>
> **Connected tools:**
> - [list connected integrations with checkmarks]
>
> **Not connected (available anytime):**
> - [list skipped integrations]
>
> **Platforms:** [list connected social platforms]
> **Voice:** [style description]
> **AUDHD mode:** [on/off] - [if on: "all outputs will be copy-paste ready, energy-tagged, no pressure language"]
> **Challenge tracking:** [weekly/monthly/rarely/disabled]
> **Relationships tracked:** [count, or "none yet"]
>
> **Does this look right? Anything you want to change?**"

After confirmation:
1. Remove `{{SETUP_NEEDED}}` from founder-profile.md
2. Show archetype-appropriate next steps:

**For GTM founders:**
> "You're all set! Here's how to use this:
> - `/q-morning` - daily briefing with schedule, pipeline, and engagement actions
> - Paste any meeting notes or conversation and I'll extract everything important
> - `/q-plan` - review and prioritize your pipeline actions
> - `/q-engage` - social engagement mode (comments, DMs, connection requests)"

**For product founders:**
> "You're all set! Here's how to use this:
> - `/q-morning` - daily briefing with schedule and priorities
> - Paste any meeting notes and I'll extract decisions and action items
> - `/q-plan` - review and prioritize what to work on next
> - `/q-create` - generate specific outputs (emails, docs, specs)"

**For content creators:**
> "You're all set! Here's how to use this:
> - `/q-morning` - daily briefing with content pipeline status and engagement opportunities
> - `/q-engage` - social engagement mode (generate comments and replies)
> - `/q-market-create` - generate content aligned with your voice and themes
> - `/q-market-plan` - plan your content calendar for the week"

**For operators:**
> "You're all set! Here's how to use this:
> - `/q-morning` - daily briefing with the founder's schedule, pipeline, and pending actions
> - Paste meeting notes and I'll extract everything for the founder's files
> - `/q-plan` - review and prioritize actions across all relationships
> - `/q-create` - generate outputs on behalf of the founder"

**For minimal:**
> "You're all set! Try asking me anything - research a topic, draft an email, plan your week. Say `/q-morning` tomorrow for your first daily briefing."

End with:
> "Try one of these now if you want to see it in action, or come back tomorrow morning."

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

If setup was interrupted, detect partial completion by checking **only the file contents** (not global context or prior knowledge):
- Is `{{SETUP_NEEDED}}` still in founder-profile.md? -> Setup not finished
- Read `founder-profile.md` field by field. Only fields with non-template, non-blank values count as completed. Blank fields (`:` with nothing after, or template text like `(date)`) are NOT filled.
- Resume from the first unfilled step, don't restart completed ones
- Tell the user: "Looks like we got partway through setup last time. I'll pick up where we left off."
