# Connect Notion

## What This Does
Connects your Notion workspace so Kipi can manage your contacts, pipeline, actions, and content calendar. This becomes your CRM.

## What the User Needs
- A Notion account (free plan works)
- A workspace they own or have admin access to

## Platform Detection

Before starting, determine how the user is running Kipi:

**If claude.ai/code (PREFERRED):** Use the Built-in path. This connects via `mcp__claude_ai_Notion__*` tools with full read/write support, no local server needed.

**If CLI or Desktop:** Use the Token path. This runs a local `notion-mcp-server` via `.mcp.json`.

### Built-in Path (claude.ai/code only)

Say:

> "Let's connect your Notion. This one might be really easy:
>
> 1. Look for a **'Connect tools'** or **'Integrations'** option in your Claude settings
> 2. Search for **Notion**
> 3. If it's there, click **Connect** and sign into your Notion account
> 4. Grant the permissions it asks for
>
> Do you see Notion in the list?"

If yes and it connects: run the validator and you're done.
If no: fall back to the Token path below.

### Token Path

Say:

> "Let's connect your Notion. Here's what to do:
>
> 1. Open your browser and go to **notion.so/profile/integrations**
> 2. Click the **'+ New integration'** button
> 3. For the name, type **Kipi**
> 4. Make sure your workspace is selected
> 5. Click **Submit**
> 6. You'll see a secret code that starts with **ntn_** - copy the whole thing
> 7. Paste it here"

### Part 2: Save the Code

When they paste the code:

1. Validate it starts with `ntn_` (or `secret_` for older integrations)
2. If invalid: "That doesn't look right - it should start with 'ntn_'. Can you try copying it again? Make sure you click 'Show' first and then copy the full code."
3. If valid: Write it to the `.mcp.json` file as the `NOTION_TOKEN` value, and to the user's environment

Save to `.mcp.json`:
```json
{
  "mcpServers": {
    "notion_api": {
      "command": "notion-mcp-server",
      "args": [],
      "env": {
        "NOTION_TOKEN": "[their token]"
      }
    }
  }
}
```

Also instruct the user:

> "Now I need you to do one more thing so this works every time you open Kipi:
>
> 1. In Claude Code, open your settings (click the gear icon or press Cmd+,)
> 2. Find the section for environment variables
> 3. Add a new one: name it **NOTION_TOKEN** and paste the same code"

### Part 3: Server Setup

**On claude.ai/code:** The server runs automatically via `npx` - no install needed. Write to `.mcp.json`:
```json
"notion_api": {
  "command": "npx",
  "args": ["-y", "@notionhq/notion-mcp-server"],
  "env": {
    "NOTION_TOKEN": "[their token]"
  }
}
```

Tell the user:
> "I've saved your connection settings. You might need to reload this project for it to take effect. Close this tab and reopen claude.ai/code with your project."

**On CLI/Desktop:** Same `.mcp.json` entry works. Or if they prefer a global install:
> "I need to install the Notion connector. This takes a few seconds."
Run: `npm install -g @notionhq/notion-mcp-server`

### Part 4: Share Databases

After the integration is created, the user needs to share their Notion databases with it:

> "Almost done! Now we need to give Kipi access to your Notion pages.
>
> For each database or page you want Kipi to use:
> 1. Open the page in Notion
> 2. Click the **...** menu in the top right
> 3. Go to **Connections**
> 4. Search for **Kipi** and click it
>
> If you don't have databases set up yet, no worries - I'll create them for you in the next step."

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "I can't find the integrations page" | "Try going directly to notion.so/profile/integrations in your browser. You need to be logged into Notion first." |
| "I don't see '+ New integration'" | "You might not have admin access to this workspace. Check with whoever set it up, or create a new workspace." |
| "The code doesn't start with ntn_" | "Older Notion integrations use codes starting with 'secret_'. That works too - paste it here." |
| "notion-mcp-server command not found" | "The Notion connector isn't installed on your computer. Run: npm install -g notion-mcp-server" |
| Connection test fails | "Make sure you shared your databases with the Kipi integration (the Connections step). The integration can only see pages you've explicitly shared with it." |
