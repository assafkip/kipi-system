# Agent Pipeline Placeholders

Every agent prompt uses `{{PLACEHOLDER}}` syntax for project-specific values.
Fill these in during setup. The orchestrator substitutes them at runtime.

## Auto-substituted (no action needed)

| Placeholder | Source | Description |
|---|---|---|
| `{{DATE}}` | `date +%Y-%m-%d` | Today's date |
| `{{BUS_DIR}}` | Orchestrator | Path to today's bus directory |
| `{{QROOT}}` | Orchestrator | Project root path |

## Notion Database IDs (fill in `my-project/notion-ids.md`)

| Placeholder | Description |
|---|---|
| `{{NOTION_ACTIONS_DB}}` | Actions/tasks database ID |
| `{{NOTION_PIPELINE_DB}}` | Investor/prospect pipeline database ID |
| `{{NOTION_TRACKER_DB}}` | Social engagement tracker database ID |

## File Paths (standard locations, override if customized)

| Placeholder | Default Value | Description |
|---|---|---|
| `{{CANONICAL_DIR}}` | `q-system/canonical` | Canonical source-of-truth files |
| `{{OUTPUT_DIR}}` | `q-system/output` | Generated output directory |
| `{{MEMORY_DIR}}` | `q-system/memory` | Time-stratified memory directory |
| `{{VOICE_SKILL_PATH}}` | `plugins/kipi-core/skills/founder-voice/SKILL.md` | Voice consistency skill |
| `{{AUDHD_SKILL_PATH}}` | `plugins/kipi-core/skills/audhd-executive-function/SKILL.md` | Actionability skill |
| `{{RESEARCH_SKILL_PATH}}` | `plugins/kipi-core/skills/research-mode/SKILL.md` | Citation-enforced research mode |
| `{{SCHEDULE_SCHEMA_PATH}}` | `q-system/marketing/templates/schedule-data-schema.md` | Daily schedule JSON schema |

## External APIs (fill if using these integrations)

| Placeholder | Description | Required? |
|---|---|---|
| `{{PIPELINE_API_URL}}` | External pipeline/CRM API endpoint (e.g., `http://localhost:5050/api/pipeline`) | Optional |

## Social Platform URLs (fill for social engagement agents)

| Placeholder | Default Value | Description |
|---|---|---|
| `{{LINKEDIN_FEED_URL}}` | `https://www.linkedin.com/feed/` | LinkedIn feed for post scanning |
| `{{LINKEDIN_MESSAGING_URL}}` | `https://www.linkedin.com/messaging/` | LinkedIn DM inbox |
| `{{LINKEDIN_CONNECTIONS_URL}}` | `https://www.linkedin.com/mynetwork/invitation-manager/sent/` | Sent connection requests |
| `{{LINKEDIN_PROFILE_URL}}` | `https://www.linkedin.com/in/` | LinkedIn profile base URL |
| `{{X_FEED_URL}}` | `https://x.com/home` | X/Twitter feed |
| `{{X_DM_URL}}` | `https://x.com/messages` | X/Twitter DM inbox |

## Content & Signals Configuration

| Placeholder | Example | Description |
|---|---|---|
| `{{SIGNAL_SEARCH_TERMS}}` | `"security operations", "threat intel", "SOC"` | Keywords for lead sourcing scrapers |
| `{{RSS_FEED_URLS}}` | `https://feeds.feedburner.com/TheHackersNews` | RSS feeds for signals content |

## Pipeline Rules (configurable thresholds)

| Placeholder | Default | Description |
|---|---|---|
| `{{STALE_DAYS_THRESHOLD}}` | `14` | Days before a no-response lead is flagged stale |
| `{{COLD_CLOSE_DAYS}}` | `14` | Days at 0 engagement before auto-closing a prospect |
| `{{POSITIONING_FRESHNESS_DAYS}}` | `30` | Days before talk tracks are flagged for review |
| `{{PIPELINE_TARGET}}` | `12` | Target number of active prospects in pipeline |
| `{{SIGNAL_WEIGHTING_RULES}}` | See 06-positioning-check.md | How to weight different signal sources |
