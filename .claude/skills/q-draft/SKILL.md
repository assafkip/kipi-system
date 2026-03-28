# /q-draft — Ad-hoc output generation

Generate one-off outputs: a specific email, DM, talking points for a meeting, quick reply. Ephemeral — saved to `{state_dir}/output/drafts/`, not structured deliverables.

For structured reusable deliverables, use `/q-create` instead.

## Setup guard

**FIRST:** Read `{config_dir}/founder-profile.md`. If it contains `{{SETUP_NEEDED}}`, STOP and tell the user:

> This system hasn't been configured yet. Run `/q-setup` first to set up your profile, integrations, and canonical files.

Do not proceed with any other steps.

## Path resolution

Read the `kipi://paths` MCP resource to get resolved directories. Key directories:
- **Config** (`{config_dir}`): founder-profile, enabled-integrations, canonical/, voice/, marketing/
- **Data** (`{data_dir}`): my-project/, memory/
- **State** (`{state_dir}`): output/, bus/
- **Repo**: system code (agents, templates, steps) stays in the git repo

## Arguments

`/q-draft [type] [audience]`

Types: email, dm, talking-points, reply, comment, intro, follow-up

## Preconditions

Read these files:
1. `{config_dir}/enabled-integrations.md`
2. `{config_dir}/founder-profile.md`
3. `{config_dir}/canonical/talk-tracks.md`
4. `{data_dir}/my-project/relationships.md` — if drafting for a specific person, check history

## Integration checks

No external integrations required. Works entirely from local files.

## Process

1. Identify output type, audience, and context from arguments (ask if unclear)
2. Check `agent-pipeline/templates/` for a matching template — use `kipi_create_template` MCP tool if one exists
3. **Load the relevant marketing guide** with `kipi_guide(topic)` for the draft type. Examples: `kipi_guide('cold-email')` for outreach, `kipi_guide('social-content')` for social posts, `kipi_guide('copywriting')` for general copy.
4. Read relevant canonical files and relationship history for the target person
5. Generate the draft
5. Save to `{state_dir}/output/drafts/{date}-{type}-{audience}.md`

## MCP tools used

`kipi_create_template`

## Output rules

- Apply `founder-voice` skill — this is text another person will read
- Apply `audhd-executive-function` skill if enabled — output should be copy-paste ready
- No overclaiming
- Frame outreach as sharing expertise, not asking for favors (RSD-aware if AUDHD enabled)
