# Memory Outcome Scoring — fleet reuse + propagation (2026-07-04)

Durable checkpoint so context can be cleared. Resume from here.

## What shipped (this session)

Earned-trust memory scoring, ported from graphify `reflect.py` (MIT). PR #6:
https://github.com/assafkip/kipi-system/pull/6 — branch `prd/memory-outcome-scoring`,
NOT merged. Full prd-os flow: PRD → Codex review (6) → 5 issues → 19 findings
triaged → archived. 45 tests green.

Files (all skeleton, all in `q-system/.q-system/scripts/`):
- `memory_outcomes.py` — append-only outcome log, single-writer + event_id dedup +
  scope guard + capture CLI.
- `memory_reflect.py` — scoring engine (30d half-life decay, corroboration gate,
  contested, dead-ends, deterministic sidecar, source-fingerprint staleness).
- `memory-scores-surface.py` — SessionStart block + MEMORY.md `[contested]`/`[stale]`
  markers; refreshes sidecar from log first (atomic).
- Wired into `.claude/settings.json` + `settings-template.json` SessionStart.

## Q1: Will `kipi update` (template push) alone propagate it? YES — verified.

`kipi-update.sh` (read 2026-07-04):
- Line 136-183: `git archive HEAD -- q-system/` + `rsync -a --delete` into each
  instance. Carries all 3 scripts (they live under `q-system/.q-system/scripts/`,
  same path as the already-propagating `memory-confidence-surface.py`).
- Line 235-243: rebuilds each instance `.claude/settings.json` from
  `settings-template.json` via `kipi-settings-merge.py`. Carries the SessionStart
  wiring. The template entry is `test -f <script> && python3 ...` so it is safe
  even if the script has not landed yet.

**Conclusion: one `kipi update` makes it LIVE fleet-wide. No new plumbing.**

## Q2: But does "live" == "useful"? NO — the gap.

Live but INERT. The surface is silent until outcomes are recorded, and capture is
MANUAL-only (the CLI). Nothing auto-records "this memory was useful/a dead end."
So after a template push every instance has the pipeline running and doing
nothing until someone feeds it.

**To get value without manual discipline = build something new: auto-capture.**
That is the open spillover `sp-04006168` (agent deciding WHEN a recall counts as
useful/dead_end/corrected — a design question, likely its own PRD). Also open:
`sp-dd6a3d86` (`load_sidecar` isinstance guard, patched defensively for now).

## Which instances actually benefit (usage-pattern judgment, not plumbing)

All 21 CAN run it (memory system is skeleton-standard). Value differs by usage:

**High — long-running, heavy memory reuse, real cost of a stale memory:**
- `4_points_consulting` (investigation OS, 27 live cases) — top candidate.
- `investigations` (kipi-investigations, boutique intel) — top candidate.
- `KTLYST_strategy` (GTM/positioning/relationships/deals canonical).
- `ktlyst` (product, technical truth), `gtm-partner` (random-stuff-ideas; deals),
  `Pure_spectrum_Q` (investigation).

**Medium — ongoing but stabler memory:**
- `ASK_AI_consultant`, `fractional-cxo`, `ktlyst_lawyer`, `accountant`,
  `personal-brand`, `reddit-build-radar`.

**Low — single-purpose / short-lived, little memory accumulation (harmless but
no value; surface stays silent):**
- `school-negotiator`, `interview-coach`, `negotiator`, `school-idf`,
  `AUDHD_KIDS`, `travel-agent`, `event_coordinator`, `Alice`, `ktlyst-website`.

## Decisions open for the founder

1. Merge PR #6 first (eyeball the scoring math + resolver), THEN `kipi update`.
2. `kipi update` pushes it live everywhere at once (safe: advisory, silent, guarded).
   Or hold and only enable where it earns its keep (would need a per-instance flag =
   new build). Default: push fleet-wide, it is harmless where unused.
3. The value unlock is the auto-capture PRD. Highest ROI on the investigation
   instances (4_points, kipi-investigations) where a wrong memory is expensive.

## Resume pointer

Next unchecked: (a) merge PR #6, (b) `kipi update` to propagate, (c) scope the
auto-capture PRD (start on 4_points or kipi-investigations as the design partner).
