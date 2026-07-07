# Plan: consolidate ALL GTM under Cole; ASK core becomes the Consulting persona

**What/why:** Founder decision (2026-07-06): Cole is the fleet's single GTM brain — GTM for
consulting, products, everything lives in Cole. ASK_AI_consultant is really two operations
bolted together: a consulting business (`q-consult/`, `clients/`) AND a 609MB content/GTM
machine (`products/` — the "claudedaddy" auto-posting engines + marketing + kits). Split them:
GTM → Cole, consulting core → the `consulting` persona.

**Status:** APPROVED shape. Two parts. Dry-first per part before any move.

---

## Part 1 — GTM extraction: ASK `products/` → `cole-gtm/products/`

- Move `~/projects/ASK_AI_consultant/products/` (609MB, self-contained — verified no
  `q-consult` dependency) → `~/projects/cole-gtm/products/`.
- Repoint the 5 `com.claudedaddy.*` launchd jobs (x/youtube/pinterest/distribution/refill)
  from `ASK_AI_consultant/products/...` → `cole-gtm/products/...`; reload; verify each fires.
- Rewrite the engine scripts' hardcoded `PROJECT="…/ASK_AI_consultant"` → `…/cole-gtm`
  (one substitution `/projects/ASK_AI_consultant` → `/projects/cole-gtm` across moved live
  code; evidence/data untouched). In-repo plist copies under `products/*/` update too.
- **Grows Cole on purpose** — this is the "Cole owns all GTM" call, so touching Cole is intent.
- Verify: `kipi check` at baseline (products/ is not a registry instance); 5 jobs loaded + fire.

## Part 2 — Consulting persona: ASK (minus products/) → `consulting`

- Rename remaining ASK → `consulting`; `Pure_spectrum_Q`, `4_points_consulting`, `Alice`
  cascade under `consulting/projects/`.
- 4 registry entries, 2 Pure plists, 25 live self-ref rewrites; **55 forensic evidence/data
  files LEFT AS-IS** (chain-of-custody). `com.ask.ai-podcast` in-repo only (not installed).

## Cross-cutting — retire the Cole↔ASK bridge

- `cole-gtm/.claude/rules/cole-ask-bridge.md` (live ENFORCED rule) + ASK's
  `cole-gtm-bridge.md` existed to link two brains. GTM now lives IN Cole → the bridge is moot.
  Retire both. The 3 `cole-gtm/.prd-os/` bridge records are historical — leave.
- `kipi-investigations/…/4points_port_audit.py:19` hardcodes the 4_points path — rewrite (TP2).

---

## The breakage ledger

| Item | Count | Handling |
|---|---|---|
| products/ engine scripts (`PROJECT=`) | ~5 + in-repo plists | self-ref rewrite ASK→cole |
| `com.claudedaddy.*` plists | 5 | rewrite path + reload + verify fires |
| Registry (Part 2) | 4 (ASK→consulting, Pure, 4points, Alice) | per-move rewrite |
| Pure plists (Part 2) | 2 | rewrite + reload |
| Forensic evidence (4_points) | 55 | LEFT AS-IS (never rewritten) |
| Cole↔ASK bridge rules | 2 live | retire both |
| kipi-investigations → 4_points | 1 script | rewrite 1 path |

## Acceptance criteria

- [ ] Part 1 dry approved before move
- [ ] products/ under cole-gtm/, 5 claudedaddy jobs fire from new path
- [ ] `kipi check` at baseline (2 FAIL) after Part 1 and after Part 2
- [ ] Part 2 dry approved before move
- [ ] `consulting` = ASK core + Pure/4points/Alice; registry resolves; evidence untouched
- [ ] Bridge retired both sides; kipi-investigations ref fixed
- [ ] Rollback tested each part via its own manifest file

## Open items (parked)
- products/ is 609MB (videos/zips) — will show untracked in cole-gtm's git; founder decides
  commit vs gitignore heavy assets. Cross-repo move does not preserve git history.
- 3 consulting-side docs mention products/ (historical) — leave.
- **Tool gap (symlinked plists):** persona-reorg.py follows a symlinked plist and rewrites
  nothing. Hit on `com.purespectrum.ti-weekly.plist`; fixed via `ln -sf` + reload.
- **Tool gap (crontab):** persona-reorg.py only rewrites launchd, NOT crontab. `reddit-build-radar`
  had a `crontab` 8am daily line pointing at the old flat path — broke silently at the Cole move,
  caught by the dedup audit, fixed by rewriting the crontab line. Add `crontab -l` scan to the tool.
- **Orphaned bridge scripts** (`build_gtm_digest.py`, `read_ask_state.py`, `verify_bridge.py`
  in cole-gtm/gtm/scripts; `emit_gtm_state.py` in consulting) + any prd-os bridge gates — the
  bridge rules are tombstoned but these scripts/gates still exist. Retire when convenient.
- Registry entries keep old names (`ASK_AI_consultant`→path consulting, `gtm-partner`→cole-gtm),
  matching the Cole precedent. Rename the entries later if the codenames cause confusion.

## Status: Part 1 + Part 2 COMPLETE (2026-07-06). Bridge retired, TP2 fixed, canonical tracked.

## Patterns (each backed by code in `scripts/persona-reorg.py`, not prose)
- `--dry` default + `--rollback` from a per-persona manifest (`manifest_path()`).
- Evidence protection: `is_live_selfref()` + `SELFREF_SKIP_PATHSEG` deny-list skip
  investigations/evidence/output/data paths in `rewrite_selfrefs_in()`.
- Per-job launchd check: `verify_launchd()` asserts each label loaded after reload.
- kipi-check gate: `verify_kipi_check()` aborts (rollback-able) on FAIL > baseline.
- Two-pass grep classification in `grep_hits()` (live vs data vs vendored vs skip).
