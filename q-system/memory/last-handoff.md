# Session handoff — 2026-05-27

## Headline

Built `kipi-investigations` from zero to working product in one session: PDF/image OCR ingestion → LLM-driven entity consolidation / actor profiles / cross-report synthesis → Obsidian vault + Canvas + STIX/MISP/CSV exports → FastAPI webapp designed to a FAANG OSINT analyst bar. Triggered by design partner conversation with Ally (small intel outfit) earlier in the day.

## Where the product lives

`~/projects/kipi-investigations/` — new kipi instance via `kipi new`. Webapp stopped at session end. Restart via `cd ~/projects/kipi-investigations && ./invctl serve` → http://127.0.0.1:8765.

## What got shipped

### Layer 1: Ingestion (`./invctl`)
- PDF + embedded image extraction via PyMuPDF, multi-language Tesseract OCR (eng+ara+fas+heb+rus+chi)
- Markdown, csv, xlsx (openpyxl), telegram JSON, screenshot ingesters
- Regex-first entity extractor (handles, channels, IPs, hashes, wallets, emails, phones, domains, URLs)
- SQLite schema with reports / entities / mentions / aliases / relationships / assets / clusters / typed_relationships / enrichment_links / entity_scores
- CLI: init, reset, ingest, ingest --inbox, query, connections, correlate, stats

### Layer 2: LLM analysis (uses `claude` CLI subprocess, no API key)
- `consolidate` — entity dedup + role tagging (operator/channel/ioc/source/infra/noise). 384 → 266 entities, 92 noise dropped
- `analyze` — typed relationships (operates, posts_in, ally_with, predecessor_of, defaced, hosted_by, member_of, targets, co_admin, same_as) + clusters + threat scoring + pivot URL population. 62 typed rels, 14 clusters, 156 scored entities, 378 pivot links
- `profile` — per-actor analyst dossiers. 59 generated for operators + IoCs (sample: @unydigma profile identified him as Order403 leader, surfaced current + deleted UIDs, flagged OCR digit-recognition discrepancy, posed open questions)
- `synthesize` — single cross-report analyst brief at `vault/synthesis.md`. Real analyst quality: named Order403 crew leadership, TTPs, IP cohort grouping by /24, flagged thin IRGC attribution, 8 next-step pivots

### Layer 3: Outputs
- Obsidian vault: entities/, reports/, sources/, profiles/, synthesis.md
- 3 Canvas files: graph.canvas (hub-only with clusters as group nodes + typed edges + threat-sized nodes), graph_iocs.canvas, diff_latest_report.canvas
- `intel_exports.py`: STIX 2.1 bundle (146 objects), MISP event, CSV (entities/typed_relationships/clusters)

### Layer 4: Webapp (FastAPI + Jinja + Tailwind CDN + Alpine + Cytoscape)
- `./invctl serve` → http://127.0.0.1:8765
- Pages: dashboard, graph (force-directed, filterable, click→side panel), entities (sortable filterable table), entity/{id} (full dossier + typed rels + mentions w/ inline screenshots + pivot URL buttons), reports, sources (lightbox gallery), synthesis, exports
- Cmd+K global fuzzy search across names + aliases
- Dark mode, role-colored pills, confidence-colored edges
- Bugs hit + fixed: Starlette TemplateResponse signature, cytoscape-cose-bilkent CDN 404 (swapped to built-in `cose`), Alpine x-data inline JSON breaking on OCR'd Arabic/Persian content (rewrote to use `<script type="application/json">` + JS read)

### Layer 5: Investigation OS ported from 4_points_consulting
- 22 `/q-*` commands at `.claude/commands/`
- structured-analysis skill (18 IC Structured Analytic Techniques)
- OSINT skill (55 Apify actors + 7 search APIs)
- Case folder templates at `q-investigate/templates/`

## What's NOT done

- Pivot links section only appended to 35 of 59 dossiers (name lookup didn't match — `Unydigma` vs `@unydigma` are still separate entities; needs alias consolidation pass)
- Temporal slider in graph (requires Obsidian plugin or webapp work) — only `diff_latest_report.canvas` works
- 4_points heavy tools NOT ported: `osint-infra-mcp`, `tgspyder`, `threat-intel-mcp` (own venvs + git)
- Telegram xlsx scrapes from Ally's batch were ingested once then wiped per founder request; final pass only had the 3 NVE PDFs
- Watchlist / hypothesis canvas — proposed in FAANG critique but not built
- Webapp is HTTP only, no auth, single-user

## Canonical updated (kipi-system)

- `q-system/my-project/relationships.md` — Ally (design partner), Ethan (FBI), Tova (Active Fence freelance signal), Google friend (toolkit author)
- `q-system/my-project/current-state.md` — kipi-investigations added as new product line
- `q-system/my-project/competitive-landscape.md` — IOC3/Kaden, Palantir, Maltego, Miro friend's tool
- `q-system/canonical/decisions.md` — 4 new rules (design partner arrangement, new-instance not feature, Obsidian-first, sanitization)
- `q-system/canonical/talk-tracks.md` — compounding memory + BYO-data framings
- `q-system/canonical/discovery.md` — open questions + proof gaps

## Open loops for next session

1. **Wait for Ally to send the actual report bundle** — when zip arrives, drop in `investigations/inbox/`, run full pipeline: `./invctl ingest --inbox --investigation handala-2026 && ./invctl consolidate && ./invctl analyze && ./invctl profile && ./invctl synthesize && ./invctl export-vault && ./invctl export-intel`
2. **Re-consolidate to merge alias splits** like `@unydigma` and `Unydigma` — single LLM pass focused on operator-type aliases
3. **Add `watchlist` feature** to webapp
4. **Add multi-case support** — webapp shows one global graph; should respect `q-investigate/investigations/<case>/` boundaries
5. **Show prototype to Ally + record her reaction** — that's the design-partner feedback loop
6. **Loop in Ethan** (FBI contractor, IOC3 originator) once Ally validates

## Memory entries added this session

- `project_kipi_investigations` — new product line context
- `feedback_faang_analyst_bar` — quality standard for any analyst-facing visualization
- `reference_4_points_investigation_os` — what's in 4_points and how to use it from other instances
- `reference_claude_cli_as_llm` — pattern for batch LLM calls in Python without API key
- `feedback_alpine_inline_jsondata` — Jinja-to-Alpine data passing pattern
