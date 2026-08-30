---
description: Memory freshness verification rules for fast/medium/slow decay
paths:
  - "memory/**/*"
  - "q-system/memory/**/*"
---

# Memory Freshness (ENFORCED)

The auto-memory system at `~/.claude/projects/<project>/memory/` stores facts that persist across sessions. Some of those facts decay fast (project state, deadlines, demo status). Others are stable (voice rules, process rules, user facts). The frontmatter `decay` field is authoritative.

## The field

Every memory file frontmatter MAY include:

`decay: fast | medium | slow`

If missing, default to `slow`.

| Value | Meaning | Verification requirement before acting |
|---|---|---|
| `fast` | Time-bound facts that can flip day-to-day (active demos, deadlines, "wait until X", relationship stage in flight) | MUST verify before acting. Either (a) check current state via tool (Notion / PostHog / Gmail / Calendar / file read), or (b) surface the memory to the founder and ask for confirmation. |
| `medium` | Structural facts that drift over weeks (IDs, team roles, cohort structure, integration configs) | SHOULD verify if the action depends on the fact being current. Skip verification if action is informational only. |
| `slow` | Voice rules, process rules, architectural conventions, user facts, feedback patterns | No verification needed. Trust unless explicitly contradicted by founder in current session. |

## When the rule fires

This rule fires when I am about to:
- Recommend an action based on memory content
- Draft messaging that asserts a fact from memory
- Assert current state (where someone is, what's in flight, what the deadline is)
- Make a decision whose correctness depends on memory being current

This rule does NOT fire when I am:
- Reading memory for context only
- Citing memory in a discussion with the founder (where the founder can correct me)
- Loading the MEMORY.md index at session start

## Acting on `fast` memories

Required steps before acting:

1. Read the memory file
2. Identify the time-bound fact (e.g., "Josh said wait until Apr 14")
3. Either verify via current tool OR surface to founder. Pick one. Do not skip.
4. Only after verification (or founder confirmation): act on the memory

If verification fails (tool says the fact is no longer true): update the memory file to reflect new state, then act on the new state. Do not silently override.

## MEMORY.md index marker

Index lines for `fast`-decay memories get a `[fast]` prefix so the freshness risk is visible at session start without reading the full file:

`- [fast] [Josh Flashpoint demo](project_josh-flashpoint-demo.md) - ...`

This lets the model see at a glance which memories require verification.

## Relationship to the system age warning

The harness already injects a passive warning when memory files older than ~24h are read: "This memory is X days old. Verify against current code before asserting as fact."

That warning is age-based and blanket. The `decay` field is content-based and authoritative. When they conflict:
- `slow` + age warning -> trust the memory; the age warning is overcautious for stable rules
- `fast` + no age warning -> still verify; the memory could be stale within a day
- `medium` + age warning -> verify if acting on it
- `fast` + age warning -> definitely verify

In short: `decay` overrides the age warning in both directions.

## Failure modes this rule prevents

1. Acting on a "demo in progress, don't follow up" memory after the demo died
2. Patching a config based on cached IDs that have since changed
3. Drafting outreach based on a relationship stage that advanced in another session

If a memory was written too narrowly and causes a recurring voice mistake, that is a memory-content problem, not a freshness problem. Update the memory body, do not change its decay.

## Deterministic enforcement

A SessionStart hook (`q-system/.q-system/scripts/memory-freshness-check.py`) reads memory frontmatter at every session boot and prints `[FAST]` warnings to context. The model sees the warning whether it remembers this rule file or not. The hook is the enforcement; this file is the spec.

## Relationship to `as_of` and supersession

`decay` says how FAST a fact goes stale. `as_of` (defined in
`memory-confidence.md`, alongside the `status` / `superseded_by` supersession
convention) says WHEN the fact was last actually true. They compose: a
`decay: fast` memory with an `as_of` from three months ago is overdue by its own
declared clock, and `memory-lint.py` reports the `status: current` half of that
without blocking anything.

When verification fails, the instruction above still holds -- update the memory to
reflect new state. If the correction is large enough that the old text is now
WRONG rather than merely out of date, supersede it (`status: superseded` plus
`superseded_by`) instead of overwriting, so the reversal survives. Deletion is
reserved for memories that were never true.
