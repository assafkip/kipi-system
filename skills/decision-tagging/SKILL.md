---
description: "Decision origin tagging — every decision logged must include USER-DIRECTED or CLAUDE-RECOMMENDED tags"
user-invocable: false
paths:
  - "**/decisions.md"
  - "**/canonical/**"
---

# Decision Origin Tagging (ENFORCED)

**Gate check:** Read `{config_dir}/enabled-integrations.md`. If `decision-tagging` is `false`, SKIP this rule file.


Every decision logged to `{config_dir}/canonical/decisions.md` MUST include an origin tag:

- `[USER-DIRECTED]` — founder explicitly made this decision
- `[CLAUDE-RECOMMENDED -> APPROVED]` — Claude suggested, founder approved
- `[CLAUDE-RECOMMENDED -> MODIFIED]` — Claude suggested, founder changed it
- `[CLAUDE-RECOMMENDED -> REJECTED]` — Claude suggested, founder rejected
- `[SYSTEM-INFERRED]` — Claude made this autonomously based on existing rules

Monthly audit on the 1st: check if >60% are rubber-stamped approvals. Surface in morning briefing if so.
