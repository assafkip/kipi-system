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

The `rca-notify` hook (PostToolUse on Bash) watches command results and taps you
to open an RCA when a test or run fails (non-zero exit, or FAIL / BLOCKED /
Traceback in the output). The `rca-lint` hook validates every RCA doc on write.
Both ship with the rca skill. The model decides; the hooks make sure the moment
is not missed and the structure holds.

## What the skill enforces

Surface vs structural root cause, multi-factor with cause-type tags,
evidence-backed verification ("ran X, got Y"), checkbox action items with
owners, and blameless phrasing. Trivial bugs fixed in the same breath that never
escaped a gate do not need an RCA.

## Relationship to other rules

- `quick-plan.md` is forward (how to build). RCA is its diagnostic mirror.
- `prd-os` — an RCA's structural fix often becomes a PRD.
- Output the founder acts on still follows AUDHD executive-function rules.
