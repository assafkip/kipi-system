---
name: improve
description: "Critique an outside idea (a pasted tip, post, transcript or video summary) against what this system already has. Use when the founder pastes something and asks whether to adopt it, or says 'improve', 'should we do this', 'compare this to what we have'. Grounded by scripts/improve_ground.py in the lessons corpora and named files; returns adopt, skip, or already-built, and NEVER decides what to build, sell or publish."
---

# Improve: an outside idea, judged against the system that exists

Plan item 2d of the morning-brief overhaul (Bloom's `improve` pass). The
founder pastes an idea. This skill answers one question: does it change how
the SYSTEM works, and is that change already here?

## The two halves

1. **Deterministic (this skill must run it, never reason from memory):**

   ```bash
   python3 plugins/kipi-core/skills/improve/scripts/improve_ground.py --target <rule|lint|hook|trigger|context|skill|prompt|test|script|job> "<idea in one sentence>"
   ```

   It prints a JSON verdict with `cites` (lessons paths or named files) and a
   `corpora` report saying which lessons directories were read, missing or
   unreadable. Exit 0 for `already-built` / `adopt`, 2 for `skip`.
   Set `KIPI_LESSONS_CORPORA=/path/one:/path/two` to ground against more than
   this instance's corpus; the report names each one either way.

2. **Judgment (the skill):** read what the script cited. Then write the
   critique in this shape:
   - The idea, in one sentence, as a SYSTEM change (a stage, a trigger, a
     rule, a context entry). If it cannot be phrased that way it is roadmap,
     and the verdict is skip regardless of how good the idea is.
   - What already exists: the cited file or lesson, opened, with the line that
     covers it. Not "we have something like that".
   - Verdict: `already-built` (name the file), `adopt` (name the smallest
     change and the check that would prove it), or `skip` (name the reason
     the classifier gave).

## Hard constraint

This skill fixes the system. It never decides the roadmap. An idea about what
to build, sell, price, publish or advise a client returns `skip` from the
script (`roadmap_scope.py`, fail-closed on unknown) and the skill does not
override that with judgment. If the founder wants the product conversation,
that is a conversation, not this skill.

## Do not

- Cite from memory. If the script's `cites` is empty the verdict is not a
  verdict; say so.
- Widen the trigger. This is on-demand only; it never rides the brief or the
  weekly pass.
- Read a corpus the report says is missing. Say it is missing.

## Changelog

- 2026-09-01: created (prd-morning-brief-learns, issue mbl-improve-skill).
  Verdicts cite a lessons path or a named file; corpora contract via
  KIPI_LESSONS_CORPORA; roadmap ideas skip by classifier, never by judgment.
