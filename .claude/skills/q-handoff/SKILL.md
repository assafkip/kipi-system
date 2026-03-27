# /q-handoff — Session continuity

Generate a context note for the next session. Run before ending a session, when context is running low, or automatically as part of `/q-wrap`.

## Preconditions

Read these files:
1. `q-system/my-project/founder-profile.md`
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
2. Write to `memory/last-handoff.md` with this structure:
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
