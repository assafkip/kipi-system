---
name: architecture-review
description: "Surfaces architectural friction in real code — shallow modules, tight coupling, untested seams — and proposes deepening refactors using Ousterhout's deep-module principle (small interface hiding a large implementation). Use when the founder says 'architecture review', 'find shallow modules', 'architectural friction', 'deep module analysis', or asks for refactor recommendations on a directory of code. Scope it to actual code (plugins/, q-system/.q-system/scripts/) — not markdown rules, canonical files, or prose."
---

# Architecture Review Skill

Finds code that is hard to change and proposes a smaller-interface, bigger-
implementation redesign. This is a judgment skill — no paired hook, same
posture as `research-mode` in `skill-hook-pairing.md`.

## Before running

Read `references/deep-module-lens.md`. It is the classification lens the
review applies to every module it looks at — do not improvise a different
one.

## Scope check (do this first)

This lens is for software modules with interfaces: Python/shell scripts,
plugin code, MCP servers. It does NOT fit markdown rules, canonical files, or
prose content — those don't have "interfaces" in the Ousterhout sense. If the
founder names a target that's mostly `.md`, say so and ask them to narrow to
a code directory.

## Process

1. **Explore.** Spawn an `Agent` with `subagent_type: Explore` over the
   target directory. Ask it to walk the code and report, per file/module:
   what it does, its public surface (functions/classes/CLI flags other code
   calls), and its internal complexity. Don't apply the lens yet — just
   gather the shape.
2. **Classify with the lens.** For each module the Explore pass surfaced,
   run the questions in `references/deep-module-lens.md`. Flag only modules
   that are genuinely shallow (interface complexity close to implementation
   complexity) — a small module with a small interface is fine, not a
   finding.
3. **Propose, don't prescribe.** For each real finding, sketch 1-2 concrete
   redesigns using the vocabulary below. State the trade-off of each. Do not
   silently pick one — that's a founder/Sana call, same as `quick-plan.md`'s
   name-options rule.
4. **Write it up, don't file it.** Output goes to
   `q-system/output/plans/architecture-review-<target-slug>-<YYYY-MM-DD>.md`
   (per `quick-plan.md`), never a GitHub issue and never auto-filed to
   `spillover` — spillover is scoped to findings that interrupt an *active*
   PRD/issue's work, and `linear-first.md` already owns where real work gets
   tracked. If a finding is worth acting on, the next step is the founder or
   Sana deciding whether it becomes a Linear issue or a `prd-os` PRD.
5. **No findings is a valid outcome.** Say so plainly if the target directory
   is already reasonably deep. Don't manufacture friction to justify the run.

## Vocabulary discipline

Use: module, interface, depth, seam, adapter, leverage, locality.
Avoid: "component," "service" — too imprecise to carry the deep-module
argument.

## What this is not

Not a bug finder (that's `/code-review`). Not a cleanup pass (that's
`/simplify`). Not gated, receipted work (that's `prd-os`) — this produces a
proposal doc for a human decision, not shipped code.
