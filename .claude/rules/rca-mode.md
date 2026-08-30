# RCA Mode (ENFORCED)

Root-cause analysis is handled by the **rca skill** in the `kipi-core` plugin.
This rule exists to make the trigger always-on; the skill carries the method.

## When to write an RCA

- A defect shipped and was caught after the fact (by a human or a gate).
- A run came back BLOCKED, or a deliverable failed validation.
- A bug recurs after a prior fix (the prior fix treated a symptom).
- The founder says "rca this", "root cause this", "postmortem this", or
  "why did this break".

When any of these happen, invoke the rca skill and write the analysis to
`q-system/output/rca/rca-<slug>-<YYYY-MM-DD>.md`. The skill's
`references/rca-template.md` is the canonical structure.

## The deterministic part

Two executables hold the label above, both wired PostToolUse in the plugin's
`hooks.json`. `plugins/kipi-core/skills/rca/scripts/rca-notify.py` (matcher Bash)
TAPS you on a failed run -- non-zero exit, or FAIL / BLOCKED / Traceback -- and
always exits 0, so it prompts and never blocks. Only
`plugins/kipi-core/skills/rca/scripts/rca-lint.py` (Edit|Write) blocks: exit 2 on
a malformed RCA or premortem doc. Neither gates the trigger; that is a model call.

## What the skill enforces

Surface vs structural root cause, multi-factor cause-type tags, evidence-backed
verification ("ran X, got Y"), checkbox action items with owners, and blameless
phrasing. A trivial bug fixed in the same breath, never escaping a gate, needs none.

## Relationship to other rules

- `quick-plan.md` is forward (how to build). RCA is its diagnostic mirror.
- `prd-os` — an RCA's structural fix often becomes a PRD.
- Output the founder acts on still follows AUDHD executive-function rules.
