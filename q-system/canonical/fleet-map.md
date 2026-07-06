# Fleet Map — all projects, grouped by type

Snapshot: 2026-07-06. Source: filesystem scan of `~/projects/` (42 dirs) + `~/projects/ktlyst-hub/` (9 instances).
Purpose: one index of every project and which function owns it. Update when a project is added, renamed, or retired.

---

## 1. KTLYST Core Product (the company product)
| Project | What it is |
|---|---|
| `ktlyst-hub/product` | Security Learning Control Plane: threat-intel PDFs → governed defense artifacts (multi-agent Python pipeline, ktlyst_v2 v0.2.0) |
| `ktlyst-hub/product-baseline` | Reference copy of the same, with zip packaging + disclaimer detail |

Note: two near-copies of one product.

## 2. Investigation / OSINT
| Project | What it is |
|---|---|
| `4_points_consulting` | Production investigation OS + client invoicing (27 live cases) |
| `Alice` | Single-case investigation instance |
| `kipi-investigations` | Ingestion → Obsidian + deployed webapp |
| `ktlyst-extract` | PDF → structured intel (Next.js sibling of the product) |
| `facebook-ads-library-search` | Meta Ad Library scraper → ad evidence |

## 3. Consulting Instances (client / business engagement hubs)
| Project | What it is |
|---|---|
| `ASK_AI_consultant` | ASK Consulting business OS |
| `Pure_spectrum_Q` | PureSpectrum fractional advisory hub |
| `ktlyst-hub/accountant` | Books for KTLYST + ASK (2 cash-basis ledgers) |
| `ktlyst-hub/lawyer` | In-house legal advisor |
| `ktlyst-hub/event_coordinator` | Stub (still `{{DESCRIPTION}}` placeholder) |
| `ktlyst-review-panel` | 9-persona brutal review of deliverables |

## 4. GTM — owned by **Cole**
| Project | What it is |
|---|---|
| `random-stuff-ideas` | **The GTM home.** Cole Mercer persona (cole@ktlystlabs.com) + `gtm/` pipeline (ICP, positioning, campaigns, chris-pi deal) |
| `founder-signal-engine` | Market signals → LinkedIn posts / comments / newsletter |
| `fractional-cxo` | Scans feeds for fractional roles, $250/hr floor, Slack-pings |
| `signal-desk` | Market signals → ranked contact actions |
| `ktlyst-hub/strategy` | Decks, investor docs, positioning research |
| `notebooklm-daily-podcast` | Daily AI-news podcast (the "podcast" under Cole) |

## 5. Website-Gen / $29 Micro-SaaS (Next.js, *.ktlystlabs.com)
Same shape: paste input → cited critique/grade → $29 upsell.
| Project | What it is |
|---|---|
| `cheapcheck` | Why your site looks cheap |
| `briefonce` | Project-brief grader |
| `authorvoice` | Manuscript voice editor |
| `feedbackpin` | Pin revision notes on a page |
| `runreceipts` | Verify agent-run completion claims vs diff |
| `shipgate` | PR ship-readiness gate |
| `ktlyst-hub/website` | The Kipi System marketing site (has a CLAUDE.md merge conflict) |

Interview coach — shipped 3× as hosted products (consolidation target):
`freshlist`, `warmreach`, `slimcli` — same behavioral interview coach, paywalled webapp.

## 6. Dev-Tools / Claude Code Plugins (shippable / OSS)
| Project | What it is |
|---|---|
| `claude-focus` | 3 anti-drift hooks (MIT) |
| `fable-discipline` | Engineering-discipline plugin (also merged into prd-os) |
| `kipi-rca` | Root-cause-analysis plugin |
| `huntkit` | OSINT toolkit as a plugin |
| `tokentrim` | Model-routing cost optimizer |
| `founder-voice-kit` | Voice-enforcement hook stack |
| `interview-coach-public` | OSS release of the coach |

## 7. Design — owned by the **design kit**
| Project | What it is |
|---|---|
| `kipi-design` plugin (in kipi-system) | brand / design / ui-ux-pro-max skills — the design kit |
| `design-room` skill | Multi-lens design review + visual-diff critic |

Eyeball: retired. The `~/projects/eyeball` repo is gone from disk. The deterministic dogfood tripwire (`plugins/kipi-design/hooks/dogfood_gate.py`) runs standalone on a bundled fallback fingerprint. Only stale doc/error-string references remain. The vision-render capability belongs in design-room.

## 8. Research / Signal Dashboards
| Project | What it is |
|---|---|
| `competitive-analysis` | AI market signals → newsletter + podcast brief |
| `reddit-build-radar` | Reddit consensus → one weekly build idea |
| `vc-signals` | Cyber VC investment dashboard (GitHub Pages) |

## 9. Personal / Single-Purpose Coaches (kipi instances, not for sale)
| Project | What it is |
|---|---|
| `travel-agent` | Family travel planning |
| `negotiator` | Car negotiation |
| `school-negotiator` | Tuition negotiation |
| `school-idf` | Classroom activities |
| `AUDHD_KIDS` | Parenting knowledge base |
| `ktlyst-hub/personal-brand` | Personal-brand advisory |

## Infra (not products)
| Project | What it is |
|---|---|
| `kipi-system` | The skeleton/OS every instance is built from |
| `ktlyst-hub/deliverables` | Output / hosting store |
| `_archive`, `_codex-worktrees` | Housekeeping |

---

## Open items surfaced by the scan
1. Interview coach exists 5 ways (interview-coach, interview-coach-public, freshlist, warmreach, slimcli). Consolidation target.
2. KTLYST product duplicated (product + product-baseline).
3. Eyeball retired — clean up stale references in `dogfood_gate.py` + `.claude/rules/dogfood-gate.md` when convenient.
