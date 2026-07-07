# Fleet Map — all projects, grouped by type

Snapshot: 2026-07-06. Source: filesystem scan of `~/projects/` + `~/projects/cole-gtm/projects/` (9 GTM) + `~/projects/ktlyst-hub/` (6 instances).
Purpose: one index of every project and which function owns it. Update when a project is added, renamed, or retired.

**Persona reorg (phase 1, 2026-07-06):** `random-stuff-ideas` was renamed to `cole-gtm` and 9 GTM
projects moved under `cole-gtm/projects/`. Paths below reflect the new locations. The map is still
grouped by TYPE; Cole's projects are marked `[cole-gtm]`. See `q-system/output/plans/cole-gtm-reorg-2026-07-06.md`.

**GTM consolidation (phase 2, 2026-07-06) — DONE.** Cole is the fleet's single GTM brain.
Part 1: ASK's `products/` content/GTM machine (the "claudedaddy" auto-posting engines, 609MB)
moved to `cole-gtm/products/`; the 5 `com.claudedaddy.*` jobs repoint there. Part 2: ASK core
(`q-consult`, `clients`) renamed `consulting`; `Pure_spectrum_Q` / `4_points_consulting` / `Alice`
now cascade under `consulting/projects/`. The Cole↔ASK bridge is retired both sides (GTM lives in
Cole now). See `q-system/output/plans/gtm-consolidation-ask-to-cole-2026-07-06.md`.

**Micro-SaaS persona (phase 3, 2026-07-06) — DONE.** The 6 $29 Next.js products moved under a new
anchor-less `micro-saas/projects/` bucket (no brain repo; named `micro-saas` to avoid overloading
`cole-gtm/products/`). Zero registry/launchd/bridge touches. Section 5 reflects the new paths. This
proved the tool's `create=True` bucket mode for the remaining anchor-less personas (Dev-tools, Intel).

**Intel persona (phase 4, 2026-07-06) — DONE.** 3 investigation/OSINT projects moved under anchor-less
`intel/projects/` (kipi-investigations, ktlyst-extract, facebook-ads-library-search). 1 registry
rewrite (`investigations`). Two tool improvements landed here: `/runs/` added to the forensic-skip
list (86 scraper capture files left intact) and a `git worktree repair` step (kipi-investigations had
3 nested codex worktrees that a move would have orphaned). Section 2 reflects the new paths.

**Dev-tools persona (phase 5, 2026-07-06) — DONE.** 6 shippable/OSS plugin + dev-tool repos live
under a new anchor-less `dev-tools/projects/` bucket (claude-focus, fable-discipline, kipi-rca,
huntkit, tokentrim, founder-voice-kit). `interview-coach-public` was moved in with this batch then
re-homed to `micro-saas` [USER-DIRECTED] — it's a friend's shipped product, not an OSS plugin.
Cleanest batch of the reorg: zero
registry, zero launchd (name + body scan), zero linked worktrees, zero bridge — pure Tier-0 repo
moves. Only rewrite: 3 tokentrim `_setup_*.py` self-refs (absolute build paths inside the moved dir).
`kipi-system` stays TOP-LEVEL/meta on purpose (it's the factory every persona depends on — plan
open-decision #3). Section 6 reflects the new paths.

---

## 1. KTLYST Core Product (the company product)
| Project | What it is |
|---|---|
| `ktlyst-saas/projects/product` | Security Learning Control Plane: threat-intel PDFs → governed defense artifacts (multi-agent Python pipeline). LIVE v5, standalone. Promoted from the former `ktlyst-hub/product-baseline` (RULE-2026-07-06-G). Origin → dedicated private repo `github.com/assafkip/ktlyst-saas-product` (v5 backed up 2026-07-07, verified); `ktlyst.git` kept as `legacy` remote for provenance. |

Note: `ktlyst-hub/` is DISSOLVED (RULE-G) — the old `product` + `product-baseline` copies are in `_archive/` (`product-ktlyst-old-2026-07-06`, `ktlyst-hub-dissolved-2026-07-07`). One live product now.

## 2. Investigation / OSINT — persona `intel`
The 3 standalone investigation/OSINT projects moved under `intel/projects/`
(persona reorg phase 4, 2026-07-06). 4_points + Alice stay under `consulting`.
The KTLYST product you SELL (now `ktlyst-saas/projects/product`, see §1) also fits
`intel` but lives under its own `ktlyst-saas` persona post-dissolution (RULE-G).
| Project | What it is |
|---|---|
| `consulting/projects/4_points_consulting` `[consulting]` | Production investigation OS + client invoicing (27 live cases) |
| `consulting/projects/Alice` `[consulting]` | Single-case investigation instance |
| `intel/projects/kipi-investigations` `[intel]` | Ingestion → Obsidian + deployed webapp (registry `investigations`; kipi-web frontend; 3 git worktrees re-linked on move) |
| `intel/projects/ktlyst-extract` `[intel]` | PDF → structured intel (Next.js sibling of the product) |
| `intel/projects/facebook-ads-library-search` `[intel]` | Meta Ad Library scraper → ad evidence (86 `runs/` capture files left forensic-intact) |

## 3. Consulting Instances (client / business engagement hubs)
| Project | What it is |
|---|---|
| `consulting` `[persona]` | ASK Consulting business OS, renamed. GTM `products/` moved to `cole-gtm/products/`; keeps q-consult + clients. Registry entry still named `ASK_AI_consultant` → path `consulting`. Pure/4points/Alice cascade under it |
| `consulting/projects/Pure_spectrum_Q` `[consulting]` | PureSpectrum fractional advisory hub (runs ps-slack-sync + ti-weekly jobs) |
| `consulting/projects/accountant` `[consulting]` | Books for KTLYST + ASK (2 cash-basis ledgers) |
| `consulting/projects/lawyer` `[consulting]` | In-house legal advisor |
| `cole-gtm/projects/event_coordinator` `[cole-gtm]` | Stub (still `{{DESCRIPTION}}` placeholder) |
| `ktlyst-review-panel` | 9-persona brutal review of deliverables |

## 4. GTM — owned by **Cole**
| Project | What it is |
|---|---|
| `cole-gtm` | **The GTM home + Cole persona repo.** Cole Mercer (cole@ktlystlabs.com) + `gtm/` pipeline (ICP, positioning, campaigns, chris-pi deal); the 9 below cascade under `cole-gtm/projects/` |
| `cole-gtm/products/` `[cole-gtm]` | The "claudedaddy" content machine (moved from ASK 2026-07-06). AFTER DEDUP: `distribution-engine` LIVE (`com.claudedaddy.repo-distribution`, ships GitHub repos) + video product catalog + kits. Daily podcast is in `gtm/scripts/podcast/`. ARCHIVED 2026-07-06 (`~/projects/_archive/`): x/youtube/pinterest posters + jobs (didn't work), refill-engine (fed posters), ai-news-podcast (dead TTS predecessor) |
| ~~`founder-signal-engine`~~ ARCHIVED 2026-07-06 | Was a dormant subset of `competitive-analysis` (same code, couldn't ingest on its own). Archived to `~/projects/_archive/`; competitive-analysis is the canonical superset |
| `fractional-cxo` | Scans feeds for fractional roles, $250/hr floor, Slack-pings (NOT moved — still top-level) |
| `cole-gtm/projects/signal-desk` `[cole-gtm]` | Market signals → ranked contact actions |
| `cole-gtm/projects/strategy` `[cole-gtm]` | Decks, investor docs, positioning research; canonical positioning source (post-dissolution, RULE-G) |
| `cole-gtm/projects/notebooklm-daily-podcast` `[cole-gtm]` | Daily AI-news podcast (the "podcast" under Cole) |

## 5. Website-Gen / $29 Micro-SaaS (Next.js, *.ktlystlabs.com) — persona `micro-saas`
The 6 below moved under `micro-saas/projects/` (persona reorg phase 3, 2026-07-06).
Anchor-less bucket (no brain repo); named `micro-saas` to avoid overloading
`cole-gtm/products/`. Same shape: paste input → cited critique/grade → $29 upsell.
| Project | What it is |
|---|---|
| `micro-saas/projects/cheapcheck` `[micro-saas]` | Why your site looks cheap |
| `micro-saas/projects/briefonce` `[micro-saas]` | Project-brief grader |
| `micro-saas/projects/authorvoice` `[micro-saas]` | Manuscript voice editor |
| `micro-saas/projects/feedbackpin` `[micro-saas]` | Pin revision notes on a page |
| `micro-saas/projects/runreceipts` `[micro-saas]` | Verify agent-run completion claims vs diff |
| `micro-saas/projects/shipgate` `[micro-saas]` | PR ship-readiness gate |
| `micro-saas/projects/interview-coach-public` `[micro-saas]` | Behavioral interview coach — a friend's shipped product (re-homed from dev-tools 2026-07-06; it's a product, not an OSS plugin) |
| `cole-gtm/projects/website` `[cole-gtm]` | The Kipi System marketing site (has a CLAUDE.md merge conflict); keeps KTLYST bridge dual-role (writes `website-state.json`) |

Interview coach — shipped 3× as hosted products (consolidation target):
`freshlist`, `warmreach`, `slimcli` — same behavioral interview coach, paywalled webapp.

## 6. Dev-Tools / Claude Code Plugins (shippable / OSS) — persona `dev-tools`
The 7 below moved under `dev-tools/projects/` (persona reorg phase 5, 2026-07-06).
Anchor-less bucket (no brain repo). `kipi-system` is NOT here — it stays top-level/meta.
| Project | What it is |
|---|---|
| `dev-tools/projects/claude-focus` `[dev-tools]` | 3 anti-drift hooks (MIT) |
| `dev-tools/projects/fable-discipline` `[dev-tools]` | Engineering-discipline plugin (also merged into prd-os) |
| `dev-tools/projects/kipi-rca` `[dev-tools]` | Root-cause-analysis plugin |
| `dev-tools/projects/huntkit` `[dev-tools]` | OSINT toolkit as a plugin |
| `dev-tools/projects/tokentrim` `[dev-tools]` | Model-routing cost optimizer (3 `_setup_*.py` self-refs repointed) |
| `dev-tools/projects/founder-voice-kit` `[dev-tools]` | Voice-enforcement hook stack |

## 7. Design — owned by the **design kit**
| Project | What it is |
|---|---|
| `kipi-design` plugin (in kipi-system) | brand / design / ui-ux-pro-max skills — the design kit |
| `design-room` skill | Multi-lens design review + visual-diff critic |

Eyeball: retired. The `~/projects/eyeball` repo is gone from disk. The deterministic dogfood tripwire (`plugins/kipi-design/hooks/dogfood_gate.py`) runs standalone on a bundled fallback fingerprint. Only stale doc/error-string references remain. The vision-render capability belongs in design-room.

## 8. Research / Signal Dashboards
| Project | What it is |
|---|---|
| `cole-gtm/projects/competitive-analysis` `[cole-gtm]` | AI market signals → newsletter + podcast brief |
| `cole-gtm/projects/reddit-build-radar` `[cole-gtm]` | Reddit consensus → one weekly build idea |
| `cole-gtm/projects/vc-signals` `[cole-gtm]` | Cyber VC investment dashboard (GitHub Pages) |

## 9. Personal / Single-Purpose Coaches (kipi instances, not for sale)
| Project | What it is |
|---|---|
| `travel-agent` | Family travel planning |
| `negotiator` | Car negotiation |
| `school-negotiator` | Tuition negotiation |
| `school-idf` | Classroom activities |
| `AUDHD_KIDS` | Parenting knowledge base |
| `cole-gtm/projects/personal-brand` `[cole-gtm]` | Personal-brand advisory |

## Infra (not products)
| Project | What it is |
|---|---|
| `kipi-system` | The skeleton/OS every instance is built from |
| `intel/projects/deliverables` `[intel]` | Output / hosting store |
| `_archive`, `_codex-worktrees` | Housekeeping |

---

## Open items surfaced by the scan
1. Interview coach exists 5 ways (interview-coach, interview-coach-public, freshlist, warmreach, slimcli). Consolidation target.
2. ~~KTLYST product duplicated (product + product-baseline).~~ RESOLVED 2026-07-07 (RULE-G + cleanup): old line archived, product-baseline promoted to `ktlyst-saas/projects/product` (v5, standalone, backed to dedicated private repo).
3. Eyeball retired — clean up stale references in `dogfood_gate.py` + `.claude/rules/dogfood-gate.md` when convenient.
