---
description: "File authority — canonical file routing for positioning, relationships, objections, decisions"
user-invocable: false
paths:
  - "**/*.md"
  - "**/*.json"
---

# File Authority

**Gate check:** Read `{config_dir}/enabled-integrations.md`. If `file-authority` is NOT explicitly set to `true`, SKIP this rule file.


These files are the source of truth. Route new information to the correct file.

- `{data_dir}/my-project/current-state.md` = what works today (NOT vision)
- `{config_dir}/canonical/discovery.md` = what's been asked and answered
- `{config_dir}/canonical/objections.md` = known pushback + responses
- `{config_dir}/canonical/talk-tracks.md` = proven language
- `{data_dir}/my-project/relationships.md` = people + conversation history
- `{data_dir}/my-project/competitive-landscape.md` = substitute buckets
- `{config_dir}/canonical/lead-lifecycle-rules.md` = when to kill/park/re-engage leads (ENFORCED in morning routine + hitlist generation)
- `{config_dir}/canonical/engagement-playbook.md` = social engagement rules + comment strategy
- `{config_dir}/canonical/market-intelligence.md` = buyer language, category signals, competitive intel, narrative validation from external content. Read before generating any marketing content or outreach.
- `{config_dir}/canonical/decisions.md` = strategic decisions with origin tags
