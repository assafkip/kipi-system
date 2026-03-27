# /q-market-create — Generate marketing content

Generate marketing content for any channel. Reads canonical files, applies templates, runs guardrails.

## Setup guard

**FIRST:** Read `~/.config/kipi/founder-profile.md`. If it contains `{{SETUP_NEEDED}}`, STOP and tell the user:

> This system hasn't been configured yet. Run `/q-setup` first to set up your profile, integrations, and canonical files.

Do not proceed with any other steps.

## Path resolution

Read the `kipi://paths` MCP resource to get resolved directories. Key directories:
- **Config** (`~/.config/kipi/`): founder-profile, enabled-integrations, canonical/, voice/, marketing/
- **Data** (`~/.local/share/kipi/`): my-project/, memory/
- **State** (`~/.local/state/kipi/`): output/, bus/
- **Repo**: system code (agents, templates, steps) stays in the git repo

## Arguments

`/q-market-create [type] [topic]`

Types: linkedin, x, medium, one-pager, outreach, deck, follow-up

## Preconditions

Read these files:
1. `~/.config/kipi/enabled-integrations.md`
2. `~/.config/kipi/founder-profile.md`
3. `~/.config/kipi/canonical/talk-tracks.md`
4. `~/.config/kipi/canonical/market-intelligence.md`
5. `~/.config/kipi/marketing/content-themes.md` — current theme rotation
6. `~/.config/kipi/marketing/brand-voice.md` — per-channel voice rules
7. `~/.config/kipi/marketing/content-guardrails.md` — validation rules
8. `q-system/marketing/assets/` — reusable boilerplate, bios, stats, proof points

## Integration checks

| Integration | Used for | If unavailable |
|------------|----------|----------------|
| Gamma | Deck and one-pager generation | Output markdown/slide text instead |
| NotebookLM | Research-grounded content | Skip research grounding, use canonical files only |

## Process

1. Identify content type and topic from arguments (ask if unclear)
2. Check current theme rotation in content-themes.md — align if possible
3. Read relevant canonical files and marketing assets
4. Generate content following brand-voice.md rules for the target channel
5. Run content through content-guardrails.md validation
6. For decks/one-pagers with Gamma: generate via Gamma MCP
7. Output the content ready for review or publishing

## Output rules

- Apply `founder-voice` skill — mandatory for all marketing content
- Apply `audhd-executive-function` skill if enabled
- Run anti-AI detection patterns from founder-voice skill
- Anti-misclassification guardrails: never use language from "what we are NOT" list
- No overclaiming — only reference current capabilities
- Mark unvalidated claims with `{{UNVALIDATED}}`
