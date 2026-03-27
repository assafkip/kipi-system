# /q-create — Generate structured deliverables

Generate a specific output type for a specific audience. For structured, reusable deliverables — not one-off drafts (use `/q-draft` for those).

## Setup guard

**FIRST:** Call `kipi_paths_info` MCP tool to get resolved directory paths. Use these paths for all file operations below.

Read `{config_dir}/founder-profile.md`. If it contains `{{SETUP_NEEDED}}`, STOP and tell the user:

> This system hasn't been configured yet. Run `/q-setup` first to set up your profile, integrations, and canonical files.

Do not proceed with any other steps.

## Arguments

`/q-create [type] [audience]`

Types: talk-track, email, slide, diagram, memo, deck, one-pager, workflow-pack, outreach-sequence

## Preconditions

Read these files:
1. `{config_dir}/enabled-integrations.md`
2. `{config_dir}/founder-profile.md`
3. `{config_dir}/canonical/talk-tracks.md` — proven language
4. `{config_dir}/canonical/objections.md` — known pushback
5. `{config_dir}/canonical/discovery.md` — validated learnings
6. `{data_dir}/my-project/current-state.md` — what works today (not vision)

## Integration checks

| Integration | Used for | If unavailable |
|------------|----------|----------------|
| Gamma | Deck and one-pager generation | Output slide text/markdown instead |
| NotebookLM | Research-grounded content | Skip research grounding |

## Process

1. Identify the output type and audience from arguments (ask if unclear)
2. Check `.q-system/agent-pipeline/templates/` for a matching template — use `create_from_template` MCP tool if one exists
3. Read relevant canonical files for source material
4. Generate the deliverable
5. Run inter-skill review gate: verify all factual claims against canonical files. Mark unvalidated claims with `{{UNVALIDATED}}`.
6. For decks/one-pagers with Gamma enabled: generate via Gamma MCP
7. Save output to `{state_dir}/output/` with descriptive filename

## MCP tools used

`create_from_template`

## Output rules

- Apply `founder-voice` skill to all text content
- Apply `audhd-executive-function` skill if enabled
- Anti-misclassification guardrails: check output against "what we are NOT" list from current-state.md
- No overclaiming — only reference capabilities that exist today
- Every claim must be backed by canonical files or marked `{{UNVALIDATED}}`
