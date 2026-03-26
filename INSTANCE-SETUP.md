# Setting Up a New Kipi Instance

## Quick Start

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

## Manual Setup

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

## CLAUDE.md Template

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

## After Setup

Open the project in Claude Code. The skeleton's setup wizard will detect `{{SETUP_NEEDED}}` in the founder profile and walk you through configuration.

## Directory Structure

After setup, your project will look like:

```
my-project/
  q-system/           # Kipi skeleton subtree (DO NOT edit directly)
    q-system/          # Core OS (agents, scripts, templates)
    CLAUDE.md          # Skeleton root CLAUDE.md
    validate-separation.sh
  CLAUDE.md            # Your instance CLAUDE.md (edit this)
```

Instance-specific content (canonical files, my-project, marketing assets, voice samples) stays outside `q-system/`.
