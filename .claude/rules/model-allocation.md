# Model Allocation Policy (ENFORCED by validator script)

The deterministic validator is `validate-separation.py` Gate 1.1b — a script run
by `kipi check` that validates every `.claude/agents/*.md` `model:` frontmatter
against the `MODEL_TIERS` / `AGENT_TIER` tables (change those tables together
with this file). This file is the single source of truth for which model tier
owns which work, fleet-wide.

## Tier → task mapping

| Tier | Current ID | Work it owns |
|------|-----------|--------------|
| Haiku | `claude-haiku-4-5` | Data pulls, scrapes, structured extraction, simple writes, gate-keeping (preflight) |
| Sonnet | `claude-sonnet-5` | Analysis, content generation, content review |
| Opus | `claude-opus-4-8` | Synthesis and engagement hitlist only — the two steps where cross-source judgment earns the cost |

## Rules

- A new `.claude/agents/*.md` file picks its tier from the table above and pins
  the current ID for that tier. No other IDs — the validator script rejects
  unknown or deprecated IDs and tier mismatches.
- Model IDs live ONLY in agent frontmatter (and the paired validator tables).
  Prose elsewhere points here instead of restating IDs.
- When Anthropic ships a new generation: update the ID column here, the
  `MODEL_TIERS` allowlist in the validator script, and every agent frontmatter
  in the same change. `kipi check` fails until all three agree.

## Scar

2026-07-01 audit: this policy existed only as prose inside morning-pipeline.md
(duplicated in folder-structure.md and SETUP.md) while agent frontmatters
silently drifted — Haiku pinned 4-5, Opus/Sonnet stuck on 4-6 with 4-8/Sonnet-5
current. No validator script existed to flag it. Hence one rule + one
deterministic checker, not three prose copies.
