# Connect LinkedIn (Chrome Automation)

## What This Does
Lets Kipi interact with LinkedIn directly in your browser - send DMs, post comments, engage with posts. This uses Chrome automation (not an API), so it acts as you in your browser.

## What the User Needs
- Google Chrome browser
- The Claude-in-Chrome extension installed
- A LinkedIn account they're logged into in Chrome

## Important Note

This integration is more hands-on than the others. The user needs to have Chrome open and be logged into LinkedIn. Kipi controls their browser tab, and they can watch everything happening in real time.

## Walk-Through Script

### Part 1: Explain

Say:

> "Let's set up LinkedIn automation. This is different from the other connections - instead of an access code, Kipi will work directly in your Chrome browser.
>
> What this means:
> - You'll see everything happening in real time in a Chrome tab
> - Kipi can send DMs, post comments, and engage on your behalf
> - You're always in control - you can stop it anytime
> - It uses your regular LinkedIn login, no special access needed
>
> Want to set this up?"

### Part 2: Install Chrome Extension

> "First, let's install the Chrome extension that lets me work with your browser:
>
> 1. Open **Google Chrome** (not Safari or Firefox - it has to be Chrome)
> 2. Go to the Chrome Web Store - search for **'Claude in Chrome'**
> 3. Click **Add to Chrome**
> 4. You'll see a small icon appear in your browser toolbar
> 5. Click the icon and make sure it says **Connected**
>
> Let me know when that's done."

### Part 3: Verify Browser Connection

> "Now make sure you're logged into LinkedIn:
>
> 1. Open **linkedin.com** in Chrome
> 2. Make sure you're signed in (you should see your profile in the top right)
> 3. Keep that tab open
>
> Let me check if I can see your browser... [run test]"

### Part 4: Test It

> "Let me try reading your LinkedIn feed to make sure everything works...
>
> [Run a simple read test - get page title from LinkedIn tab]
>
> I can see your LinkedIn! Everything's connected."

## When to Recommend This

- For `gtm-founder` and `content-creator` archetypes
- Chrome is the primary tool for all LinkedIn data (profiles, posts, DMs, engagement)
- Not during initial setup for `minimal` or `product-founder`

## Guardrails

- Never automate LinkedIn actions without the user seeing what's happening
- Always show the draft comment/DM before posting
- Respect LinkedIn rate limits (no more than 20-30 interactions per session)
- If the user isn't watching (tab not visible), pause and wait

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "I use Safari / Firefox" | "Chrome automation only works with Google Chrome. You'll need to open Chrome for LinkedIn tasks, but you can keep using your preferred browser for everything else." |
| "The extension says 'Disconnected'" | "Try clicking the extension icon and toggling it off and on. If that doesn't work, remove and reinstall the extension." |
| "I'm worried about LinkedIn banning me" | "Kipi acts like a normal person browsing LinkedIn - one action at a time, with natural pauses. It's much safer than bulk automation tools. But if you're concerned, we can skip this and you can handle LinkedIn manually." |
| "Can I watch what it's doing?" | "Yes! Everything happens in a visible Chrome tab. You'll see Kipi navigating, typing, and clicking in real time. You can stop it at any point." |
