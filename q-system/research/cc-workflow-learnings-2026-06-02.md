# "Every Claude Code Hack I Know" (Mar 2026) — Learnings for kipi-system

Date: 2026-06-02
Source: viral article by mvanhorn (author of `last30days`, #3 contributor to Compound Engineering plugin).
Lens: what transfers to kipi-system, filtered for self-promo and personal-workflow noise.

## Thesis (stripped of self-promo)

Plan-first beats code-first. The `plan.md` is the durable checkpoint that survives context loss — a fresh session resumes from it. Everything else in the article is tooling around that one idea.

## Already covered in kipi-system (no action)

- **Research-before-plan** → `deep-research` + `last30days` (the article uses last30days, already installed).
- **Parallel agent fan-out** → `Workflow` + agent pipeline.
- **Codex fallback when tokens run low** → `codex` plugin (rescue/setup).
- **Meeting transcript -> plan** → `founder-debrief` + auto-detection rule on pasted transcripts.
- **Hooks everywhere** → core architecture (skill-hook pairing rule).

## 3 patterns worth stealing

1. **plan.md as a lightweight universal checkpoint.** `prd-os` is the gated/heavy version (product work). Missing: a non-gated "quick plan" mode for the in-between (strategy docs, one-off fixes), grounded in codebase + conventions + prior plans, resumable from a fresh session.
2. **A `solutions/` folder the planner auto-searches.** His planner reads `docs/solutions/` for past-bug learnings before planning. kipi-system has `memory/` + `methodology/anti-hallucination.md`, but the planner does not auto-grep prior solutions. Wiring idea: planner reads prior debriefs/solutions before drafting.
3. **Stop-hook sound for parallel sessions.** `afplay` on the `Stop` hook so you know which of N windows finished. ~4-line config add.

## The one setting that would BREAK our model — do not adopt

He pushes `bypassPermissions` + `skipDangerousModePermissionPrompt: true` and brags the AI "tried to stop him." That is the exact inversion of our NON-NEGOTIABLE destructive-op carve-out (PocketOS volume-deletion incident, hook-level enforcement, `ALLOW_DESTRUCTIVE=1` only in the founder's shell). His workflow has no destructive-op guard; ours does. Copying this disables the safety layer we built on purpose.

## Noise (ignore)

Tesla/FSD dictation, MacBook battery, "wife is mad," Disney play-by-play. Demo theater, not method.
