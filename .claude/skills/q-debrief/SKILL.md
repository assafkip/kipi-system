# /q-debrief — Post-conversation structured extraction

**Highest-priority workflow.** Process any conversation (prospect, investor, partner, advisor) through the debrief template. Extracts insights, routes to canonical files, creates follow-up actions.

**Auto-trigger:** When the user pastes a conversation transcript, meeting notes, or chat log, run this workflow automatically. No command needed.

## Arguments

`/q-debrief [person]` — optional person name. If not provided, detect from transcript content. If unidentifiable, ask once then proceed.

## Preconditions

Read these files:
1. `q-system/my-project/enabled-integrations.md`
2. `q-system/my-project/founder-profile.md`
3. `q-system/methodology/debrief-template.md` — the structured extraction template. **Use this exactly.**
4. `q-system/canonical/discovery.md` — cross-reference existing knowledge
5. `q-system/canonical/objections.md` — check for new objections
6. `q-system/canonical/talk-tracks.md` — check what language resonated
7. `q-system/canonical/market-intelligence.md` — route market signals
8. `q-system/my-project/current-state.md` — map pain to current capabilities
9. `q-system/my-project/relationships.md` — existing relationship context

## Integration checks

- **Notion:** Optional. If enabled, log interaction to Contacts DB and create follow-up Actions. If not, update `relationships.md` locally.

## Process

1. **Identify the person** — name, role, company from transcript or user input
2. **Run the debrief template** — all sections from `methodology/debrief-template.md`
3. **Apply all 12 strategic implications lenses** (defined in the template)
4. **Route findings to canonical files:**
   - New objections → `canonical/objections.md`
   - Resonant language → `canonical/talk-tracks.md`
   - Market signals → `canonical/market-intelligence.md`
   - Competitive intel → `my-project/competitive-landscape.md`
   - New contacts mentioned → `my-project/relationships.md`
5. **Design Partner Conversion** (MANDATORY for practitioner/buyer conversations):
   - Read `my-project/current-state.md` to map their pain to current capabilities
   - Identify capability gaps honestly
   - Draft a copy-paste message to convert the conversation into a design partner trial
   - Output the message ready to send
6. **Open follow-up loops** via `loop_open` MCP tool for any pending actions
7. **Log to Notion** if enabled — update contact record, create interaction, create follow-up actions
8. **Log decision** to `canonical/decisions.md` with origin tag

## MCP tools used

`loop_open`

## Output rules

- Apply `founder-voice` skill to any drafted messages (follow-ups, design partner conversion)
- Apply `audhd-executive-function` skill if enabled
- Mark any unvalidated claims with `{{UNVALIDATED}}`
- The debrief is NOT complete until there is a concrete next action for every open thread
