# /q-setup — First-time setup wizard for Q Founder OS

Run this on first use or to reconfigure integrations. Walks through setup one step at a time — conversational, not a wall of questions.

## Path resolution

All user data lives under `${CLAUDE_PLUGIN_DATA}` (provided by Claude Code plugin system). Read the `kipi://paths` MCP resource to get resolved directories. Key directories:
- **Config** (`{config_dir}`): founder-profile, enabled-integrations, canonical/, voice/, marketing/
- **Data** (`{data_dir}`): my-project/, memory/
- **State** (`{state_dir}`): output/, bus/
- **Repo**: system code (agents, templates, steps) stays in the git repo

In plugin mode, `{config_dir}`, `{data_dir}`, and `{state_dir}` all resolve to the same instance directory under `${CLAUDE_PLUGIN_DATA}/instances/{name}/`.

## Detection

**FIRST:** Read the `kipi://status` MCP resource.

**If `legacy_data_detected` is true:** Tell the user:
> "I found existing kipi data in the git repo that needs to migrate first. Running `/q-migrate` to handle that."
>
> Then run the `/q-migrate` skill. After migration completes, continue with setup detection below.

**Then:** Read `{config_dir}/founder-profile.md` (path from `kipi://paths`). If it contains `{{SETUP_NEEDED}}`, this is a fresh install. Tell the user: "This is a fresh Q Founder OS install. Let's get you set up — I'll ask a few questions, one topic at a time."

If `{{SETUP_NEEDED}}` is NOT present, ask: "You're already set up. Want to reconfigure something specific, or start fresh?"

## Process

Run these steps IN ORDER. Ask one category at a time. Confirm answers before moving to next step. Use a conversational tone.

### Step 1: Who are you?

Ask:
- What's your name?
- What's your role? (founder, operator, executive, etc.)
- What's your company/project name?
- What do you sell / what are you building? (one sentence)
- What stage are you at? (idea, pre-seed, seed, Series A, growth)
- Do you have a co-founder? If so, name and role.

**After getting the company name**, generate an instance name:
1. Call `kipi_suggest_instance_name(company=<company_name>)` to get a Discord-style suggestion (e.g. "eqbit-dragon12")
2. Show the suggestion: "I'll name this instance **eqbit-dragon12**. This is how kipi tracks your data separately from other projects. Want to keep it, or pick something different?"
3. If they want to change it, let them type a new name. Re-check uniqueness by calling `kipi_suggest_instance_name` again (it returns existing names).
4. If the name collides with an existing instance, tell them and suggest a new one.
5. Once confirmed, call `kipi_set_instance_name(name=<chosen_name>)` to register the instance.

**Save to:** `{config_dir}/founder-profile.md`

### Step 2: Who do you sell to?

Ask:
- Who is your target buyer? (title, department, company size)
- What industry/vertical?
- What's the pain you solve? (in the buyer's words, not yours)
- What do they use today instead of you? (competitors or manual process)
- What's your price point or deal size? (if known)

**Save to:** `{data_dir}/my-project/current-state.md` and `{config_dir}/canonical/discovery.md`

### Step 3: What's your positioning?

Ask:
- Do you have a one-liner? ("We help [who] do [what] by [how]")
- Any metaphors or analogies that have landed in conversations?
- What are you NOT? (common misclassifications)
- What are the top 3 objections you hear?

**Save to:** `{config_dir}/canonical/talk-tracks.md`, `{config_dir}/canonical/objections.md`

### Step 4: Your voice

Ask:
- How would you describe your writing style? (direct, casual, academic, etc.)
- Any words or phrases you naturally use?
- Any words or phrases you hate? (buzzwords, corporate speak, etc.)
- What language/communication patterns should I know about? (ESL, neurodivergent, etc.)
- Share 2-3 examples of messages or posts you've written that sound like you (paste or link)

**Save to:** `{config_dir}/voice/voice-dna.md` and `{config_dir}/voice/writing-samples.md`

If they mention ADHD, ASD, or AUDHD:
- Ask: "Want me to enable AUDHD executive function mode? It structures all output for minimal decision-making — copy-paste ready, friction-ordered, no pressure language."
- If yes: set `enabled: true` in `{config_dir}/enabled-integrations.md` under AUDHD Mode
- Read `.claude/skills/audhd-executive-function/SKILL.md` and populate the user profile at `{config_dir}/audhd/user-profile.md`

### Step 5: Your tools (SMART DETECTION)

Check `.mcp.json` at the project root for configured MCP servers. For each one found:

**Notion** — if `notion_api` server exists in `.mcp.json`:
- Tell the user: "I see Notion is configured. Let me test the connection..."
- Try listing databases via the Notion MCP tools
- If it works: "Notion is connected. We'll use it for CRM."
- If it fails: "Notion server is configured but not responding. Check your NOTION_TOKEN. Skipping for now — the system works with local files."
- Set `notion: true/false` in `enabled-integrations.md`

**Apify** — if `apify` server exists in `.mcp.json`:
- Tell the user: "I see Apify is configured for LinkedIn, Twitter, and Reddit scraping."
- Set `apify: true` in `enabled-integrations.md`

**Playwright** — if `playwright` server exists:
- Tell the user: "Browser automation is available for LinkedIn DMs and interactive tasks."
- Set `linkedin_chrome: true` in `enabled-integrations.md`

**For servers NOT in .mcp.json**, ask:
- "Do you use Google Calendar? Gmail?" → If yes, provide the MCP server config snippet to add
- "Want Gamma for deck/one-pager generation?" → If yes, provide config snippet
- "Want NotebookLM for research content?" → If yes, provide config snippet

After probing, write the final state to `{config_dir}/enabled-integrations.md`.

### Step 6: Your CRM

**If Notion is enabled:**
- Walk them through creating or connecting databases: Contacts, Interactions, Actions, Pipeline, LinkedIn Tracker, Content Pipeline, Editorial Calendar, Asset Library
- For each DB, get the database ID and save to `enabled-integrations.md` under Notion Database IDs
- Also save to `{data_dir}/my-project/notion-ids.md`

**If Notion is NOT enabled:**
- Tell them: "No problem — the system works with local files. `{data_dir}/my-project/relationships.md` is your CRM."

### Step 7: Your network

Ask:
- Who are your top 10 contacts right now? (name, role, company, relationship status)
- Any investors you're talking to?
- Any design partners or early customers?
- Any advisors or connectors?

**Save to:** `{data_dir}/my-project/relationships.md`

### Step 8: Confirmation

1. Show a summary of everything configured:
   - Founder profile
   - Integrations enabled/disabled
   - Canonical files populated
   - CRM mode (Notion vs local)
   - AUDHD mode (on/off)
2. Ask if anything needs adjusting
3. Remove `{{SETUP_NEEDED}}` from `founder-profile.md`
4. Remove `{{SETUP_NEEDED}}` from `enabled-integrations.md`
5. Tell the user where their data lives (read `kipi://paths` resource for actual resolved paths): "Your kipi data lives at **{config_dir}**. Back it up anytime with `kipi_backup`, or export with `kipi_export` to move to another machine. Backups run automatically after each `/q-morning`."
6. Tell the user: "You're set. Try `/q-morning` tomorrow to see the full system, or `/q-plan` right now to start prioritizing."

## Output rules
- Conversational tone, one step at a time
- Never dump all questions at once
- Confirm each step before moving on
- If the user seems overwhelmed, slow down and offer to skip optional steps
