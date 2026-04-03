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

**Preferred (claude.ai/code users):** Connect Notion via Claude.ai integrations panel. No `.mcp.json` entry needed -- the cloud integration provides `mcp__claude_ai_Notion__*` tools with full read/write support.

**CLI-only fallback** (if cloud integration unavailable):
```json
"notion_api": {
  "command": "npx",
  "args": ["-y", "@notionhq/notion-mcp-server"],
  "env": {
    "NOTION_TOKEN": "[user's token]"
  }
}
```
**Prerequisite:** Node.js + npm installed. Get token from https://www.notion.so/my-integrations

#### Reddit MCP (no auth needed)
```json
"reddit": {
  "command": "uvx",
  "args": ["reddit-no-auth-mcp-server"]
}
```
**Prerequisite:** Python + uv installed (`pip install uv` or `brew install uv`)

#### Apify (X/Twitter only)
```json
"apify": {
  "command": "npx",
  "args": ["-y", "@apify/actors-mcp-server@0.9.10"],
  "env": {
    "APIFY_TOKEN": "[user's token]",
    "TOOLS": "actors,curious_coder/twitter-scraper"
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

#### Reddit (alternative)

**Note:** The primary Reddit config is the no-auth server above (via uvx). This is an alternative if uvx is not available:
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

After CRM setup, save database IDs. Which databases exist depends on archetype (see setup-flow.md Step 7):

```markdown
# Notion Database IDs

## CRM (GTM founders / operators)
- Contacts: [database_id]
- Interactions: [database_id]
- Actions: [database_id]
- Pipeline: [database_id]
- Content Pipeline: [database_id]

## CRM (product founders)
- Contacts: [database_id]
- Interactions: [database_id]
- Actions: [database_id]
- Content Pipeline: [database_id]

## CRM (content creators)
- Contacts: [database_id]
- Content Pipeline: [database_id]
- Actions: [database_id]
```

Only include sections for databases that were actually created. Delete unused sections.

### 4. Connection status tracking

Connection status is tracked in `my-project/founder-profile.md` under the `## Connected Tools` section. Update that section when tools are connected or disconnected. Do NOT create a separate `connected-tools.md` file.

## How to Write .mcp.json

### For claude.ai/code users

The `.mcp.json` file lives in the project's GitHub repo. Claude can write it directly using the Write tool.

Tell the user:

> "I'm saving your connection settings to the project. This means they'll be there every time you open this project."

### For CLI / Desktop users

Same approach - write `.mcp.json` to the project root. Claude Code CLI reads it automatically.

### Environment Variables vs. Hardcoded Tokens

**Preferred approach:** Use `${ENV_VAR}` references in `.mcp.json` and store actual tokens in environment variables or `.env` files that are gitignored. This follows the project's security rules (see `.claude/rules/security.md`).

Tell the user:

> "I'll save your connection settings so they load automatically. Your access codes will be stored separately from the project files so they don't accidentally get shared."

**For CLI/Desktop users:** Store tokens in `~/.zshrc`, `~/.bashrc`, or a `.env` file in the project root (already gitignored).

**For claude.ai/code users:** Tokens in `.mcp.json` are stored in the user's private project. This is acceptable since the file is not committed to a shared repo. But if the repo might become public, use `${ENV_VAR}` references.

## Build Order

When connecting multiple tools, always build in this order:
1. Notion (CRM depends on it)
2. Google Calendar (morning routine needs it)
3. Gmail (follow-ups need it)
4. Chrome/LinkedIn (engagement, profiles, posts, DMs)
5. Apify (X/Twitter scraping, optional)
6. Gamma (nice to have, always last)

## Validation After Building

After writing any config file:
1. Ask Claude Code to reload MCP servers (may require reopening the project)
2. Run the matching validator from `validators/`
3. If validation fails, check the config for typos or missing fields
4. If validation passes, update `my-project/founder-profile.md` Connected Tools section

## Recovery

If the user's config gets corrupted:
- Read `my-project/founder-profile.md` Connected Tools section for what should be connected
- Rebuild `.mcp.json` from scratch using the saved tokens
- Re-run validators for each connected tool
