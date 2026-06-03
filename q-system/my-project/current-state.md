# Current State

> Single source of truth for what works today vs. what's planned.

## Product Lines <!-- pin -->

### kipi-system (founder OS)
The compounding founder operating system. Lives in `~/projects/kipi-system/`.

### kipi-investigations (NEW — 2026-05-27)
Productized version of the kipi-core investigation memory layer, for boutique intel / small T&S teams. Lives in `~/projects/kipi-investigations/`.
- **Design partner:** Ally (see relationships.md)
- **Wedge use case:** Ingest multiple intel reports; auto-build a compounding knowledge graph; visualize in Obsidian.
- **ICP:** Boutique intel firms, resource-constrained T&S teams, PI shops, freelance OSINT investigators.

## What Works Today (Demo-able) <!-- pin -->
- Compounding investigation memory in kipi-core (consulting use case proven for Assaf's daily work)
- Telegram scraping pipeline → intel synthesis
- Python-deterministic CSV/document extraction before LLM reasoning
- File-based knowledge layer that survives across Claude sessions
- Multi-instance kipi system via `kipi new <path> <name>`

## Claimed But Unproven
- "Build in two days" — true for Assaf with current tooling, {{NEEDS_VALIDATION}} as a customer-facing claim
- Cross-investigation entity correlation at scale beyond ~10 reports {{NEEDS_PROOF}}

## Planned / Vision
- Obsidian vault export module {{IN_PROGRESS — kipi-investigations}}
- Web UI v0 (Ally explicitly said graph in Obsidian is the visualization, defer custom UI)
- AWS-instance deployment for multi-user team access
- SaaS pricing model {{UNVALIDATED}}

## Key Metrics
- **Fundraise target:** N/A (bootstrapped)
- **Team size:** 1 (founder)
- **Active design partners:** 1 (Ally — kipi-investigations)

## What We Are NOT <!-- pin -->
- Not Palantir (enterprise pricing/complexity)
- Not Maltego (graph-as-product, no compounding memory)
- Not an OSINT aggregator (we don't pull data from external systems; user brings their own intel)
- Not IOC3/Kaden's tool (username-to-graph aggregator — narrower scope)
- Not "another T&S dashboard"

## kipi-investigations Specific <!-- pin -->

### The wedge
Customer drops intel reports (PDF/MD/CSV/screenshots/telegram scrapes) into an inbox. System ingests, extracts entities/relationships, correlates against prior reports, exports an Obsidian vault. Compounding memory across investigations.

### What it IS
- Investigation memory layer
- Compounding knowledge graph
- BYO-data (the user supplies the intel)
- Obsidian-native visualization

### What it is NOT
- Not OSINT data collection (telegram scraper module exists but is optional)
- Not a SaaS at launch (consultant-deployed prototype first)
- Not integrated into customer's existing data systems (BYO data is the constraint)
