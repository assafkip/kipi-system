---
description: "Operating modes — CALIBRATE, CREATE, DEBRIEF, PLAN mode definitions and triggers"
user-invocable: false
paths:
  - "**/*"
---

# Operating Modes

**Gate check:** Read `{config_dir}/enabled-integrations.md`. If `operating-modes` is NOT explicitly set to `true`, SKIP this rule file.


This system operates in 4 modes (not stages). The founder switches freely between them.

| Mode | When | Primary Action |
|------|------|----------------|
| **CALIBRATE** | After conversations, feedback, market changes | Update canonical files with new learning |
| **CREATE** | Need outputs (talk tracks, emails, slides) | Generate from canonical memory |
| **DEBRIEF** | After any conversation with prospect/investor/partner | Structured extraction via debrief template |
| **PLAN** | Deciding what to do next | Prioritize actions from relationship + objection data |

DEBRIEF is the highest-priority workflow. The debrief template in `methodology/debrief-template.md` must be used for every `/q-debrief` command.
