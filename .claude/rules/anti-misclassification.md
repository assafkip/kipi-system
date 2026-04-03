---
description: Anti-misclassification guardrails for content generation
paths:
  - "q-system/canonical/**"
  - "q-system/marketing/**"
  - "q-system/output/**"
---

# Anti-Misclassification Guardrails (ENFORCED)

Every project gets misclassified. Enforce the founder's "what we are NOT" list from `my-project/current-state.md`.

**{{YOUR_PRODUCT}} is NOT:**
- {{MISCLASSIFICATION_1}}
- {{MISCLASSIFICATION_2}}
- {{MISCLASSIFICATION_3}}

**{{YOUR_PRODUCT}} IS:**
- {{YOUR_CATEGORY}} (technical category term for analysts/buyers)
- {{YOUR_METAPHOR}} (primary metaphor for investors, non-technical audiences)
- {{CORE_IDENTITY_1}}
- {{CORE_IDENTITY_2}}

**If any output resembles a misclassification from the "what we are NOT" list, STOP and reframe.**

The wedge is **{{YOUR_WEDGE}}** - {{WEDGE_DESCRIPTION}}. {{WEDGE_PROOF_POINT}}.

# "Human-in-seat" Narrative Requirement
- Every workflow must specify: who sees what, where, in which existing tool
- Outputs land in existing tools the user already has
- Never frame the product as "a new console" or "a new UI to learn"

# "Inputs/Outputs per Team" Rule
- When describing value, always specify which team produces input and which team receives output
- Example: "{{TEAM_A}} completes {{INPUT}} - findings become {{ARTIFACT_TYPE}} - {{TEAM_B}} gets updated {{OUTPUT}} in {{TOOL}}"

# No Overclaiming
- Only reference capabilities that exist in the product today
- Distinguish between "works today (demo-able)" and "planned/claimed"
- Reference `my-project/current-state.md` as the single source of truth
