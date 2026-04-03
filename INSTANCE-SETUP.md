# Setting Up a New Kipi Instance

## Option A: Using claude.ai/code (No Technical Skills Needed)

This is the easiest way to get started. No terminal, no installs, no coding.

### What You Need
1. A Claude account with a Pro ($20/month) or Max ($100/month) subscription at **claude.ai**
2. A GitHub account (free) at **github.com**

### Step-by-Step

**1. Create your GitHub account (skip if you already have one)**
- Go to **github.com** and click **Sign up**
- Use your email, create a password, pick a username
- Verify your email

**2. Get your own copy of Kipi**
- Your Kipi admin will share a repository link with you
- Click the **"Use this template"** button (green button, top right)
- Name your project (e.g., "my-kipi" or your company name)
- Make sure **Private** is selected (this keeps your data private)
- Click **Create repository**

**3. Open it in Claude**
- Go to **claude.ai/code** in your browser
- Sign in with your Claude account
- Click **"Connect Repository"** (or "Open Project")
- Find and select the repository you just created
- Wait for it to load

**4. Start the setup wizard**
- Just say **"hello"** or **"let's get started"**
- Kipi will detect this is a fresh install and walk you through everything
- It will ask you questions one at a time - just answer naturally
- It will help you connect your tools (Notion, Gmail, Calendar, etc.) step by step
- The whole setup takes about 10-15 minutes

**5. You're done!**
- Every day, open claude.ai/code and say `/q-morning` for your daily briefing
- After any meeting, paste your notes and Kipi will extract everything important
- Say `/q-plan` to review and prioritize your actions

### Connecting Your Tools

During setup, Kipi will ask which tools you use and walk you through connecting them. You don't need to prepare anything in advance. The setup guides use plain language and tell you exactly where to click.

Tools you might connect:
- **Notion** - for tracking contacts, pipeline, and actions
- **Google Calendar** - so Kipi can prep you for meetings
- **Gmail** - for drafting follow-up emails
- **LinkedIn** (via Chrome) - for profiles, posts, DMs, and engagement
- **Apify** - for X/Twitter scraping (optional, Chrome fallback available)
- **Gamma** - for creating pitch decks and one-pagers

You can skip any tool during setup and connect it later by saying "connect my [tool name]".

---

## Option B: Using Claude Code CLI (For Technical Users)

### Quick Start

```bash
# From the kipi-system directory:
./kipi-new-instance.sh /path/to/my-project my-project-name
```

This will:
1. Create the directory (if needed)
2. Initialize git
3. Add kipi-system as a subtree at `q-system/`
4. Create a template `CLAUDE.md`
5. Register the instance in `instance-registry.json`

### Manual Setup

If you prefer to do it step by step:

```bash
# 1. Create and enter your project directory
mkdir ~/Desktop/my-project && cd ~/Desktop/my-project

# 2. Initialize git
git init

# 3. Add kipi-system as a subtree
git subtree add --prefix=q-system https://github.com/assafkip/kipi-system.git main --squash

# 4. Create your CLAUDE.md (see template below)

# 5. Commit
git add -A && git commit -m "Initial setup with kipi-system skeleton"
```

### CLAUDE.md Template

Your root `CLAUDE.md` must import the skeleton behavioral rules:

```markdown
# My Project Name

## About
One-sentence description.

## Founder OS (Skeleton)
@q-system/q-system/CLAUDE.md

## Instance Rules
(Add your project-specific rules here)
```

The `@q-system/q-system/CLAUDE.md` import loads all skeleton behavioral rules (setup wizard, operating modes, memory architecture, voice framework, agent pipeline).

### After Setup

Open the project in Claude Code. The skeleton's setup wizard will detect `{{SETUP_NEEDED}}` in the founder profile and walk you through configuration.

### Marketplace Plugins

Your instance automatically registers the kipi marketplace via `settings-template.json`. The core plugin (AUDHD + voice + research mode) is enabled by default. To enable additional plugins, add them to your `.claude/settings.json`:

```json
{
  "enabledPlugins": {
    "kipi-core@kipi": true,
    "kipi-ops@kipi": true,
    "kipi-design@kipi": true
  }
}
```

Available plugins:
- **kipi-core** - AUDHD executive function + founder voice + research mode (recommended for all)
- **kipi-ops** - Council debates + customer fit reviews (for GTM/sales work)
- **kipi-design** - UI/UX, brand identity, visual assets (for design/website work)

Research mode (`/research <topic>`) is included in kipi-core. No extra install needed.

The "Founder OS" output style is set by default in `settings-template.json` and enforces voice rules on all responses.

---

## Directory Structure

After setup, your project will look like:

```
my-project/
  q-system/           # Kipi skeleton subtree (DO NOT edit directly)
    q-system/          # Core OS (agents, scripts, templates)
    CLAUDE.md          # Skeleton root CLAUDE.md
    validate-separation.py
  CLAUDE.md            # Your instance CLAUDE.md (edit this)
```

Instance-specific content (canonical files, my-project, marketing assets, voice samples) stays outside `q-system/`.
