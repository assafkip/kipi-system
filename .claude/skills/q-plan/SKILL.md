# /q-plan — Review and prioritize actions

Review relationships, objections, proof gaps, and open loops. Propose prioritized next actions based on data, not gut feel.

## Setup guard

**FIRST:** Call `kipi_paths_info` MCP tool to get resolved directory paths. Use these paths for all file operations below.

Read `{config_dir}/founder-profile.md`. If it contains `{{SETUP_NEEDED}}`, STOP and tell the user:

> This system hasn't been configured yet. Run `/q-setup` first to set up your profile, integrations, and canonical files.

Do not proceed with any other steps.

## Preconditions

Read these files:
1. `{config_dir}/enabled-integrations.md`
2. `{config_dir}/founder-profile.md`
3. `{data_dir}/my-project/relationships.md` — all contacts and conversation history
4. `{config_dir}/canonical/objections.md` — known pushback patterns
5. `{config_dir}/canonical/discovery.md` — validated learnings
6. `{data_dir}/my-project/competitive-landscape.md` — substitute landscape
7. `{config_dir}/canonical/lead-lifecycle-rules.md` — when to kill/park/re-engage leads
8. `{data_dir}/my-project/current-state.md` — what's real today

## Integration checks

| Integration | Used for | If unavailable |
|------------|----------|----------------|
| Notion | Pull pipeline data, deal stages | Work from local relationships.md |

## Process

1. Pull open loops via `loop_list` MCP tool — surface what's pending
2. Review all relationships — who's active, cooling, stale
3. Apply lead-lifecycle-rules.md — identify leads to kill, park, or re-engage
4. Cross-reference objections with proof gaps — where are we weakest?
5. Propose prioritized actions:
   - Each action has: who, what, why, estimated effort
   - Sorted by impact, not urgency
   - Include concrete next steps (not abstract "follow up with X")
6. If AUDHD mode enabled: tag each action with energy mode (Quick Win / Deep Focus / People / Admin) and time estimate

## MCP tools used

`loop_list`, `loop_stats`

## Output rules

- Apply `audhd-executive-function` skill if enabled — friction-ordered, copy-paste ready
- Present choices, not commands ("you could..." not "you need to...")
- No pressure language, no shame about stale contacts
- Track effort not outcomes
