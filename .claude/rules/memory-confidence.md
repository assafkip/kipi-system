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

## Supersession and `as_of` (the correction axis)

`decay` tracks TIME, `confidence` tracks TRUST. This adds the CORRECTION axis:
what happens to a memory once it turns out to be wrong.

The old convention was "delete memories that turn out to be wrong". Deleting the
correction destroys the most useful thing in the file: that this belief was once
held, and what replaced it. A reader who only sees the successor cannot tell a
fact that was always true from one that reversed.

So a corrected memory is SUPERSEDED, not deleted:

```yaml
---
name: some-fact
status: superseded
superseded_by: some-fact-v2
as_of: 2026-05-11
---
```

and the successor points back:

```yaml
---
name: some-fact-v2
status: current
supersedes: some-fact
as_of: 2026-08-19
---
```

| Field | Meaning |
|---|---|
| `status` | `current` or `superseded`. Absent means `current`. |
| `superseded_by` | The successor's `name:` slug. REQUIRED when `status: superseded`. |
| `supersedes` | The predecessor's `name:` slug, on the successor. |
| `as_of` | `YYYY-MM-DD`: when the claim was actually TRUE. |

`as_of` is not the write date and it is not the file's mtime. A memory rewritten
for formatting today can still be as-of a fact last verified in May. Staleness is
judged against `as_of`, so using the write date would make every touched file look
freshly verified when nothing was re-checked.

### Deletion is now narrow

Delete only a memory that was NEVER true: a mis-file, a test artifact, something
recorded about the wrong person or project. There is no successor to point at and
no correction to preserve. Everything else is superseded. A `superseded` memory
with no `superseded_by` is refused at the write, because a dead end tells the
reader the memory is wrong and nothing about what replaced it, which is strictly
worse than the deletion this replaces.

### Grandfathering

Both fields are OPTIONAL and absence is legal, exactly like `decay` and
`confidence`. The pre-existing corpus carries neither. A convention that made ~70
files invalid on day one would be red on its whole population from the first run,
which is how a gate gets switched off and then protects nothing. The linter
reports the gap; nothing blocks.

### The two executables

- **Shape, at write time:** `memory-confidence-validator.py` (the same PostToolUse
  chokepoint that owns `confidence` and `provenance`) BLOCKS a `status` outside the
  enum, an `as_of` that is not a real `YYYY-MM-DD` date, a `superseded` with no
  `superseded_by`, and an empty link field. Absent fields pass.
- **Graph, across the corpus:** `q-system/.q-system/scripts/memory-lint.py` sweeps
  a memory directory and REPORTS dangling `[[wiki-links]]`, `superseded_by` /
  `supersedes` that resolve to no memory, MEMORY.md index lines with no backing
  file, memory files with no index line, duplicate `name:` slugs, and
  `status: current` memories whose `as_of` is older than N months (default 6).
  It is report-only, it never auto-fixes, and it exits 0 in advisory mode; the
  `--strict` flag exits 1 on structural findings for CI-style use. Wired as an
  advisory Gate 1.2b in `validate-separation.py` (`kipi check`), warn-only.

Cross-file checks live in the sweep and NOT in the hook on purpose: at write time
the successor may not exist yet, so a hook enforcing link resolution would refuse a
correct pair of edits for arriving in the wrong order.

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

## One vocabulary, one table (2026-07-28)

The `provenance` enum is NOT defined here in prose. It lives in
`q-system/.q-system/scripts/provenance-vocabulary.json` and is read at runtime by
BOTH `memory-confidence-validator.py` and `handoff-provenance-lint.py`, so a value
added there reaches both. That file also ranks the forms, so a line carrying two
markers has a defined winner and the pair gets reported rather than silently
resolved.

Scar: this enum was hardcoded in the validator, and three days later
`handoff-provenance-lint.py` shipped a DIFFERENT vocabulary for the same idea.
Nothing collided, because their file scopes differ, so the drift was invisible
rather than absent. See `.claude/rules/evidence-ledger.md` and PRD
prd-deterministic-reading-2026-07-28 Part C.
