---
id: prd-competitive-intel-analyst-2026-06-30
title: Competitive Intel Analyst Workflow
status: idea
created_at: 2026-06-30T00:00:00Z
updated_at: 2026-06-30T00:00:00Z
owner: assafkipnis
reviewers: []
findings_path: .prd-os/findings/prd-competitive-intel-analyst-2026-06-30-findings.jsonl
---

# Competitive Intel Analyst Workflow

## Problem

KTLYST already has the pieces of a competitive intelligence analyst spread across
Strategy and ASK: platform sourcing, Reddit fetchers, ICP signal scoring, Apify
rules, and weekly signal outputs. The missing part is a clean reusable component
that turns normalized social/content harvest records into a weekly market-read
newsletter that connects repeated patterns across watched entities.

## Goals

- Provide a deterministic analyzer that reads a watchlist and normalized harvest
  records, clusters repeated themes across entities, and renders a weekly intel
  newsletter.
- Ship a runnable CLI with checked-in fixture data, so the workflow can be tested
  without live Instagram, TikTok, LinkedIn, X, YouTube, Reddit, or Apify calls.
- Document exactly which Strategy and ASK components this extracts from, and how
  the existing Kipi harvest layer can feed it later.
- Prove behavior with tests for cross-entity trend detection, CLI output, and bad
  input rejection.

## Non-goals

- No live platform scraping in this increment. Live collection stays in the
  existing Kipi harvest layer and external actors.
- No LLM dependency. The first version is deterministic and auditable.
- No database schema change.
- No newsletter sending integration.

## Proposed approach

Add `kipi_mcp.competitive_intel` inside the reusable MCP package:

- `Watchlist` input names watched entities, categories, platform handles, and
  theme keywords.
- `HarvestRecord` input represents normalized posts from any source.
- Analyzer groups records by watched entity, detects theme convergence when two
  or more entities mention the same configured theme, and emits an `IntelReport`.
- Renderer creates a Markdown newsletter with market moves, entity activity, and
  source appendix.
- CLI reads JSON/YAML files and writes Markdown plus optional JSON.

The existing Strategy and ASK assets remain evidence and feeders. Strategy has the
platform-specific lead sourcing agent and Reddit fetcher; ASK has the richer
source strategy docs, deterministic Reddit monitor, and Kipi MCP harvest layer.

## Alternatives considered

- **Prompt-only analyst.** Rejected: it does not solve ingestion, repeatability,
  or regression testing.
- **Live Apify-first build.** Rejected: live platform calls make tests flaky and
  block a runnable local demo.
- **Strategy-only script.** Rejected: ASK owns the reusable harvest layer, so the
  clean extraction belongs in `kipi-mcp`.

## Scenarios

- **Weekly market read.** Founder runs the CLI against last week's normalized
  records. The generated Markdown highlights themes where multiple watched
  entities converged, then lists supporting posts.
- **Bad watchlist.** A watchlist entry omits a name. The CLI exits non-zero via
  validation instead of producing a misleading empty report.
- **Future live feed.** `kipi_harvest` stores platform records; a small adapter
  writes normalized records; this analyzer renders the same newsletter.

## Resolved decisions

- **Deterministic core first.** Decided: no LLM dependency in v1. Rationale: the
  analyzer should be testable and explainable before adding synthesis polish.
- **Two-entity threshold.** Decided: a theme becomes a market move when at least
  two watched entities mention it. Rationale: matches the Reddit example without
  requiring a large dataset.
- **Package location.** Decided: `plugins/kipi-core/kipi-mcp`. Rationale: this is
  the existing reusable ingestion and source-manifest package.

## Risks and rollback

- **False convergence:** keyword overlap can overstate a trend. Mitigation: the
  report lists source records under each move so a reviewer can audit evidence.
- **Platform mismatch:** source-specific fields vary. Mitigation: normalized input
  only requires entity, source, url/id, text, and published timestamp.
- **Rollback:** remove the new module, CLI script entry, docs, fixtures, and tests.

## Issues

```json
[]
```
