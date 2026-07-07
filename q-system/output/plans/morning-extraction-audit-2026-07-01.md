# Morning-pipeline extraction: audit, then fleet-wide incorporation

**Date:** 2026-07-01. Written as a post-/clear handoff prompt. Execute top to bottom.

## Mission

Five mechanisms are wired ONLY into `/q-morning` (verified 2026-07-01 by caller grep). Audit whether the fleet already has each capability under a different name. For the ones genuinely missing: fold into an existing project where it helps, or stand up a repo — either way it must reach the entire fleet. Do not skip the audit and jump to building.

## The five candidates (source paths)

1. **Sycophancy audit** — Phase 6 agent + `q-system/.q-system/sycophancy-harness.py` (independent pi verifier: approved/(approved+modified+rejected)). Invoked only by `.claude/rules/morning-pipeline.md`.
2. **Step-logging + post-run audit** — "if a step isn't logged, it didn't happen" + `q-system/.q-system/audit-morning.py`. Catches jobs that ran but silently skipped steps (launchd-health only catches jobs that died).
3. **Model allocation policy** — Haiku pulls / Sonnet analysis / Opus synthesis-only. Exists only as prose in morning-pipeline.md.
4. **Self-healing retry contract** — targeted fix → re-run failed phase only → 3-attempt cap → environmental (MCP auth/hard-down) failures stop on attempt 1. Encoded only in morning-pipeline.md.
5. **Auto-fail checklist pattern** — `q-system/.q-system/agent-pipeline/agents/_auto-fail-checklist.md`: agents self-check output against enumerated fail conditions before writing.

## Phase 1 — Audit (read-only, then STOP for founder OK)

For each candidate, sweep for equivalent capability under other names. Verdict per item: **EXISTS** (where, and whether the morning copy should be retired to point at it) / **PARTIAL** (what the gap is) / **MISSING**.

Where to look (fan out Explore agents; do not read whole files into main context):
- Skeleton: `plugins/kipi-core` (skills, hooks/hooks.json, scripts), `.claude/rules/*.md`, `q-system/.q-system/scripts/*`, `q-system/lessons/`
- Gated systems: `plugins/prd-os` (gates/receipts), `plugins/kipi-dsse` (required_checks), `plugins/memory-lifecycle`
- Autonomous layer: launchd-health watchdog, `open-loops-heartbeat.sh`, the self-healing/auto-learning canonical docs (commits 2f837d3, d862636), `q-system/output/rca/`
- Instances: `instance-registry.json` for the fleet list; spot-check 2-3 instances (state which + why before reading outside this repo)

Specific likely-overlap checks (don't trust names, check behavior):
- #1 vs `.claude/rules/sycophancy.md` decision-origin tagging, the council skill (dissent surfacing), `q-system/output/skeptic-proposals/`
- #2 vs prd-os receipts, kipi-dsse verified receipts, launchd-health, heartbeat run-logs
- #3 vs `.claude/agents/*.md` model frontmatter, workflow model opts, any token-discipline rule text
- #4 vs the autonomous-systems self-healing docs and rca-mode (is the retry contract written anywhere reusable?)
- #5 vs fable-discipline `references/checklist.md`, content-reviewer 4-pass, wiring-check

Deliverable: one table (candidate / verdict / evidence path / recommendation). Present it, then WAIT — placement decisions are the founder's.

## Phase 2 — Placement (per approved item)

Fold-vs-standalone criteria, in order:
1. Who consumes it? (one instance → fold there; every instance → kipi-core plugin or `.claude/rules/`)
2. Propagation: only `q-system/`, `.claude/rules|agents|output-styles`, and `plugins/*/` reach instances via `kipi update`. Repo-root does NOT propagate. Instance automation stays at repo root (RULE-2026-06-30-A).
3. Skill-hook pairing: any deterministic slice MUST ship a paired hook (skill-hook-pairing.md). No prompt-only enforcement.
4. Load-path: plugins run from the marketplace clone, not instance `plugins/` (wiring-check scar 2026-06-20).

## Phase 3 — Build (per item, only after Phase 2 OK)

quick-plan per item → fable-discipline (reproducer first, verify against a copy, negative self-test) → wiring-check with evidence → `kipi update --dry` proves fleet propagation.

## Standing connections (do not drop)

- **HuntKit tie-in:** extraction #1 must yield a generic sycophancy core (behavioral rules + decision-origin tagging, no Phase-6/harness/synthesizer references). Then update `~/projects/4_points_consulting/scripts/sync-huntkit.py` RULE_FILES to ship the generic core and rerun the sync — this retires the 2026-07-01 external feedback about dangling references in `huntkit/rules/sycophancy.md`.
- **Open spillover sp-dd731488:** settings-template.json wires token-guard with `|| true` (swallows exit-2 blocks fleet-wide). Any work touching template hook wiring should resolve it properly (via the spillover flow, not hand-clearing).
- Fleet context: huntkit auto-sync now fires from 4_points post-commit (`~/projects/4_points_consulting/scripts/sync-huntkit.py`, plan: `huntkit-parity-sync-2026-07-01.md`).
