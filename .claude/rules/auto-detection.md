---
description: Auto-detection triggers for conversation transcripts, social posts, and council
---

# Auto-Detection Rules (no command needed)

## Conversation transcript/summary pasted
When the founder pastes or uploads a conversation transcript, meeting notes, voice conversation summary, or chat log:
1. Auto-detect the person's name, role, and company from the content
2. Immediately run the full `/q-debrief` workflow: debrief template, all 12 strategic implications lenses, canonical routing, and Notion logging
3. **For practitioner/buyer conversations: run the Design Partner Conversion section.** MANDATORY. Read `my-project/current-state.md` to map pain to capabilities. Output a copy-paste message and create a follow-up Action in Notion.
4. No command needed. The founder should never have to type `/q-debrief` manually.
5. If the person can't be identified, ask once, then proceed.

## Social post screenshot shared
Handled by `/q-engage` reactive mode. Evaluates post content for market intelligence first (6 lenses), then generates 1 best comment. System picks the style.

## Council auto-trigger (no command needed)
The `council` skill fires automatically:

- **During `/q-calibrate`:** Before writing ANY change to a canonical file, run a Quick Council check. If 2+ personas object, surface dissent before writing.
- **During `/q-debrief` with conflicting signals:** Auto-run Quick Council: "Is this new signal or noise?"
- **Design partner feature requests:** If feature doesn't map to current-state.md, auto-run Quick Council: "Build it / Park it / Counter-offer."
- **Competitive moves:** Auto-run Quick Council: "Respond / Ignore / Reposition."

**Rules:**
- Always Quick mode for auto-triggers. Full Debate is founder-initiated only.
- If canonical files contain `{{PLACEHOLDER}}`, skip the council.
- Log every auto-triggered council result to `canonical/decisions.md` with `[COUNCIL-DEBATED]` origin tag.
