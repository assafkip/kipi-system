---
description: Confidence and provenance fields on auto-memory (the trust axis)
paths:
  - "memory/**/*"
  - "q-system/memory/**/*"
---

# Memory Confidence + Provenance (ENFORCED)

The auto-memory system at `~/.claude/projects/<project>/memory/` stores facts that
persist across sessions. `decay` (see `memory-freshness.md`) tracks the TIME axis:
how fast a fact goes stale. This rule adds the TRUST axis: how sure the fact is and
where it came from. Without it, a founder-stated fact and a model-inferred guess are
byte-indistinguishable at recall, and the model can repeat its own guess back as
established fact.

## The fields

Every memory file frontmatter MAY include two optional top-level fields:

`confidence: 0.0-1.0`
`provenance: explicit_statement | inferred | corrected | validated | observed | imported`

Both are OPTIONAL. Absent = treat as founder-stated/high (the 32 pre-existing files
are unaffected). This mirrors how `decay` is optional and defaults to `slow`.

| Field | Meaning |
|---|---|
| `confidence` | The writer's certainty, 0.0 (pure guess) to 1.0 (verified fact). Below 0.5 surfaces at recall. |
| `provenance` | Where the fact came from. `inferred` and `observed` surface at recall regardless of the confidence number. |

### Provenance values

- `explicit_statement` — the founder said it directly.
- `inferred` — the model deduced it; not stated. (Surfaces at recall.)
- `corrected` — a prior memory was wrong and this replaces it.
- `validated` — checked against a tool/source (Notion, PostHog, file, etc.).
- `observed` — seen in behavior/data, not stated. (Surfaces at recall.)
- `imported` — brought in from another system or document.

## Write side (deterministic gate)

`q-system/.q-system/scripts/memory-confidence-validator.py` (PostToolUse Edit|Write)
self-scopes to auto-memory files and BLOCKS (exit 2) a write whose `confidence` is
out of `[0.0, 1.0]` or whose `provenance` is not in the enum. Absent fields pass.
The rule is the spec; the hook is the enforcement (no-prompt-only rule).

## Recall side (surfacing)

`q-system/.q-system/scripts/memory-confidence-surface.py` (SessionStart) prints a
`[LOW-CONF]` warning block listing memories with `confidence < 0.5` OR `provenance`
in {`inferred`, `observed`}. Treat those skeptically: verify before asserting their
content as fact (tool-check or ask the founder), the same discipline `decay: fast`
requires.

## MEMORY.md index marker

So the trust signal reaches the index reader too (not only SessionStart and direct
Reads), index lines for low-trust memories get a `[low-conf]` prefix, mirroring the
`[fast]` marker:

`- [low-conf] [Some inferred fact](project_some-fact.md) - ...`

This makes the trust risk visible at a glance without opening the file. A memory can
carry both markers (`[fast] [low-conf]`).

## When this rule fires

Same trigger as freshness: when about to recommend an action, draft a claim, or
assert current state based on a memory. A `[LOW-CONF]` memory gets verified before
it drives an action. It does NOT fire when reading for context only or discussing
with the founder (who can correct in-session).

## Relationship to decay

`decay` and `confidence` are orthogonal. `decay` = will this go stale (time).
`confidence` = was this ever solid (trust). A `slow` + low-confidence memory is a
stable guess; a `fast` + high-confidence memory is a verified fact with a short
shelf life. Both markers can apply to one memory.
