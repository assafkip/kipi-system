# /q-calibrate — Update canonical files

Enter calibrate mode. Update canonical files based on new information, feedback, market changes, or learnings from conversations.

## Setup guard

**FIRST:** Call `kipi_paths_info` MCP tool to get resolved directory paths. Use these paths for all file operations below.

Read `{config_dir}/founder-profile.md`. If it contains `{{SETUP_NEEDED}}`, STOP and tell the user:

> This system hasn't been configured yet. Run `/q-setup` first to set up your profile, integrations, and canonical files.

Do not proceed with any other steps.

## Preconditions

Read these files:
1. `{config_dir}/enabled-integrations.md`
2. `{config_dir}/founder-profile.md`
3. ALL canonical files in `{config_dir}/canonical/` to understand current state
4. `{data_dir}/my-project/current-state.md`

## Integration checks

No external integrations required. Works entirely from local files.

## Process

1. Ask the founder: "What changed? New feedback, market shift, positioning update, or competitive intel?"
2. Identify which canonical files need updating based on the input
3. Show the CURRENT state of the relevant section before proposing changes
4. Propose specific edits with clear before/after
5. Apply changes after founder confirms
6. Log the decision to `{config_dir}/canonical/decisions.md` with origin tag:
   - `[USER-DIRECTED]` if founder specified the change
   - `[CLAUDE-RECOMMENDED -> APPROVED]` if Claude suggested and founder approved
   - `[CLAUDE-RECOMMENDED -> MODIFIED]` if founder changed the suggestion
7. Update `{data_dir}/my-project/progress.md` with calibration note

## Routing guide

| Input type | Route to |
|-----------|----------|
| New objection heard | `{config_dir}/canonical/objections.md` |
| Language that resonated | `{config_dir}/canonical/talk-tracks.md` |
| Competitive intel | `{data_dir}/my-project/competitive-landscape.md` |
| Market signal / buyer language | `{config_dir}/canonical/market-intelligence.md` |
| What we learned works/doesn't | `{config_dir}/canonical/discovery.md` |
| Pricing feedback | `{config_dir}/canonical/pricing-framework.md` |
| Product capability change | `{data_dir}/my-project/current-state.md` |

## Output rules

- Never assert unvalidated claims — mark with `{{UNVALIDATED}}`
- Preserve ambiguity explicitly
- Anti-misclassification check: if any update drifts toward "what we are NOT" list, STOP and flag
