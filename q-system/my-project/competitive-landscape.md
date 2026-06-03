# Competitive Landscape

> How do prospects solve this problem today? Not "who are your competitors" but "what do they do instead?"

## Substitute Categories <!-- pin -->

### 1. Stuff-it-into-Claude
- **Examples:** Claude chat, ChatGPT, Gemini, ad-hoc LLM use
- **How they solve it:** Paste telegram scrapes, ask LLM to find threat actors and connections
- **Where they fall short:** Context window fills, conversations forget, no cross-investigation memory, hallucinations on large data
- **Switching friction:** Low — analyst can keep using Claude in parallel during eval

### 2. Manual Obsidian / Notion / spreadsheet building
- **Examples:** Ally's "insane Obsidian board", spreadsheet-based investigations
- **How they solve it:** Manually link people/places/events as they read each report
- **Where they fall short:** Doesn't scale past 5-10 reports, doesn't auto-surface cross-report connections, founder-attention-bound
- **Switching friction:** Low — kipi-investigations exports back to Obsidian so prior work isn't wasted

### 3. Enterprise intel platforms
- **Examples:** Palantir, Babel Street, ShadowDragon, Maltego (CE+)
- **How they solve it:** Full-stack OSINT collection + analysis platform
- **Where they fall short:** Pricing locks out boutique/small T&S teams; require integration into customer's data systems; learning curve
- **Switching friction:** N/A — most boutique teams can't access these in the first place

### 4. OSINT aggregator tools
- **Examples:** IOC3 (Kaden's spin-off, $700K + FBI pilot, ~2026), various username-lookup graph tools
- **How they solve it:** Take a username/phone/email; aggregate from N OSINT sources; render in graph
- **Where they fall short:** No compounding investigation memory; one-shot lookups, not multi-report synthesis; don't ingest customer's own reports
- **Switching friction:** Complementary — kipi-investigations can consume IOC3-style output as one of N inputs

## Named Adjacents
- **IOC3 / Kaden's tool** — graph-based OSINT aggregator (closest by surface; we differ on compounding memory)
- **Palantir** — enterprise comparator (we differ on price/deployment/scope)
- **Maltego** — graph tool (we differ on compounding cross-investigation memory)
- **Miro friend's tool** (name TBD per call) — knowledge graph with system integrations (we differ: BYO data, no system integration overhead)

## Key Differentiator <!-- pin -->

**Compounding investigation memory in the analyst's own files.**

Every other tool either: (a) does one-shot lookups, (b) requires customer to integrate their data systems, or (c) costs Palantir money. kipi-investigations is the only thing that takes the analyst's intel reports as input, builds a knowledge graph that compounds across investigations, and outputs to the tool the analyst already uses (Obsidian).

## What Customers Compare Us To (and the correction)
- "Like Palantir?" → No. Boutique-priced, deploy in days, BYO data.
- "Like an OSINT tool?" → No. We take your reports and synthesize. OSINT collection is optional.
- "Like Claude with extra steps?" → Yes — but with persistent memory across investigations and a graph view.
