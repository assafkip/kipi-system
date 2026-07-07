# Plan: Cole-GTM — the main interface + home for all GTM projects

**What/why:** Make `cole-gtm/` the single thing the founder opens for GTM work — Cole the persona at its root, all GTM projects cascading underneath, Cole's CLAUDE.md routing to each. First persona in the fleet-wide reorg (see `persona-reorg-2026-07-06.md`). Complete + break-nothing.

**Status:** PLAN. Nothing moves until the founder approves a `--dry` run.

---

## Ground truth (scanned 2026-07-06)

- **`random-stuff-ideas` IS Cole.** Root `CLAUDE.md` = the "gtm-partner" persona (self-naming Cole entity). Holds `persona/`, `q-system/` (kipi instance), and the full `gtm/` brain (icp, positioning, pricing, campaigns, deals, channels, outreach-playbook, scripts, design-room, sites). The `com.cole.*` launchd jobs already run from `random-stuff-ideas/gtm/scripts/podcast/`.
- **So Cole-GTM = rename + promote `random-stuff-ideas` → `cole-gtm`.** Not a new empty container. Least breakage: the persona, brain, registry entry, and launchd targets are already there; only the parent name changes.
- **All 10 projects are independent git repos.** `ktlyst-hub` is a plain container (not a repo) — the precedent Cole-GTM follows.

---

## Target structure

```
cole-gtm/                       (renamed random-stuff-ideas — Cole persona repo + interface)
├── CLAUDE.md                   (Cole persona; + NEW roster/router to projects/*)
├── persona/                    (Cole identity — unchanged)
├── q-system/                   (Cole's kipi OS — unchanged)
├── gtm/                        (Cole's brain incl. LIVE podcast pipeline — unchanged)
├── projects/                   (NEW cascade; each an independent nested repo, gitignored in parent)
│   ├── notebooklm-daily-podcast/
│   ├── reddit-build-radar/
│   ├── vc-signals/
│   ├── event_coordinator/          (moves from ktlyst-hub)
│   ├── website/                    (moves from ktlyst-hub)
│   ├── personal-brand/             (moves from ktlyst-hub)
│   ├── founder-signal-engine/      (+add)
│   ├── signal-desk/                (+add)
│   └── competitive-analysis/       (+add)
└── (root clutter: src/ build/ build2/ motion-teardown/ radar/ work/ supabase/ — cleanup, separate task)
```

**The "interface":** `cole-gtm/CLAUDE.md` gains a roster section — one line per sub-project (what it is, when to route to it, its path). Opening `cole-gtm/` = you are Cole, and Cole knows his whole portfolio.

---

## The breakage ledger (complete for Cole-GTM)

### A. instance-registry.json — 5 path rewrites
| Registry name | Old path | New path |
|---|---|---|
| (random-stuff-ideas entry) | `projects/random-stuff-ideas` | `projects/cole-gtm` |
| ktlyst-website | `projects/ktlyst-hub/website` | `projects/cole-gtm/projects/website` |
| personal-brand | `projects/ktlyst-hub/personal-brand` | `projects/cole-gtm/projects/personal-brand` |
| event_coordinator | `projects/ktlyst-hub/event_coordinator` | `projects/cole-gtm/projects/event_coordinator` |
| reddit-build-radar | `projects/reddit-build-radar` | `projects/cole-gtm/projects/reddit-build-radar` |

### B. launchd plists — 5 rewrites + reload
| Plist | Change | Tier |
|---|---|---|
| com.cole.daily-podcast.plist | `random-stuff-ideas` → `cole-gtm` | 2 (verify fires) |
| com.cole.podcast-report.plist | same | 2 |
| com.cole.podcast-weekly-report.plist | same | 2 |
| com.cole.daily-video.plist.disabled | same (rewrite even though disabled) | — |
| com.assaf.competitive-analysis.morning.plist | `competitive-analysis` → `cole-gtm/projects/competitive-analysis` | 2 (verify fires) |

### C. Global rule — 1 (needs founder confirm; it's a ~/.claude sibling file)
- `~/.claude/rules/ktlyst-cluster.md` — website + event_coordinator rows point at `~/projects/ktlyst-hub/...`. They leave ktlyst-hub. Update rows OR note them as Cole-owned. Per cross-instance preflight rule, founder confirms before this edit.

### D. Bridge — 1 (preserve, don't break)
- `~/.ktlyst/bridge/website-state.json` — website writes deployed-copy state for the KTLYST cluster. **website keeps dual citizenship:** Cole-GTM asset AND KTLYST bridge writer. If website's deploy/sync script hardcodes its own absolute path, rewrite it; the bridge write itself must keep working. Verify `website-state.json` still updates after the move.

### E. Catch-all — two-pass grep
- Pass 1 + pass 2 for absolute `~/projects/random-stuff-ideas`, `~/projects/ktlyst-hub/{website,personal-brand,event_coordinator}`, `~/projects/{reddit-build-radar,competitive-analysis,vc-signals,founder-signal-engine,signal-desk,notebooklm-daily-podcast}` across the fleet + scripts. Rewrite every hit (token-discipline Cleanup Rule).

---

## Ordered migration (within Cole-GTM, safe-first)

1. **Dry-run the full Cole batch.** `persona-reorg.py --persona cole-gtm --dry` prints every move + every path rewrite (registry, plists, rule, grep hits). Nothing changes. Founder approves the output.
2. **Rename `random-stuff-ideas` → `cole-gtm`** (parent rename). Rewrite + reload the 4 `com.cole.*` plists. **Verify:** podcast job fires from new path (Tier-2, the risk item — but it's only a parent-name substitution). Registry entry resolves; `kipi check`.
3. **Create `cole-gtm/projects/`; add to parent `.gitignore`.** Move the 4 low-risk repos in: notebooklm-daily-podcast, vc-signals, founder-signal-engine, signal-desk. No registry/launchd. Smoke each from new path.
4. **Move competitive-analysis.** Rewrite + reload its 1 plist. **Verify:** morning job fires.
5. **Move reddit-build-radar.** Rewrite registry. `kipi check`.
6. **Move the 3 ktlyst-hub instances** (website, personal-brand, event_coordinator). Rewrite 3 registry entries; update `ktlyst-cluster.md` (founder-confirmed); **preserve website bridge write.** Verify `kipi check` + `website-state.json` still updates.
7. **Write Cole's roster/router** into `cole-gtm/CLAUDE.md` (the interface).
8. **Full verification** (acceptance below).

---

## Acceptance criteria

- [ ] `--dry` output reviewed + approved before any real change
- [ ] `random-stuff-ideas` → `cole-gtm` renamed; git repo + remote intact
- [ ] All 9 sub-projects present under `cole-gtm/projects/`, each still its own repo (remote intact)
- [ ] `kipi check` + `kipi list` green (all 5 registry paths resolve)
- [ ] All 5 launchd jobs reloaded + confirmed firing (`launchctl list` + one triggered run each)
- [ ] `~/.ktlyst/bridge/website-state.json` still updates (website bridge role preserved)
- [ ] `ktlyst-cluster.md` reflects the 3 departures (founder-confirmed)
- [ ] `cole-gtm/CLAUDE.md` roster routes to all 9 sub-projects
- [ ] Two-pass grep: zero stale absolute refs to any old path
- [ ] Rollback dry-run proven to reverse the batch
- [ ] launchd-health watchdog quiet 24h after (no silent job death)

---

## Decisions specific to Cole-GTM (need founder call)

1. **Layout fork (the big one). — LOCKED: A (founder-decided 2026-07-06).**
   - **A (chosen):** `cole-gtm/` = renamed `random-stuff-ideas` (persona repo at root) + `projects/` nested & gitignored. Cole-GTM is both interface AND its own project. Least breakage.
   - ~~B: plain container + `cole/` subdir~~ — not chosen.
2. **Two podcasts.** Live `gtm/scripts/podcast/` (NotebookLM, launchd-driven) vs standalone `notebooklm-daily-podcast` repo (RSS/email, active). Consolidate to one, or keep both with defined roles? Not a blocker — flag for later.
3. **Root clutter.** Clean `src/ build/ build2/ motion-teardown/ radar/ work/ supabase/` out of the promoted `cole-gtm/` root during the move, or leave and clean separately? Rec: separate cleanup task, don't bundle.
4. **website dual role.** Confirm website stays a KTLYST bridge writer (writes `website-state.json`) after moving under Cole. Rec: yes — it's still the KTLYST marketing site, Cole just owns the repo now.

## Patterns followed (this repo's own)
- Deterministic script + `--dry` + reversible (founder rule; self-healing-retry contract).
- Two-pass grep on rename (token-discipline Cleanup Rule).
- Instance automation at repo root, not synced subtrees (launchd-autonomous-layer scar).
- Cross-instance preflight before editing `~/.claude/rules/ktlyst-cluster.md` (KTLYST cluster rule).
