# Settings Builder

This file tells Claude how to assemble the user's configuration files during onboarding. The user should never edit JSON directly - Claude builds it for them.

## Files That Get Built

### 1. `.mcp.json` (project-level MCP server config)

This file lives at the root of the user's project directory. It tells Claude Code which external tools to load.

**Start with an empty template:**
```json
{
  "mcpServers": {}
}
```

**Add servers one at a time** as the user connects each integration. Never write all servers at once - only add what's been successfully connected and tested.

#### Notion
```json
"notion_api": {
  "command": "notion-mcp-server",
  "args": [],
  "env": {
    "NOTION_TOKEN": "[user's token]"
  }
}
```
**Prerequisite:** `npm install -g notion-mcp-server`

#### Apify
```json
"apify": {
  "command": "npx",
  "args": ["-y", "@apify/actors-mcp-server@0.9.10"],
  "env": {
    "APIFY_TOKEN": "[user's token]",
    "TOOLS": "actors,apify/linkedin-profile-scraper,apify/linkedin-posts-scraper,apify/linkedin-connections-scraper,curious_coder/twitter-scraper,apify/reddit-scraper,apify/web-scraper"
  }
}
```
**Prerequisite:** Node.js + npm installed (npx comes with npm)

#### Gmail (CLI/Desktop only)
```json
"ask_gmail": {
  "command": "gmail-mcp",
  "args": [],
  "env": {
    "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
    "HOME": "[user home dir]"
  }
}
```
**Prerequisite:** `npm install -g gmail-mcp` + Google OAuth credentials setup

#### Google Calendar (CLI/Desktop only)
```json
"ask_calendar": {
  "command": "google-calendar-mcp",
  "args": [],
  "env": {
    "GOOGLE_OAUTH_CREDENTIALS": "[path to gcp-oauth.keys.json]",
    "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
    "HOME": "[user home dir]"
  }
}
```
**Prerequisite:** `npm install -g google-calendar-mcp` + Google Cloud project with Calendar API + OAuth credentials file

#### Reddit
```json
"reddit": {
  "command": "npx",
  "args": ["reddit-mcp-buddy"],
  "env": {
    "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
    "HOME": "[user home dir]"
  }
}
```
**Prerequisite:** Node.js + npm installed (no token needed)

#### Telegram (optional)
```json
"telegram": {
  "command": "telegram-mcp",
  "env": {
    "TG_APP_ID": "[user telegram app id]",
    "TG_API_HASH": "[user telegram api hash]",
    "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
    "HOME": "[user home dir]"
  }
}
```
**Prerequisite:** `npm install -g telegram-mcp` + Telegram API credentials from my.telegram.org

#### Playwright (browser automation fallback)
```json
"playwright": {
  "command": "npx",
  "args": ["@playwright/mcp@latest"],
  "env": {
    "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
    "HOME": "[user home dir]"
  }
}
```
**Prerequisite:** Node.js + npm installed

### 2. Claude.ai Built-in Integrations

These don't go in `.mcp.json` - they're connected through Claude's own settings UI:

- **Gmail** - Connected via Claude.ai integrations panel
- **Google Calendar** - Connected via Claude.ai integrations panel
- **Gamma** - Connected via Claude.ai integrations panel (if available)

For these, walk the user through the Claude.ai settings UI. No code or JSON needed.

### 3. `my-project/notion-ids.md` (Notion database IDs)

After CRM setup, save all database IDs:

```markdown
# Notion Database IDs

## CRM
- Contacts: [database_id]
- Interactions: [database_id]
- Actions: [database_id]
- Pipeline: [database_id]

## Content
- Content Pipeline: [database_id]
- Editorial Calendar: [database_id]
- Asset Library: [database_id]

## Other
- LinkedIn Tracker: [database_id]
```

### 4. `my-project/connected-tools.md` (connection status tracker)

Create this file during setup and update it whenever a tool is connected or disconnected:

```markdown
# Connected Tools

Last updated: [date]

## Connected
- [tool]: connected [date], status: active

## Not Connected
- [tool]: skipped during setup, reason: [user choice / not needed for archetype]

## Connection History
- [date]: Connected [tool]
- [date]: Skipped [tool] (user chose to skip)
```

## How to Write .mcp.json

### For claude.ai/code users

The `.mcp.json` file lives in the project's GitHub repo. Claude can write it directly using the Write tool.

Tell the user:

> "I'm saving your connection settings to the project. This means they'll be there every time you open this project."

### For CLI / Desktop users

Same approach - write `.mcp.json` to the project root. Claude Code CLI reads it automatically.

### Environment Variables vs. Hardcoded Tokens

**Preferred approach:** Store tokens directly in `.mcp.json` for simplicity. The file is in the user's private repo.

**More secure approach:** Use `${ENV_VAR}` references and tell the user to set environment variables. Only recommend this if the user asks about security or if the repo might become public.

> "Your access codes are stored in your project settings. Since this is your private repo, they're safe there. If you ever make this repo public, let me know and we'll move them to a more secure location."

## Build Order

When connecting multiple tools, always build in this order:
1. Notion (CRM depends on it)
2. Google Calendar (morning routine needs it)
3. Gmail (follow-ups need it)
4. Apify (research needs it)
5. Chrome/LinkedIn (engagement needs Apify data first)
6. Gamma (nice to have, always last)

## Validation After Building

After writing any config file:
1. Ask Claude Code to reload MCP servers (may require reopening the project)
2. Run the matching validator from `validators/`
3. If validation fails, check the config for typos or missing fields
4. If validation passes, update `connected-tools.md`

## Recovery

If the user's config gets corrupted:
- Read `connected-tools.md` for what should be connected
- Rebuild `.mcp.json` from scratch using the saved tokens
- Re-run validators for each connected tool
