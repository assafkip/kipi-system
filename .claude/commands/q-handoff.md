Session handoff. Generate context note for the next session.

Read `.claude/skills/session-handoff/SKILL.md` in the q-system directory for the full spec.

Save to `memory/last-handoff.md`. Includes: what happened this session, in-progress work, decisions made, files modified, blocked items, suggested next action.

Trigger: user says "done"/"stopping"/"wrapping up", context running low, after `/q-wrap`, before context compaction.
