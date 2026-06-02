# Quick-Plan Mode (ENFORCED)

A lightweight, non-gated planning reflex. The moment the founder has an idea, a
bug, a pasted error, or a task bigger than a one-line change, the first move is
a `plan.md` grounded in this instance's code, conventions, and prior learnings.

This is NOT `prd-os`. `prd-os` is the gated, receipted, Codex-reviewed workflow
for product/system changes. Quick-plan is the fast path for everything in
between: strategy docs, one-off fixes, exploratory ideas, bug triage. No gates,
no receipts, no approval ceremony. The plan is the durable checkpoint that
survives context loss.

## When it fires

- Founder pastes a bug, error, screenshot, transcript, or rough idea.
- A task is more than a literal one-line change AND is not already going through
  `prd-os` (`/prd-start`).
- Founder says "plan this", "figure out how to...", or describes work to be done.

## When it does NOT fire

- One-line / trivial edits (typo, config value, single-line fix). Just do it.
- Anything already inside a `prd-os` or `kipi-dsse` issue flow. That owns its plan.
- Pure conversational questions with no work attached.

## The contract

Before writing the plan, READ prior context first (this is the wiring that makes
each plan better than the last — never skip it):

1. `q-system/memory/` — past learnings, corrections, prior decisions.
2. `q-system/output/plans/` — prior plan files in this instance.
3. `q-system/methodology/anti-hallucination.md` — grounding rules.
4. The relevant code/files for the task (read, do not assume).

Then write `q-system/output/plans/<slug>-<YYYY-MM-DD>.md` containing:

- **What / why** — the problem in one or two lines.
- **Approach** — the chosen path. If three reasonable approaches exist, name them
  and mark the pick (founder's `name-options` rule applies).
- **Files to touch** — explicit paths.
- **Acceptance criteria** — checkbox list. For code: a reproducer or test that
  defines done (founder's verification-loops rule).
- **Patterns to follow** — from this instance's own code/conventions, not generic
  advice.

`q-system/output/plans/` lives under `output/`, which `kipi update` excludes from
sync. Plans stay instance-local; they are not skeleton content.

## Resuming

A plan is a checkpoint. If context is lost, a fresh session reads the plan file
and picks up from the first unchecked acceptance criterion. State that explicitly
when resuming: "Resuming from `<plan path>`, next unchecked item: X."

## Relationship to other rules

- Heavier than this → `prd-os` (gated). Lighter than this → just do the edit.
- `wiring-check.md` still applies when the plan ships code/skills/hooks.
- Output the founder acts on still follows AUDHD executive-function rules.
