# Memory Lifecycle Rules

The auto-memory system at `~/.claude/projects/<project>/memory/` stores facts that persist across sessions. Some facts decay fast (project state, deadlines, demo status). Others are stable (voice rules, process conventions, user preferences). The `decay` frontmatter field controls how Claude treats each memory.

## Decay field

Every memory file frontmatter MAY include:

`decay: fast | medium | slow`

Default: `slow` (if missing).

| Value | Meaning | Verification before acting |
|---|---|---|
| `fast` | Time-bound facts that flip day-to-day (active demos, deadlines, "wait until X", relationship stages) | MUST verify. Check current state via tool OR surface to user for confirmation. |
| `medium` | Structural facts that drift over weeks (IDs, team roles, configs, integration settings) | SHOULD verify if the action depends on the fact being current. Skip if informational only. |
| `slow` | Stable facts (voice rules, process conventions, architectural decisions, user preferences) | No verification needed. Trust unless contradicted by user in current session. |

## Verification tracking

After verifying a fast or medium-decay memory and confirming it is still true, update the memory file's frontmatter:

```yaml
last_verified: 2026-04-11
verify_count: 3
```

- Set `last_verified` to today's date
- Increment `verify_count` by 1
- This resets the staleness clock and contributes to eventual promotion

If verification fails (the fact is no longer true):
- Update the memory body to reflect the new state
- Update `last_verified` to today
- Do NOT silently override. State what changed.

## When this rule fires

This rule fires when you are about to:
- Recommend an action based on memory content
- Draft messaging that asserts a fact from memory
- Assert current state (where someone is, what's in flight, what the deadline is)
- Make a decision whose correctness depends on memory being current

This rule does NOT fire when you are:
- Reading memory for context only
- Citing memory in a discussion with the user (where they can correct you)
- Loading the MEMORY.md index at session start

## Acting on fast memories

Required steps before acting:

1. Read the memory file
2. Identify the time-bound fact (e.g., "Josh said wait until Apr 14")
3. Either verify via tool OR surface to user. Pick one. Do not skip.
4. Only after verification (or user confirmation): act on the memory

## MEMORY.md index markers

Index lines for fast-decay memories get a `[fast]` prefix:

`- [fast] [Demo status](project_demo-status.md) - Active demo, verified Apr 10`

This makes freshness risk visible at session start without reading each file.

## Auto-archive (deterministic, runs on SessionStart)

The lifecycle hook automatically archives stale memories:
- `fast` decay: archived after 14 days without verification or file update
- `medium` decay: archived after 60 days without verification or file update
- `slow` decay: never auto-archived

Archived memories move to `memory/archived/`. They are removed from MEMORY.md but preserved on disk. Reversible by moving the file back.

## Decay promotion (deterministic, runs on SessionStart)

Memories that have been verified repeatedly get promoted to slower decay:
- `fast` with 3+ verifications and 30+ days old -> promoted to `medium`
- `medium` with 5+ verifications and 60+ days old -> promoted to `slow`

Rationale: if a fact has been true for a month and verified three times, it is no longer fast-decay. It has become established knowledge.

## Frontmatter schema

```yaml
---
name: descriptive memory name
description: one-line description for MEMORY.md index
type: user | feedback | project | reference
decay: fast | medium | slow
last_verified: YYYY-MM-DD
verify_count: N
origin: manual | auto | pitfall_detection
---
```

All fields except `name` and `type` are optional. `decay` defaults to `slow`. `verify_count` defaults to 0.

## Conflict with age warnings

Claude Code may inject age-based warnings ("This memory is X days old"). The `decay` field overrides these:
- `slow` + age warning -> trust the memory (age warning is overcautious for stable rules)
- `fast` + no age warning -> still verify (could be stale within a day)
- `medium` + age warning -> verify if acting on it

`decay` is content-based and authoritative. Age warnings are blanket and passive.

## Failure modes this prevents

1. Acting on "demo in progress, don't follow up" after the demo died
2. Patching a config based on cached IDs that changed
3. Drafting outreach based on a relationship stage that advanced in another session
4. Asserting a deadline that already passed
5. Recommending a tool integration based on credentials that expired

## Pitfall detection (automatic)

The SessionStart hook scans the previous session's transcript for correction patterns. When the user corrects a fact from memory ("that changed", "that's outdated", "not anymore"), the system auto-creates a fast-decay memory recording the correction.

Pitfall memories are tagged `origin: pitfall_detection` and appear as `[FAST]` warnings at the next session start. They instruct you to update the original memory.

When you see a pitfall memory:
1. Read the pitfall to understand what was corrected
2. Read the original memory it references
3. Update the original with the corrected information
4. If the original is fully outdated, archive it
5. Archive the pitfall memory (it served its purpose)

## Memory compilation (user-invoked)

When the user asks to compile or consolidate memories, run `compile-memories.py` to identify clusters of 3+ related memories.

Compilation rules:
- Keep the most recent factual state, not the history of changes
- Preserve decisions and lessons learned
- Drop timestamps and status updates that are no longer relevant
- If facts conflict between memories, keep the most recent one
- Set `decay: slow` and `origin: compiled` on the compiled memory
- Archive (don't delete) the source memories after compilation
- Update MEMORY.md index

Only compile when the user explicitly asks. Never auto-compile.

## Deterministic enforcement

The SessionStart hook reads memory frontmatter and prints `[FAST]` warnings to context. It also runs pitfall detection on the previous session's transcript. The model sees warnings whether it remembers this rule file or not. The hook is the enforcement; this file is the spec.
