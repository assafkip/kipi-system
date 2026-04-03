# MCP Setup Playbook

How to get integrations working for different users in different environments. This is the admin reference - not user-facing.

## The Reality of MCP on Different Platforms

### claude.ai/code (web)

**Built-in integrations (no setup needed beyond OAuth):**
- Gmail - available via Claude.ai integrations panel
- Google Calendar - available via Claude.ai integrations panel
- Google Drive - available via Claude.ai integrations panel
- Notion - available via Claude.ai integrations panel (if Anthropic has added it)
- Gamma - may be available as a built-in

These connect with a single OAuth click. No tokens, no npm, no terminal. This is the ideal path for non-technical users.

**Custom MCP servers (.mcp.json):**
- claude.ai/code runs in a sandboxed environment connected to the user's GitHub repo
- It CAN read .mcp.json from the repo
- Servers that use `npx` (Apify, Reddit, Playwright) SHOULD work because the environment has Node.js
- BUT: tokens in .mcp.json get committed to the repo (privacy concern)
- Environment variable references (`${VAR}`) need the variable set somewhere the sandbox can read it

**What this means in practice:**
- For Gmail, Calendar: use Claude.ai built-in integrations (best experience)
- For Notion: use built-in if available, otherwise .mcp.json with direct token
- For Apify: .mcp.json with direct token (no built-in option)
- For Chrome/LinkedIn: DOES NOT WORK on claude.ai/code (requires local Chrome browser)
- For Playwright: may work in sandbox but limited usefulness without visible browser

### Claude Code CLI (local)

Everything works. .mcp.json servers run locally, Chrome automation works, environment variables work normally. This is the power-user path.

### Claude Code Desktop App

Same as CLI - full local access. Friendlier UI than terminal.

## Three Setup Scenarios

### Scenario 1: User Self-Serve (via claude.ai/code)

**Best for:** Users who are comfortable following step-by-step instructions independently.

**Flow:**
1. User forks the template repo
2. Opens it in claude.ai/code
3. The setup wizard (setup-flow.md) handles everything conversationally
4. For built-in integrations: Claude tells the user to click through the Claude.ai settings
5. For custom servers: Claude writes tokens directly into .mcp.json
6. Claude tests each connection live

**Token storage approach:**
- Built-in integrations: managed by Claude.ai (no token visible to user or repo)
- Custom servers: token goes directly in .mcp.json
- The repo is PRIVATE so this is acceptable
- Warn the user: "Never make this repository public - it contains your access codes"

**Limitations:**
- Chrome/LinkedIn automation won't work (no local browser)
- User might need to restart the claude.ai/code session after adding MCP servers
- If a custom server package isn't available in the sandbox, it won't work

**Fallback for unavailable servers:**
- If Notion MCP isn't available as built-in and custom server fails: use local files for CRM
- If Apify fails: skip X/Twitter scraping, Chrome fallback available
- If any server fails: the system works without it, just with reduced functionality

### Scenario 2: Admin Pre-Configures (before handoff)

**Best for:** Users who are completely non-technical. You (the admin) set up their repo before they ever see it.

**What you do:**
1. Fork the template repo into a new private repo under the user's GitHub account (or your org)
2. Add the user as a collaborator (or transfer ownership)
3. Pre-configure .mcp.json with their tokens:
   - Ask them for their Notion token (walk them through creating it on a call or via screenshots)
   - Ask them for their Apify token (same approach)
   - Write the tokens into .mcp.json and commit
4. Remove `{{SETUP_NEEDED}}` partially - leave it but pre-fill known fields
5. Or: leave `{{SETUP_NEEDED}}` so the wizard runs but tools are already connected

**What the user does:**
1. Opens claude.ai/code
2. Connects to the repo you set up
3. The wizard runs but integration steps just... work (you already configured them)
4. They only need to do the identity/positioning/voice steps

**Privacy consideration:**
- You will see their tokens during setup
- Make clear to the user: "I'll help you set this up, and then I'll remove my access"
- After setup: remove yourself as a collaborator on their repo
- Or: have them change their tokens after you hand off (Notion: regenerate integration token)

**Checklist for admin pre-config:**

```
[ ] Fork template repo
[ ] Set repo to Private
[ ] Add user as collaborator (or transfer ownership)
[ ] Get Notion token from user -> write to .mcp.json
[ ] Get Apify token from user -> write to .mcp.json
[ ] Test connections work (open in Claude Code yourself, run validators)
[ ] Commit and push
[ ] Send user the GETTING-STARTED.md (skip to Step 4)
[ ] After user confirms setup: remove your access
```

### Scenario 3: Live Setup on a Call

**Best for:** Users who want hand-holding. Highest success rate. Takes 30-45 minutes.

**Call structure:**

**Before the call (5 min prep):**
- Fork the template repo for them (or have them share screen and do it)
- Have the GETTING-STARTED.md open as your script

**Part 1: Accounts (10 min)**
- Walk them through creating Claude account + picking plan (share screen or they share)
- Walk them through creating GitHub account (if needed)
- Walk them through forking the template repo

**Part 2: Connect to Claude (5 min)**
- Have them open claude.ai/code
- Walk them through connecting the repository
- Confirm it loads

**Part 3: Tool connections (15-20 min)**
- You stay on the call while Claude runs the setup wizard
- For each integration the wizard asks about:
  - You guide them through the web UI in real time (Notion integrations page, Apify settings, etc.)
  - You can see if they're stuck and help immediately
  - Claude tests each connection and you confirm together

**Part 4: Identity setup (5-10 min)**
- The wizard handles this conversationally
- You can jump in if they need help articulating positioning or voice

**Part 5: Confirmation (2 min)**
- Verify everything works
- Show them how to do `/q-morning`
- Tell them to try it tomorrow morning

**Post-call:**
- Send follow-up email with:
  - Link to their repo (bookmark this)
  - Link to claude.ai/code (bookmark this)
  - Quick reference: `/q-morning`, paste notes for debrief, `/q-plan`
  - Your contact info for help

## Integration Compatibility Matrix

| Integration | claude.ai/code | CLI | Desktop | Setup method | Package |
|------------|---------------|-----|---------|-------------|---------|
| Gmail | Built-in OAuth | google-calendar-mcp | gmail-mcp | Click-through (web) or OAuth (CLI) | `npm i -g gmail-mcp` |
| Google Calendar | Built-in OAuth | google-calendar-mcp | google-calendar-mcp | Click-through (web) or OAuth (CLI) | `npm i -g google-calendar-mcp` |
| Notion | Built-in or .mcp.json | .mcp.json | .mcp.json | Token paste | `npx @notionhq/notion-mcp-server` |
| Apify | .mcp.json | .mcp.json | .mcp.json | Token paste | `npx @apify/actors-mcp-server` |
| Chrome/LinkedIn | NOT AVAILABLE | Works | Works | Extension install | Claude-in-Chrome extension |
| Reddit | .mcp.json | .mcp.json | .mcp.json | No token needed | `npx reddit-mcp-buddy` |
| Telegram | NOT AVAILABLE | .mcp.json | .mcp.json | API credentials from my.telegram.org | `npm i -g telegram-mcp` |
| Playwright | Maybe (sandbox) | Works | Works | No token needed | `npx @playwright/mcp@latest` |
| Gamma | Built-in (if available) | .mcp.json | .mcp.json | Varies | Claude.ai integration |

## When Things Go Wrong

### "The MCP server won't start"
- On claude.ai/code: the sandbox might not have the package. Try reloading the session.
- On CLI: run `npx -y [package-name]` manually to see the error.

### "My token doesn't work"
- Most common: token was copied with extra whitespace or missing characters
- Second most common: Notion integration wasn't shared with the right databases
- Fix: regenerate the token and paste again

### "I connected everything but Claude can't see my data"
- For Notion: databases must be explicitly shared with the integration (Connections menu)
- For Gmail/Calendar: permissions might have been denied during OAuth
- Fix: disconnect and reconnect, making sure to grant all permissions

### "I added a server but nothing changed"
- On claude.ai/code: may need to close and reopen the project
- On CLI: restart Claude Code (`claude` command)
- The .mcp.json is read at session start, not live-reloaded

### "Chrome automation isn't working"
- Only works on CLI/Desktop, not claude.ai/code
- Chrome must be open with the extension installed and showing "Connected"
- LinkedIn must be open and logged in in a Chrome tab

## Upgrading from claude.ai/code to CLI

If a user starts on claude.ai/code and later wants Chrome automation or more power:

1. Install Claude Code CLI: `npm install -g @anthropic-ai/claude-code`
2. Clone their repo locally: `git clone [repo-url]`
3. Open it: `cd [repo] && claude`
4. All their data, config, and history carry over through the repo
5. Now Chrome/LinkedIn automation works too

This is a natural upgrade path - start simple, add power later.
