# kipi-core skills

One directory per skill, each with a `SKILL.md`. Skills generate; hooks
validate. A skill with deterministic rules ships a paired hook
(`.claude/rules/skill-hook-pairing.md`); a skill whose rules need judgment
gets a trigger-eval fixture instead.

## Changelog convention

A skill file carries its own history at the bottom, under one heading, so a
friction fix lands with a trace of what changed and when (plan item 2l of the
morning-brief overhaul, 2026-09-01). Without it, the weekly friction pass
proposes a change and nothing records that it happened.

The shape, checked by `q-system/.q-system/tests/test_skill_changelog.py`:

```markdown
## Changelog

- 2026-09-01: created. Verdicts cite a lessons path or a named file.
```

Rules:

- One `## Changelog` heading per file, last section in the file.
- One line per change: `- YYYY-MM-DD: <what changed, one sentence>`.
- Newest first. The test asserts the dates are non-increasing.
- Applies to every skill created from 2026-09-01 on (`improve` is the first).
  An existing skill adopts the section the next time it is edited for its own
  reasons; this convention never bulk-edits existing skills (Codex finding-3 on
  prd-morning-brief-learns: a wildcard over `*/SKILL.md` gave one issue
  fleet-wide authority over every skill for an unrelated header).
