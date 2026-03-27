# /q-calibrate — Update canonical files

Enter calibrate mode. Update canonical files based on new information, feedback, market changes, or learnings from conversations.

## Preconditions

Read these files:
1. `q-system/my-project/enabled-integrations.md`
2. `q-system/my-project/founder-profile.md`
3. ALL canonical files in `q-system/canonical/` to understand current state
4. `q-system/my-project/current-state.md`

## Integration checks

No external integrations required. Works entirely from local files.

## Process

1. Ask the founder: "What changed? New feedback, market shift, positioning update, or competitive intel?"
2. Identify which canonical files need updating based on the input
3. Show the CURRENT state of the relevant section before proposing changes
4. Propose specific edits with clear before/after
5. Apply changes after founder confirms
6. Log the decision to `canonical/decisions.md` with origin tag:
   - `[USER-DIRECTED]` if founder specified the change
   - `[CLAUDE-RECOMMENDED -> APPROVED]` if Claude suggested and founder approved
   - `[CLAUDE-RECOMMENDED -> MODIFIED]` if founder changed the suggestion
7. Update `my-project/progress.md` with calibration note

## Routing guide

| Input type | Route to |
|-----------|----------|
| New objection heard | `canonical/objections.md` |
| Language that resonated | `canonical/talk-tracks.md` |
| Competitive intel | `my-project/competitive-landscape.md` |
| Market signal / buyer language | `canonical/market-intelligence.md` |
| What we learned works/doesn't | `canonical/discovery.md` |
| Pricing feedback | `canonical/pricing-framework.md` |
| Product capability change | `my-project/current-state.md` |

## Output rules

- Never assert unvalidated claims — mark with `{{UNVALIDATED}}`
- Preserve ambiguity explicitly
- Anti-misclassification check: if any update drifts toward "what we are NOT" list, STOP and flag
