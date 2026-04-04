# Getting Started with Kipi

This is the guide you send to new users. It covers everything they need to do BEFORE the in-system setup wizard takes over.

Send this as a PDF, email, or share as a document. Screenshots recommended at each step.

---

## What is Kipi?

Kipi is your personal operating system for running your business. It lives inside Claude (an AI assistant) and helps you with:

- Morning briefings with your calendar, email, and action items
- Managing your contacts and sales pipeline
- Writing outreach, follow-ups, and content in your voice
- Preparing for meetings
- Tracking everything without you having to remember

You talk to it in plain English. No coding, no technical skills needed.

## What You Need

1. **A computer** (Mac, Windows, or Linux)
2. **A web browser** (Chrome recommended)
3. **A Claude account** - this costs $20/month (Pro) or $100/month (Max)
4. **A GitHub account** - free
5. **About 20 minutes** for initial setup

## Step 1: Create Your Claude Account

1. Open your browser and go to **claude.ai**
2. Click **Sign up**
3. Create an account with your email (or sign in with Google)
4. You'll need to pick a plan:
   - **Pro ($20/month)** - works fine for daily use
   - **Max ($100/month)** - more capacity, recommended if you'll use this heavily
5. Enter your payment information
6. You're in!

> **Why does this cost money?** Kipi runs on Claude, which is an AI service by Anthropic. The subscription gives you access to the AI that powers everything. Think of it like a Netflix subscription, but for your business assistant.

## Step 2: Create Your GitHub Account

GitHub is where your Kipi data lives. Think of it as a private cloud folder for your system.

1. Go to **github.com**
2. Click **Sign up**
3. Enter your email, create a password, pick a username
4. Verify your email (they'll send you a code)
5. You can skip any optional setup questions

> **Is my data safe?** Your Kipi repository is private by default. Only you can see it. GitHub is used by millions of companies to store their code securely.

## Step 3: Get Your Own Copy of Kipi

Your Kipi admin will send you a link to a GitHub repository. Here's what to do:

1. Click the link they sent you
2. You'll see a green button that says **"Use this template"** - click it
3. Under "Repository name," type a name for your project (e.g., "my-kipi" or your company name)
4. Make sure **"Private"** is selected (this is important!)
5. Click **"Create repository"**
6. Wait a few seconds - you now have your own private copy

> **What if I don't see "Use this template"?** Your admin might have sent a different kind of link. Look for a **"Fork"** button instead, or ask them to resend the template link.

## Step 4: Open It in Claude

1. Go to **claude.ai/code** in your browser
2. Sign in with your Claude account (the one from Step 1)
3. Look for a **"Connect Repository"** or **"Open Project"** button
4. Click it and you'll see a list of your GitHub repositories
5. Select the one you just created in Step 3
6. Wait for it to load (this might take 30 seconds to a minute)

> **What if I don't see "Connect Repository"?** Make sure you're at **claude.ai/code** (not just claude.ai). The /code part is important.

## Step 5: Start Using Kipi

Once your project loads in Claude, just type **"hello"** or **"let's get started"**.

Kipi will detect that this is your first time and start a friendly setup conversation. It will:

1. Ask what kind of work you do (so it knows which tools to set up)
2. Walk you through connecting your tools (Notion, Gmail, Calendar, etc.) one at a time
3. Learn about you, your company, and your voice
4. Set everything up automatically

**Just answer the questions naturally.** If you get stuck on any step, say "skip this for now" and you can come back to it later.

## After Setup

Here are the main things you can do:

| What to say | What happens |
|------------|-------------|
| `/q-morning` | Your daily briefing - meetings, emails, action items, engagement opportunities |
| Paste meeting notes | Kipi automatically extracts key takeaways, action items, and follow-ups |
| `/q-plan` | Review and prioritize your actions |
| `/q-engage` | Work on social media engagement |
| "connect my [tool]" | Add a new tool connection anytime |

## Connecting Your Tools

During setup, Kipi will ask about connecting your tools. Here's a preview of what each one does:

| Tool | What it does | Do you need it? |
|------|-------------|-----------------|
| **Notion** | Tracks your contacts, pipeline, and actions | Recommended if you use Notion |
| **Google Calendar** | Lets Kipi see your meetings and prep you | Recommended |
| **Gmail** | Draft follow-up emails, track threads | Recommended |
| **LinkedIn (Chrome)** | See profiles, posts, DMs, engage on LinkedIn | Recommended for active LinkedIn users |
| **Apify** | X/Twitter scraping for engagement and leads | Optional |
| **Gamma** | Create pitch decks and one-pagers | Optional |

**You don't need any of these to start.** Kipi works with zero tools connected. You can add them one at a time whenever you're ready.

## Need Help?

- **During setup:** Just tell Kipi "I'm stuck" or "I don't understand" and it will help
- **After setup:** Say "help" to see what you can do
- **Technical problems:** Contact your Kipi admin

## Tips

- You can close the browser tab and come back anytime - your data is saved
- Kipi remembers your conversations and builds on them over time
- Start with `/q-morning` each day to build the habit
- Don't try to set up everything at once - start simple, add tools as you need them

---

*This guide is for users setting up Kipi via claude.ai/code. If you're a technical user who prefers the command line, see INSTANCE-SETUP.md for CLI instructions.*
