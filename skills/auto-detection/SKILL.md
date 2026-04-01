---
description: "Auto-detection triggers for conversation transcripts and social post screenshots"
user-invocable: false
paths:
  - "**/*"
---

# Auto-Detection Rules

**Gate check:** Read `{config_dir}/enabled-integrations.md`. If `auto-detection` is NOT explicitly set to `true`, SKIP this rule file.


These triggers fire automatically — no command needed.

## Conversation transcript/summary pasted

When the founder pastes or uploads a conversation transcript, meeting notes, voice conversation summary, or chat log:
1. Auto-detect the person's name, role, and company from the content
2. Immediately run the full `/q-debrief` workflow: debrief template, all 12 strategic implications lenses, canonical routing (including market-intelligence.md, competitive-landscape.md, network expansion), and Notion logging
3. For practitioner/buyer conversations: run the Design Partner Conversion section. The debrief is not complete until there is a copy-paste message the founder can send to convert the conversation into a design partner trial.
4. If the person can't be identified, ask once, then proceed.

## Social post screenshot shared

Handled by `/q-engage` reactive mode. Evaluates post content for market intelligence first (6 lenses), then generates 1 best comment (not 2-3 options). System picks the style. Founder can ask for alternatives if needed.
