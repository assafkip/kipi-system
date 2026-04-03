# Bus Protocol v1

## Overview

The inter-agent bus is a file-based JSON message passing layer for the morning pipeline. Agents communicate exclusively through JSON files in `bus/{date}/`, enabling parallel execution, fault isolation, and deterministic validation.

## Envelope

Every bus file MUST include these fields:

```json
{
  "bus_version": 1,
  "date": "YYYY-MM-DD",
  "generated_by": "agent-name",
  ...agent-specific fields...
}
```

- `bus_version` - Integer. Current version: 1. Bump when adding required fields.
- `date` - ISO date string matching the bus directory name.
- `generated_by` - Agent filename without extension (e.g., "01-calendar-pull").

## File Naming

- kebab-case for all filenames (e.g., `linkedin-posts.json`, `prospect-pipeline.json`)
- One file per logical concept (not per agent)
- No timestamps in filenames (date is implicit from directory)
- Files are overwritten each run (fresh state daily)

## Directory Structure

```
bus/
└── YYYY-MM-DD/
    ├── preflight.json           # Phase 0
    ├── energy.json              # Phase 0
    ├── bootstrap.json           # Phase 0
    ├── canonical-digest.json    # Phase 0 (script)
    ├── calendar.json            # Phase 1
    ├── gmail.json               # Phase 1
    ├── notion.json              # Phase 1
    ├── meeting-prep.json        # Phase 2
    ├── warm-intros.json         # Phase 2
    ├── linkedin-posts.json      # Phase 3
    ├── linkedin-dms.json        # Phase 3
    ├── prospect-pipeline.json   # Phase 3
    ├── signals.json             # Phase 4
    ├── temperature.json         # Phase 5 (script)
    ├── leads.json               # Phase 5
    ├── hitlist.json             # Phase 5 (Opus)
    ├── compliance.json          # Phase 6 (script)
    ├── positioning.json         # Phase 6
    ├── sycophancy-audit.json    # Phase 6
    └── schedule-data-*.json     # Phase 7 (Opus, output/)
```

## Phase Ownership

| Phase | Agent | Writes | Reads |
|-------|-------|--------|-------|
| 0 | 00-preflight | preflight.json | (tools only) |
| 0 | 00b-energy-check | energy.json | (founder input) |
| 0 | 00-session-bootstrap | bootstrap.json | last-handoff.md |
| 0 | canonical-digest.py | canonical-digest.json | canonical/ files |
| 1 | 01-calendar-pull | calendar.json | (Calendar API) |
| 1 | 01-gmail-pull | gmail.json | (Gmail API) |
| 1 | 01-notion-pull | notion.json | (Notion API) |
| 2 | 02-meeting-prep | meeting-prep.json | calendar.json, notion.json |
| 2 | 02-warm-intro-match | warm-intros.json | vc-pipeline.json, notion.json |
| 3 | 03-linkedin-posts | linkedin-posts.json | (Chrome/Apify) |
| 3 | 03-linkedin-dms | linkedin-dms.json | (Chrome/Apify) |
| 3 | 03-prospect-pipeline | prospect-pipeline.json | notion.json |
| 4 | 04-signals-content | signals.json | linkedin-posts.json, x-activity.json |
| 5 | temperature-scoring.py | temperature.json | notion.json, linkedin-*, gmail.json |
| 5 | 05-engagement-hitlist | hitlist.json | temperature.json, leads.json, linkedin-*, pipeline-followup.json, loop-review.json |
| 6 | compliance-check.py | compliance.json | canonical/ files |
| 6 | 06-positioning-check | positioning.json | canonical/ files |
| 6 | 06-sycophancy-audit | sycophancy-audit.json | ALL bus/*.json, decisions.md |
| 7 | 07-synthesize | schedule-data-*.json | ALL bus/*.json |

## Validation Layers

1. **JSON Schema** (`schemas/*.schema.json`) - Structure, types, required fields, enums. Checked by verify-bus.py. Currently WARN-only during migration.
2. **Domain checks** (verify-bus.py lambdas) - Business logic that schemas can't express (e.g., hitlist actions length > 0).
3. **Sycophancy harness** (sycophancy-harness.py) - Independent non-LLM verification of Phase 6 audit.
4. **bus-to-log.py** - Consumption-time validation when mapping bus files to morning-log steps.

## Error Convention

Agents that fail write:
```json
{
  "bus_version": 1,
  "date": "YYYY-MM-DD",
  "generated_by": "agent-name",
  "error": "Human-readable error message"
}
```

- Required files with `"error"` key: FAIL (pipeline halts or uses fallback)
- Optional files with `"error"` key: WARN (downstream agents handle gracefully)
- Missing optional files: SKIP (not counted as failure)

## Cadence Rules

Day-of-week rules are in `agents/_cadence-config.json` (single source of truth). verify-bus.py reads this file to determine which optional files become required on specific days.

- Monday: content-intel.json required (Phase 3)
- Tuesday/Thursday: tl-content.json required (Phase 4)
- Weekly brand day: founder-brand-post.json (Phase 4)
- 1st of month: Extra bootstrap checks (monthly audit)

## Schema Versioning

- Current `bus_version`: 1
- Bump bus_version when: adding new required fields, changing field types, removing fields
- Do NOT bump for: adding optional fields, adding new bus files
- verify-bus.py rejects files with mismatched bus_version
- Schema files in `schemas/` are the source of truth for structure
