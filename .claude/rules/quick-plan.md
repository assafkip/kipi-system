# Quick-Plan Mode (ENFORCED)

A lightweight, non-gated planning reflex: the moment the founder has an idea, a bug, a pasted error, or a task bigger than a one-line change, the first move is a `plan.md` grounded in this instance's code, conventions, and prior learnings. NOT `prd-os` (that is the gated, receipted, Codex-reviewed path); this is the fast path for strategy docs, one-off fixes, exploratory ideas, bug triage. The plan is the durable checkpoint that survives context loss.

**Scope of (ENFORCED) above: the plan's SHAPE, held by `q-system/.q-system/scripts/plan-lint.py`.** Wired PostToolUse on Edit/Write in BOTH `.claude/settings.json` and `settings-template.json`, so `kipi update` ships the switch and not only the script. It exits 2 on a plan written to `q-system/output/plans/` that lacks the dated `<slug>-<YYYY-MM-DD>.md` filename or any of the five sections named below, and fast-exits on every other path. Read its silence narrowly: it checks that those sections EXIST, never that their content is true, grounded or complete. Plans dated before 2026-08-21 are grandfathered (39 of the 57 plans on disk were short a section, and a gate red on its own population gets switched off), and `plan-lint-skip` is the explicit per-file bypass. Whether this reflex FIRES at all stays a model decision that no hook observes -- a PostToolUse hook can inspect a plan that was written and is structurally blind to one that was skipped. Pinned by `test-quick-plan-rule-wired.sh` (the labelling and the wiring) and `test_plan_lint.py` (the engine).

## Fires / does not fire

- **Fires:** founder pastes a bug/error/screenshot/transcript/idea; a task is more than a one-line change and not already in `prd-os`/`kipi-dsse`; founder says "plan this" / "figure out how to…".
- **Does not:** one-line/trivial edits (just do it); anything already inside a prd-os/kipi-dsse issue (that owns its plan); pure conversational questions.

## The contract

First READ prior context (the wiring that makes each plan better than the last — never skip): (1) `q-system/memory/`, (2) `q-system/output/plans/`, (3) `q-system/methodology/anti-hallucination.md`, (4) the relevant code/files (read, do not assume).

Then write `q-system/output/plans/<slug>-<YYYY-MM-DD>.md` with: **What/why** (1-2 lines); **Approach** (the pick; if three reasonable approaches exist, name them and mark the pick — `name-options` rule); **Files to touch** (explicit paths); **Acceptance criteria** (checkboxes; for code, a reproducer/test that defines done — verification-loops rule); **Patterns to follow** (from this instance's own code, not generic advice). `output/plans/` is excluded from `kipi update` sync — plans stay instance-local.

## Discipline

- **Plan for the plan (deep work):** for multi-input synthesis do NOT ask for the deliverable directly (it makes the model cut corners). First write a plan for HOW you will mine each input and assemble it, with acceptance criteria; the deliverable is the next, separate step.
- **Reading:** the plan is the agent's homework, not the founder's reading assignment. Surface a one-line title + offer eli5/TLDR/"why this approach" on demand; full body stays in the file (AUDHD rule).
- **Resuming:** a plan is a checkpoint. On context loss, read the plan and resume from the first unchecked criterion — state it: "Resuming from `<path>`, next unchecked: X."

## Relationship

Heavier → `prd-os` (gated). Lighter → just do the edit. `wiring-check.md` applies when a plan ships code/skills/hooks. Founder-facing output follows AUDHD executive-function rules.
