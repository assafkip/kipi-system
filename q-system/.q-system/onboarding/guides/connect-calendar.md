# Connect Google Calendar

## What This Does
Lets Kipi see your upcoming meetings so it can prepare briefings, suggest talking points, and build your daily schedule.

## What the User Needs
- A Google account with Google Calendar
- The ability to authorize apps

## Walk-Through Script

### Part 1: Explain

Say:

> "Let's connect your Google Calendar. This lets me:
> - See what meetings you have today and this week
> - Prep you with context on who you're meeting and what to cover
> - Build your morning schedule around your real calendar
>
> I can only read your calendar - I won't create or change any events unless you ask me to."

### Part 2: Connect via Claude.ai MCP

If the user is on claude.ai/code, Calendar is a built-in integration:

> "This one's easy:
>
> 1. Look for **'Connect tools'** or **'Integrations'** in your Claude settings
> 2. Find **Google Calendar** in the list
> 3. Click **Connect** and sign into your Google account
> 4. Grant the permissions when asked
>
> Done!"

### Part 3: Verify

> "Let me check... [run test]. I can see your calendar. You have [N] events today. Connected!"

## For CLI / Desktop Users

The Calendar connector uses the `google-calendar-mcp` package.

**If Gmail is already connected via the same Google Cloud project:**

> "You already set up a Google project for Gmail. Let me check if Calendar works too... [run test]."

If it works, done. If not:

> "We need to add Calendar access to your Google project:
>
> 1. Go to **console.cloud.google.com**
> 2. Make sure your **Kipi** project is selected at the top
> 3. Search for **Google Calendar API** and click **Enable**
> 4. That's it - the same credentials should work."

**If Gmail is NOT connected (fresh Google setup):**

> "Paste this into your terminal:
>
> `npm install -g google-calendar-mcp`"

Then follow the same Google Cloud setup as in `connect-gmail.md` (create project, enable Calendar API, create OAuth credentials, download JSON).

Write to the user's `.claude/settings.json` mcpServers section:
```json
"ask_calendar": {
  "command": "google-calendar-mcp",
  "args": [],
  "env": {
    "GOOGLE_OAUTH_CREDENTIALS": "[path to their gcp-oauth.keys.json]",
    "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
    "HOME": "[user home dir]"
  }
}
```

> "The first time I check your calendar, a browser window will pop up asking you to sign into Google. Click through and allow access. This only happens once."

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "I use Outlook/Microsoft calendar" | "The built-in integration is for Google Calendar. If you use Outlook, we'll skip this for now. Your morning routine will still work, I just won't have your meeting schedule." |
| "I have multiple Google accounts" | "Connect the one you use for work meetings. You can switch later if needed." |
| "Will it see my personal events?" | "It sees all events on the calendar you connect. If you want to keep personal events private, connect only your work calendar." |
| "I'm worried about permissions" | "Kipi only reads your calendar. It can't create, edit, or delete events unless you explicitly ask it to." |
