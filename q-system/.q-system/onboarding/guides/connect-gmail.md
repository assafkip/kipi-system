# Connect Gmail

## What This Does
Lets Kipi read your recent emails, draft follow-ups, and track email threads with your contacts. Kipi never sends emails without your approval.

## What the User Needs
- A Google account with Gmail
- The ability to authorize apps (not blocked by a company admin)

## Walk-Through Script

### Part 1: Explain What's Happening

Say:

> "Let's connect your Gmail. This lets me:
> - See your recent emails so I can prep you for meetings
> - Draft follow-up emails you can review before sending
> - Track email threads with your contacts
>
> I'll never send anything without your say-so."

### Part 2: Connect via Claude.ai MCP

If the user is on claude.ai/code, Gmail is available as a built-in Claude.ai integration:

> "Good news - Gmail connects directly through Claude.
>
> 1. Look for a **'Connect tools'** or **'Integrations'** option in your Claude settings
> 2. Find **Gmail** in the list
> 3. Click **Connect** and sign into your Google account
> 4. Grant the permissions it asks for
>
> That's it - no codes to copy or anything to install."

### Part 3: Verify

After they say it's done, run the validator to test the connection.

> "Let me check... [run test]. I can see your inbox. You're connected!"

## For CLI / Desktop Users

If the user is using Claude Code CLI or desktop app instead of claude.ai/code, they need the `gmail-mcp` package:

> "Since you're using Claude Code on your computer, we need a couple extra steps."

**Step 1: Install the Gmail connector**

> "Paste this into your terminal:
>
> `npm install -g gmail-mcp`"

**Step 2: Google Cloud setup**

> "Now we need to connect it to your Google account:
>
> 1. Go to **console.cloud.google.com** in your browser
> 2. Click **Select a project** at the top, then **New Project**
> 3. Name it **Kipi** and click **Create**
> 4. In the search bar at the top, search for **Gmail API** and click **Enable**
> 5. Go to **APIs & Services > Credentials** in the left menu
> 6. Click **+ Create Credentials > OAuth client ID**
> 7. If asked for consent screen: pick **External**, fill in app name as **Kipi**, add your email, save
> 8. For Application type pick **Desktop app**, name it **Kipi**
> 9. Click **Create** - you'll see a download button. Download the JSON file.
> 10. Save it somewhere safe (like your home folder)
>
> Tell me where you saved the file and I'll configure the rest."

This is more involved. If the user seems overwhelmed, suggest:

> "This part is a bit technical. Would you rather skip Gmail for now and connect it later when you have someone who can help? Your morning routine will still work - I just won't be able to check your email."

**Step 3: Configure**

Write to the user's `.claude/settings.json` mcpServers section:
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

The first time they use it, `gmail-mcp` will open a browser window for Google OAuth consent. Tell the user:

> "The first time I try to read your email, a browser window will pop up asking you to sign into Google. Click through and allow access. This only happens once."

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "My company blocks third-party apps" | "Check with your IT team, or use a personal Gmail account instead." |
| "I don't see Gmail in the integrations" | "It might be under 'Google' or 'Google Workspace'. Look for anything Google-related." |
| "I'm worried about privacy" | "Kipi reads emails locally in your session. Nothing is stored on external servers. Your email data stays between you and Claude." |
| "Can Kipi send emails?" | "It can create drafts, but only you can hit Send. It will never send anything automatically." |
