# /q-handoff — Session continuity

Generate a context note for the next session. Run before ending a session, when context is running low, or automatically as part of `/q-wrap`.

## Setup guard

**FIRST:** Call `kipi_paths_info` MCP tool to get resolved directory paths. Use these paths for all file operations below.

Read `{config_dir}/founder-profile.md`. If it contains `{{SETUP_NEEDED}}`, STOP and tell the user:

> This system hasn't been configured yet. Run `/q-setup` first to set up your profile, integrations, and canonical files.

Do not proceed with any other steps.

## Preconditions

Read these files:
1. `{config_dir}/founder-profile.md`
2. Current session context (what was worked on, decisions made, files changed)

## Integration checks

No external integrations required.

## Process

1. Summarize the current session:
   - What was worked on
   - Decisions made (with origin tags)
   - Files created or modified
   - What's pending / in-progress
   - Any blockers or open questions
2. Write to `{data_dir}/memory/last-handoff.md` with this structure:
   ```
   # Session Handoff - {date}

   ## Completed
   - [what got done]

   ## In Progress
   - [what's mid-stream]

   ## Pending
   - [what needs attention next]

   ## Blockers
   - [anything stuck]

   ## Context for Next Session
   - [key decisions, state changes, anything the next session needs to know]
   ```
3. Confirm to the founder: "Handoff saved. Next session will pick up from here."

## Output rules

- Concise — this is a reference doc, not a narrative
- Include file paths for anything in progress
- Flag any time-sensitive items
