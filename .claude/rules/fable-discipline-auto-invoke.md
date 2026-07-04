# Fable-Discipline Auto-Invocation (ENFORCED)

Invoke the `fable-discipline` skill — the **execution-discipline layer of the
prd-os plugin** (merged 2026-07-04, one skill, two load paths: `/issue-start`
loads it for PRD/DSSE work; this rule + the quick-plan fast path load it for
everything else) — BEFORE writing or editing code on any task larger than a
one-line change. It encodes the verified-good coding habits distilled from the
Fable 5 model (recon before edit, verify against a copy with a negative
self-test, single-writer chokepoints, scar-anchored why-comments).

| Trigger | Action |
|---------|--------|
| Building a feature, fixing a bug, writing a script | Read the fable-discipline SKILL.md (prd-os plugin), then follow its checklist |
| Writing or editing tests | Same. The fable-discipline-lint hook also blocks tests that touch a live data path |
| Hardening a data path, schema, or migration | Same. Single-writer + verify-against-a-copy rules apply |

**Gate check (skip the skill for):** one-line config/value tweaks, typo fixes,
formatting; pure content/docs (those go through founder-voice); read-only work.

**Relationship to other rules:**
- `coding-standards.md` is the static style baseline; fable-discipline is the
  procedure layer on top. `rca-mode.md` is the diagnostic mirror (forward vs
  backward); a "why" comment cites the rca that motivated it. `wiring-check.md`
  still applies when the code being built is a skill/hook/agent.
- The deterministic slice (test isolation) is enforced by the fable-discipline-lint
  hook in the prd-os plugin's hooks.json; mirror drift by
  `plugins/prd-os/scripts/export-fable-mirror.sh --check`.
