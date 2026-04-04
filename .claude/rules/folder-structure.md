---
description: Strict folder structure adherence for the kipi-system project
---

# Folder Structure (ENFORCED)

This project follows a strict directory layout aligned with Claude Code documentation. Every file must be in its canonical location. No exceptions without founder approval.

## Canonical Directory Tree

```
kipi-system/                          # Project root (skeleton/template repo + marketplace)
├── CLAUDE.md                         # Root instructions
├── README.md                         # Project overview
├── INSTANCE-SETUP.md                 # Setup guide for new instances
├── ARCHITECTURE.md                   # System architecture overview
├── SETUP.md                          # Detailed setup reference
├── CONTRIBUTE.md                     # Contribution guidelines
├── UPDATE.md                         # Update instructions for instances
├── .mcp.json                         # MCP server config (project scope)
├── .gitignore                        # Standard ignores
├── kipi                              # CLI entry point (bash)
├── kipi-new-instance.sh              # Creates new instances (used by kipi new)
├── kipi-update.sh                    # Pulls updates to instances (used by kipi update)
├── kipi-push-upstream.sh             # Pushes generic changes back (used by kipi push)
├── build-template-repo.sh            # Builds clean template for GitHub fork users
├── validate-separation.py            # Validation harness (used by kipi check)
├── instance-registry.json            # Registered project instances
├── skill-manifest.json               # Plugin group assignments per instance
├── settings-template.json            # Template for new instances
│
├── sites/                            # Vercel-deployed skill landing pages (GITIGNORED content)
│   ├── index.html
│   ├── vercel.json
│   └── <skill-name>/                # One subdir per published skill page
│
├── .claude-plugin/                   # Marketplace manifest
│   └── marketplace.json              # Lists kipi-core, kipi-ops, kipi-design plugins
│
├── plugins/                          # Marketplace plugin groups
│   ├── kipi-core/                    # Core (every instance)
│   │   ├── .claude-plugin/plugin.json
│   │   └── skills/
│   │       ├── audhd-executive-function/
│   │       ├── founder-voice/
│   │       └── research-mode/
│   ├── kipi-ops/                     # Operations (GTM instances)
│   │   ├── .claude-plugin/plugin.json
│   │   └── skills/
│   │       ├── council/
│   │       └── customer-fit-review/
│   └── kipi-design/                  # Design (UI/visual instances)
│       ├── .claude-plugin/plugin.json
│       └── skills/
│           ├── ui-ux-pro-max/
│           ├── brand/
│           └── design/
│
├── memory/
│   └── MEMORY.md                     # Auto-memory index (first 200 lines load at session start)
│
├── .claude/                          # Claude Code configuration
│   ├── settings.json                 # Shared settings (committed)
│   ├── settings.local.json           # Personal overrides (GITIGNORED)
│   │
│   ├── agents/                       # Custom agent definitions
│   │   ├── preflight.md              # Haiku - pipeline gate-keeper
│   │   ├── data-ingest.md            # Haiku - calendar/email/Notion pulls
│   │   ├── engagement-hitlist.md     # Opus - copy-paste engagement actions
│   │   ├── synthesizer.md            # Opus - daily schedule assembly
│   │   └── content-reviewer.md       # Sonnet - 4-pass content review
│   │
│   ├── output-styles/                # Custom output styles
│   │   └── founder.md                # Founder OS voice baseline
│   │
│   ├── rules/                        # Path-scoped instruction files
│   │   └── (14 files: anti-misclassification, audhd, auto-detection,
│   │        coding-standards, content-output, design-auto-invoke,
│   │        dev-skills-auto-invoke, folder-structure, marketing-system,
│   │        morning-pipeline, security, sycophancy, token-discipline,
│   │        voice-enforcement)
│   │
│   └── plans/                        # Plan mode output (auto-created, GITIGNORED)
│       └── *.md
│
├── q-system/                         # Core operating system
│   ├── CLAUDE.md                     # Q-system behavioral rules (<200 lines)
│   │
│   ├── canonical/                    # Source of truth (IMMUTABLE by agents)
│   │   ├── decisions.md
│   │   ├── discovery.md
│   │   ├── engagement-playbook.md
│   │   ├── content-intelligence.md
│   │   ├── lead-lifecycle-rules.md
│   │   ├── market-intelligence.md
│   │   ├── objections.md
│   │   ├── pricing-framework.md
│   │   ├── talk-tracks.md
│   │   └── verticals.md
│   │
│   ├── my-project/                   # Instance-specific state
│   │   ├── current-state.md
│   │   ├── founder-profile.md        # Identity, platform handles, connected tools
│   │   ├── relationships.md
│   │   ├── competitive-landscape.md
│   │   ├── lead-sources.md           # Reddit subreddits, Medium tags, X accounts to monitor
│   │   ├── notion-ids.md
│   │   └── progress.md
│   │
│   ├── marketing/                    # Content pipeline
│   │   ├── README.md
│   │   ├── brand-voice.md
│   │   ├── content-guardrails.md
│   │   ├── content-themes.md
│   │   ├── assets/                   # Reusable marketing assets
│   │   └── templates/                # Content + schedule templates
│   │
│   ├── methodology/                  # Operating frameworks
│   │   ├── debrief-template.md
│   │   ├── modes.md
│   │   └── reference.md
│   │
│   ├── memory/                       # Session state (lightweight)
│   │   ├── last-handoff.md           # Session continuity (written by /q-handoff)
│   │   ├── morning-state.md          # Checkpoint state (written by /q-checkpoint)
│   │   ├── marketing-state.md        # Publish log + cadence actuals
│   │   ├── sycophancy-log.json       # Rolling bias audit log
│   │   ├── working/                  # Working memory (current session)
│   │   ├── weekly/                   # Weekly memory rollups
│   │   └── monthly/                  # Monthly memory rollups
│   │
│   ├── hooks/                        # Session lifecycle scripts
│   │   ├── session-start.py          # Once-daily context injection (SessionStart hook)
│   │   ├── session-context.sh        # SessionStart hook (date, handoff, energy)
│   │   ├── post-compact.sh           # PostCompact hook (mode, loops, voice reminder)
│   │   ├── stop-logger.sh            # Stop hook (async effort logging)
│   │   ├── statusline.sh             # StatusLine display script
│   │   └── auto-update.sh            # Auto-update hook
│   │
│   ├── output/                       # Generated artifacts (GITIGNORED)
│   │   ├── morning-log-*.json
│   │   ├── schedule-data-*.json
│   │   ├── daily-schedule-*.html
│   │   ├── session-effort-*.log
│   │   └── .gitkeep
│   │
│   └── .q-system/                    # Execution infrastructure
│       ├── commands.md               # Command reference
│       ├── preflight.md              # Tool manifest + known issues
│       ├── state-model.md            # State machine design
│       │
│       ├── [Python harnesses]        # Deterministic guardrails
│       │   ├── token-guard.py        # PreToolUse circuit breaker
│       │   ├── audit-morning.py      # Post-routine audit
│       │   ├── sycophancy-harness.py # Independent sycophancy verify
│       │   ├── verify-bus.py         # Bus file structure checks
│       │   ├── verify-orchestrator.py
│       │   ├── verify-schedule.py
│       │   └── bus-to-log.py         # Bus -> morning-log bridge
│       │
│       ├── [Shell scripts]
│       │   ├── log-step.py
│       │   └── loop-tracker.py
│       │
│       ├── scripts/                  # Deterministic replacements for LLM agents
│       │   ├── canonical-digest.py
│       │   ├── compliance-check.py
│       │   ├── copy-diff.py
│       │   ├── publish-reconciliation.py
│       │   ├── scan-draft.py
│       │   └── temperature-scoring.py
│       │
│       ├── data/                     # SQLite + query utilities
│       │   ├── db-init.py
│       │   ├── db-query.py
│       │   └── monthly-learnings.py
│       │
│
│       ├── onboarding/               # First-run setup
│       │   ├── setup-flow.md
│       │   ├── archetypes.md
│       │   ├── guides/               # Per-integration setup
│       │   └── validators/           # Live connection tests
│       │
│       └── agent-pipeline/           # Morning routine agents
│           ├── BUS-PROTOCOL.md       # Bus envelope, naming, validation, versioning
│           ├── orchestrator-design.md
│           ├── README.md
│           ├── schemas/              # JSON Schema files for bus contracts (18 files)
│           │   ├── _bus-envelope.schema.json
│           │   └── <bus-file>.schema.json
│           ├── agents/               # Agent prompt files (52+)
│           │   ├── _auto-fail-checklist.md
│           │   ├── _cadence-config.md
│           │   ├── _scoring-config.md
│           │   ├── step-orchestrator.md
│           │   └── [00-10]-*.md      # Phase agents
│           ├── bus/                   # Inter-agent JSON (per date)
│           │   └── YYYY-MM-DD/
│           │       └── *.json
│           └── templates/            # Reusable output structures
│               ├── content/
│               ├── debrief/
│               ├── deck/
│               └── outreach/
```

## Placement Rules

**New rules file?** -> `.claude/rules/<name>.md` with frontmatter
**New skill?** -> `plugins/<group>/skills/<name>/SKILL.md` (groups: kipi-core, kipi-ops, kipi-design)
**New agent?** -> `q-system/.q-system/agent-pipeline/agents/<phase>-<name>.md`
**New Python harness?** -> `q-system/.q-system/scripts/<name>.py` (if in scripts/) or `q-system/.q-system/<name>.py` (if top-level harness)
**New canonical file?** -> `q-system/canonical/<name>.md`
**New marketing template?** -> `q-system/marketing/templates/<name>.md`
**New onboarding guide?** -> `q-system/.q-system/onboarding/guides/connect-<tool>.md`

## Naming Conventions

| Type | Convention | Example |
|------|-----------|---------|
| Rules | kebab-case.md | `anti-misclassification.md` |
| Skills | kebab-case directory | `plugins/kipi-core/skills/founder-voice/` |
| Agents | `NN-kebab-name.md` | `05-engagement-hitlist.md` |
| Config agents | `_kebab-name.md` | `_cadence-config.md` |
| Python scripts | snake_case or kebab-case.py | `canonical-digest.py` |
| Shell scripts | kebab-case.sh | `session-context.sh` |
| Python scripts | kebab-case.py | `log-step.py` |
| Bus files | kebab-case.json | `linkedin-posts.json` |
| Output files | `type-YYYY-MM-DD.ext` | `morning-log-2026-04-02.json` |

## QROOT Resolution

Scripts at different depths must resolve QROOT differently:
- `q-system/.q-system/*.py` -> `os.path.join(dirname, "..")` = `q-system/`
- `q-system/.q-system/scripts/*.py` -> `os.path.join(dirname, "..", "..")` = `q-system/`
- `q-system/.q-system/data/*.py` -> `os.path.join(dirname, "..", "..")` = `q-system/`

**All scripts MUST resolve QROOT to `q-system/` (the directory containing canonical/, my-project/, memory/).**

## Forbidden Patterns

- Never create files outside the tree above without founder approval
- Never create nested `.q-system/.q-system/` paths (shadow directories)
- `.claude/agents/` is for Claude Code agent definitions (model/tool isolation). Pipeline agent prompts stay in `.q-system/agent-pipeline/agents/`
- Never put skills in `.claude/skills/` (use `plugins/<group>/skills/` instead)
- Never put secrets in committed files (use `${VAR}` references)
- Never create output files in `q-system/` root (use `output/`)
- Never modify `canonical/` files without council check (see auto-detection rules)
