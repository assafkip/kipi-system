---
id: skill-trigger-eval
title: Skill-trigger eval harness + fixtures for the 4 high-stakes skills, on-demand claude -p from real repo root (H1), plus the skill-hook-pairing + wiring-check documentation (H13); required_check is OFFLINE (claude -p mocked)
status: closed
priority: p1
parent_prd: prd-brief-adopt-items-2026-06-20
allowed_files:
  - q-system/.q-system/scripts/skill-trigger-eval.py
  - q-system/.q-system/skill-evals/**
  - .claude/rules/skill-hook-pairing.md
  - .claude/rules/wiring-check.md
  - q-system/.q-system/scripts/test/test-skill-trigger-eval.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-skill-trigger-eval.sh
required_reviews: []
bypass_check: "bash q-system/.q-system/scripts/test/test-skill-trigger-eval.sh"
---
<!-- generated-by: prd_split.py prd=prd-brief-adopt-items-2026-06-20 finding=finding-3 at=2026-06-20T01:42:14Z -->

# Skill-trigger eval harness + fixtures for the 4 high-stakes skills, on-demand claude -p from real repo root (H1), plus the skill-hook-pairing + wiring-check documentation (H13); required_check is OFFLINE (claude -p mocked)

## Context

Parent PRD: `.prd-os/prds/prd-brief-adopt-items-2026-06-20.md`

## Acceptance

- [ ] `q-system/.q-system/scripts/skill-trigger-eval.py`: reads fixtures from `q-system/.q-system/skill-evals/<skill>.json` (dir overridable via `SKILL_EVAL_DIR`), runs `claude -p` (command overridable via `SKILL_EVAL_CLAUDE_CMD`) from the REPO ROOT per case so the `.claude/rules` auto-invoke path loads, and computes a per-skill `trigger_rate` (the fixture's `fired_marker` appearing in the output == fired; compared to each case's `should_trigger`). On-demand, NOT a hook. Rejects malformed fixtures (missing skill/cases/prompt/should_trigger). Prints an ADVISORY note that the live rate is noisy and not a pass/fail gate.
- [ ] Fixture sets under `q-system/.q-system/skill-evals/` for the 4 high-stakes skills (founder-voice, audhd-executive-function, rca, fable-discipline), 4-6 cases each mixing should_trigger true/false.
- [ ] H13 wiring: `skill-hook-pairing.md` documents the trigger-eval pairing (advisory/periodic, never a blocking exit-2 hook); `wiring-check.md` gets a bullet pointing at the fixtures.
- [ ] `test-skill-trigger-eval.sh`: OFFLINE -- a temp fixture dir + a mock claude command (via the env overrides) prove the harness computes the correct trigger_rate and rejects a malformed fixture. NO live `claude -p` call.
- [ ] required_check passes.
