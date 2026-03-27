# /q-draft — Ad-hoc output generation

Generate one-off outputs: a specific email, DM, talking points for a meeting, quick reply. Ephemeral — saved to `output/drafts/`, not structured deliverables.

For structured reusable deliverables, use `/q-create` instead.

## Arguments

`/q-draft [type] [audience]`

Types: email, dm, talking-points, reply, comment, intro, follow-up

## Preconditions

Read these files:
1. `q-system/my-project/enabled-integrations.md`
2. `q-system/my-project/founder-profile.md`
3. `q-system/canonical/talk-tracks.md`
4. `q-system/my-project/relationships.md` — if drafting for a specific person, check history

## Integration checks

No external integrations required. Works entirely from local files.

## Process

1. Identify output type, audience, and context from arguments (ask if unclear)
2. Check `.q-system/agent-pipeline/templates/` for a matching template — use `create_from_template` MCP tool if one exists
3. Read relevant canonical files and relationship history for the target person
4. Generate the draft
5. Save to `output/drafts/{date}-{type}-{audience}.md`

## MCP tools used

`create_from_template`

## Output rules

- Apply `founder-voice` skill — this is text another person will read
- Apply `audhd-executive-function` skill if enabled — output should be copy-paste ready
- No overclaiming
- Frame outreach as sharing expertise, not asking for favors (RSD-aware if AUDHD enabled)
