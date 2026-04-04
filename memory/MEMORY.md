# Q Entrepreneur OS Memory Index

> First 200 lines load at session start. This is the map to everything the system knows.

## Canonical Files (Source of Truth)
- `q-system/canonical/talk-tracks.md` - Proven language and messaging
- `q-system/canonical/objections.md` - Known pushback + tested responses
- `q-system/canonical/discovery.md` - Questions asked and answered
- `q-system/canonical/decisions.md` - Decision log with origin tags (USER-DIRECTED / CLAUDE-RECOMMENDED)
- `q-system/canonical/market-intelligence.md` - Buyer language, category signals, competitive intel
- `q-system/canonical/engagement-playbook.md` - Social engagement rules + comment strategy
- `q-system/canonical/lead-lifecycle-rules.md` - When to kill/park/re-engage leads
- `q-system/canonical/pricing-framework.md` - Pricing structure and packaging
- `q-system/canonical/verticals.md` - Target vertical definitions
- `q-system/canonical/content-intelligence.md` - Content performance patterns

## Project State
- `q-system/my-project/current-state.md` - What works today (NOT vision)
- `q-system/my-project/founder-profile.md` - Identity, voice, AUDHD accommodations
- `q-system/my-project/relationships.md` - People + conversation history
- `q-system/my-project/competitive-landscape.md` - Substitute buckets
- `q-system/my-project/progress.md` - Session-by-session changes, current mode
- `q-system/my-project/notion-ids.md` - Notion database IDs for API access

## Session State
- `q-system/memory/last-handoff.md` - What was in progress when last session ended
- `q-system/memory/sycophancy-log.json` - Rolling audit of decision bias checks

## Pipeline
- `q-system/output/open-loops.json` - Follow-up loops (open/closed/parked/killed)
- `q-system/output/morning-log-YYYY-MM-DD.json` - Today's pipeline completion state
- `q-system/output/session-effort-YYYY-MM-DD.log` - Turn-by-turn effort tracking

## Metrics Database
- `q-system/.q-system/data/metrics.db` - SQLite (content_performance, outreach_log, copy_edits, behavioral_signals)
- Query via: `python3 q-system/.q-system/data/db-query.py <command> [args]`

## Key Rules (auto-loaded by path)
- Voice enforcement: all written output through founder-voice skill
- AUDHD: friction-ordered, copy-paste-ready, no shame/pressure language
- Anti-misclassification: never describe product as something it's not
- Token discipline: diagnose before retry, 10-call checkpoint, no brute force
- Research mode: `/q-research` toggles citation enforcement, every claim needs a source
