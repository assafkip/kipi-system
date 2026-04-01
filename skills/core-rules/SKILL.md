---
description: "Core rules — actionable outputs, positioning guardrails, anti-misclassification"
user-invocable: false
paths:
  - "**/q-system/**"
  - "**/canonical/**"
  - "**/my-project/**"
---

# Core Rules

**Gate check:** Read `{config_dir}/enabled-integrations.md`. If `core-rules` is `false`, SKIP this rule file.

## Every output must be actionable
No dashboards without actions. No scores without drafts. No summaries without next steps. If the founder can't copy-paste it, click it, or check it off, it doesn't belong.

## Anti-misclassification (ENFORCED)
Read the "what we are NOT" list from `{data_dir}/my-project/current-state.md`. If any output resembles a misclassification, STOP and reframe.

## No overclaiming
Only reference capabilities that exist today. Distinguish "works today" from "planned." Reference `{data_dir}/my-project/current-state.md` as source of truth.

## Inter-skill review gates
Before outputting any factual claim about the founder's product:
1. Check against canonical files (current-state.md, talk-tracks.md)
2. If not in canonical: mark `{{UNVALIDATED}}`
3. If contradicts canonical: BLOCK the output

## Team-to-team specificity
When describing value, specify which team produces input and which team receives output. No abstract value claims.

## Preserve ambiguity
If something hasn't been validated, do NOT assert it. Use `{{UNVALIDATED}}` or `{{NEEDS_PROOF}}`.
