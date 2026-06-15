# Fable-Discipline Auto-Invocation (ENFORCED)

Invoke the `fable-discipline` skill (kipi-core) BEFORE writing or editing code on any
task larger than a one-line change. It encodes the verified-good coding habits
distilled from the Fable 5 model (recon before edit, verify against a copy with a
negative self-test, single-writer chokepoints, scar-anchored why-comments) plus
the consistency rules an independent Codex review showed were applied unevenly.

| Trigger | Action |
|---------|--------|
| Building a feature, fixing a bug, writing a script | Read fable-discipline SKILL.md, then follow its checklist |
| Writing or editing tests | Same. The fable-discipline-lint hook also blocks tests that touch a live data path |
| Hardening a data path, schema, or migration | Same. Single-writer + verify-against-a-copy rules apply |

**Gate check (skip the skill for):**
- One-line config/value tweaks, typo fixes, formatting
- Pure content/docs (those go through founder-voice, not fable-discipline)
- Reading or searching only (no edit)

**Relationship to other rules:**
- `coding-standards.md` is the static style baseline. fable-discipline is the
  procedure layer on top of it.
- `rca-mode.md` is the diagnostic mirror: fable-discipline is forward (how to build so
  it does not break), rca is backward (why it broke). A "why" comment should cite
  the rca that motivated it.
- `wiring-check.md` still applies when the code being built is a skill/hook/agent.
- The deterministic slice (test isolation) is enforced by the fable-discipline-lint
  hook in the kipi-core plugin; the rest is judgment in the skill.
