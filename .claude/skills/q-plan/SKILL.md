# /q-plan — Review and prioritize actions

Review relationships, objections, proof gaps, and open loops. Propose prioritized next actions based on data, not gut feel.

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

## Preconditions

Read these files:
1. `~/.config/kipi/enabled-integrations.md`
2. `~/.config/kipi/founder-profile.md`
3. `~/.local/share/kipi/my-project/relationships.md` — all contacts and conversation history
4. `~/.config/kipi/canonical/objections.md` — known pushback patterns
5. `~/.config/kipi/canonical/discovery.md` — validated learnings
6. `~/.local/share/kipi/my-project/competitive-landscape.md` — substitute landscape
7. `~/.config/kipi/canonical/lead-lifecycle-rules.md` — when to kill/park/re-engage leads
8. `~/.local/share/kipi/my-project/current-state.md` — what's real today

## Integration checks

| Integration | Used for | If unavailable |
|------------|----------|----------------|
| Notion | Pull pipeline data, deal stages | Work from local relationships.md |

## Process

1. Pull open loops via `kipi://loops/open` MCP resource — surface what's pending
2. Review all relationships — who's active, cooling, stale
3. Apply lead-lifecycle-rules.md — identify leads to kill, park, or re-engage
4. Cross-reference objections with proof gaps — where are we weakest?
5. Propose prioritized actions:
   - Each action has: who, what, why, estimated effort
   - Sorted by impact, not urgency
   - Include concrete next steps (not abstract "follow up with X")
6. If AUDHD mode enabled: tag each action with energy mode (Quick Win / Deep Focus / People / Admin) and time estimate

## MCP tools used

`kipi://loops/open` (resource), `kipi://loops/stats` (resource)

## Output rules

- Apply `audhd-executive-function` skill if enabled — friction-ordered, copy-paste ready
- Present choices, not commands ("you could..." not "you need to...")
- No pressure language, no shame about stale contacts
- Track effort not outcomes
