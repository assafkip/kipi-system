# Instance Operating Guide

Every instance operates independently with the same skeleton structure, rules, and sanitation from kipi-system. No instance depends on another to function.

## Active Instances

### KTLYST_strategy
- **Purpose:** GTM strategy, fundraising, VC pipeline, design partner program
- **Plugins:** core + ops + design (recommended)
- **Skeleton:** subtree at `q-system/`
- **Instance content:** `q-ktlyst/` (canonical, my-project, marketing, memory)
- **Includes:** VC_Reachout (merged 2026-03-26 as `q-ktlyst/vc-sourcing/`)
- **Daily:** `/q-morning`, paste meeting transcripts for auto-debrief
- **Weekly:** `/q-market-plan`, `/q-content-intel`, `/q-reality-check`

### ktlyst
- **Purpose:** Product development, technical architecture, website code
- **Plugins:** core + design
- **Skeleton:** subtree at `q-system/`
- **Instance content:** none (product code IS the instance)
- **Daily:** Development workflow, not morning routine
- **When to use:** Building features, fixing bugs, writing tests

### ASK_AI_consultant
- **Purpose:** AI consulting practice (ASK Consulting / askconsulting.io)
- **Plugins:** core + ops + design
- **Skeleton:** subtree at `q-system/`
- **Instance content:** `q-consult/` (canonical, my-project, marketing, memory)
- **Daily:** `/q-morning`, client deliverable tracking, pipeline follow-ups
- **Weekly:** `/q-market-plan`, invoice prep, client health checks

### q-education
- **Purpose:** Learning content, educational material creation
- **Plugins:** core
- **Skeleton:** subtree at `q-system/`
- **Instance content:** none yet
- **Daily:** Content creation workflow
- **When to use:** Building courses, writing educational content

### ktlyst-website
- **Purpose:** KTLYST marketing site (Vercel-deployed)
- **Plugins:** core + design
- **Skeleton:** subtree at `q-system/`
- **Instance content:** site code (Next.js/HTML)
- **Daily:** Not routine-driven. Use for site updates, landing pages, content publishes.

### car-research
- **Purpose:** Personal car lease research
- **Plugins:** core (minimal)
- **Skeleton:** direct clone of kipi-system
- **Daily:** Ad-hoc research sessions
- **Note:** Direct clone, updates via `git pull` not subtree

### client_a
- **Purpose:** Threat intelligence investigation for client-a
- **Plugins:** core (custom OSINT skill at `q-investigate/`)
- **Skeleton:** NOT connected (custom architecture)
- **Daily:** Investigation-driven, not routine-driven
- **Note:** Has its own OSINT pipeline with 55+ Apify actors
- **Action needed:** Register in instance-registry.json

### client_b
- **Purpose:** Strategic advisory engagement hub for client-b (fraud/threat intel)
- **Plugins:** core (custom `.q-system/`)
- **Skeleton:** NOT connected (custom architecture, predates skeleton)
- **Daily:** Client project management, 5 consulting workstreams
- **Note:** Has its own commands.md and state model
- **Action needed:** Register in instance-registry.json

### VC_Reachout
- **Purpose:** VC sourcing and outreach
- **Status:** Merged into KTLYST_strategy on 2026-03-26
- **Location:** `/Users/assafkip/Desktop/assafs_qs/VC_Reachout` (archive)
- **Content lives at:** `KTLYST_strategy/q-ktlyst/vc-sourcing/`

## Combination Candidates

| Candidate | Recommendation | Reason |
|-----------|---------------|--------|
| ktlyst + ktlyst-website | Keep separate | Different concerns (product code vs marketing site) |
| KTLYST_strategy + ktlyst | Keep separate | Strategy/GTM is distinct from product dev |
| client_a | Register, don't merge | Custom OSINT architecture, no skeleton overlap |
| client_b | Register, don't merge | Custom architecture, active client engagement |
| car-research | Keep as-is | Lightweight personal use, minimal overhead |

No instances should be combined or retired without your explicit approval.

## Multi-Instance Design

Each instance is fully independent:
- **Separate CRM:** Each instance has its own Notion databases (or none)
- **Separate canonical:** Each instance has its own positioning, talk tracks, objections
- **Shared skeleton:** All get the same agents, scripts, rules, hooks via `kipi update`
- **Shared plugins:** All get kipi-core. Ops and design are opt-in per instance.

Cross-instance awareness happens through you, not through the system. The system doesn't sync data between instances.

## Per-Instance Cheat Sheet

### Routine instances (KTLYST_strategy, ASK_AI_consultant)

```
Morning:    /q-morning
After call: paste transcript (auto-debriefs)
Weekly:     /q-market-plan, /q-content-intel
Monthly:    /q-reality-check
End of day: /q-wrap
```

### Product instances (ktlyst, ktlyst-website)

```
No morning routine. Use for development tasks.
After design changes: invoke kipi-design skills
After meetings about product: /q-debrief
```

### Research instances (car-research, q-education)

```
No routine. Ad-hoc sessions.
/q-research [topic] for citation-verified research
```

### Client instances (client_a, client_b)

```
These have custom workflows, not skeleton commands.
client_a: /q-osint, /q-collect (OSINT pipeline)
client_b: custom .q-system/commands.md
```

## Plugin Assignments

| Instance | core | ops | design |
|----------|------|-----|--------|
| KTLYST_strategy | yes | yes | yes |
| ktlyst | yes | no | yes |
| ASK_AI_consultant | yes | yes | yes |
| q-education | yes | no | no |
| ktlyst-website | yes | no | yes |
| car-research | yes | no | no |
| client_a | yes | no | no |
| client_b | yes | no | no |

To enable plugins in an instance, add to `.claude/settings.json`:
```json
{
  "enabledPlugins": {
    "kipi-core@kipi": true,
    "kipi-ops@kipi": true,
    "kipi-design@kipi": true
  }
}
```

## Registering Unregistered Instances

client_a and client_b exist on disk but are not in `instance-registry.json`. To register them (without connecting to skeleton):

```bash
# From kipi-system directory, add to instance-registry.json:
# type: "standalone" (no subtree, no direct-clone)
```

This lets `kipi check` and `kipi list` see them without trying to sync skeleton content.
