# Q Entrepreneur OS

@q-system/CLAUDE.md

## Project Structure
- `plugins/` - Plugin groups: kipi-core (every instance), kipi-ops (GTM), kipi-design (UI)
- `.claude/agents/` - Custom agent definitions (preflight, data-ingest, synthesizer, etc.)
- `.claude/rules/` - Path-scoped instruction files
- `q-system/` - Core OS (canonical/, marketing/, methodology/, output/, my-project/, memory/)

## Conventions
- All written output goes through the founder voice skill
- All actionable output follows AUDHD executive function rules (if enabled)
- No filler phrases ("leverage," "innovative," "cutting-edge," "game-changing")
- When something fails because an LLM misinterpreted instructions, the fix must be a deterministic script or code change
- For any task involving more than a single file edit, state the planned approach and wait for OK. When fixing identified issues, fix exactly what was flagged. No scope expansion.
- Never read or search files outside the current project directory without stating which directory and why
- All product/system changes use the PRD template at `q-system/marketing/templates/prd.md`

## Commands
- `/q-morning` - The day brief: one Slack message with today's calendar, mail needing an answer, what is owed today, and which overnight jobs failed. Runs itself at 07:40 (`com.kipi.morning-brief`); the command just runs it early. A section that could not be read says COULD NOT READ, never "nothing". If no brief lands by 09:00 a separate job (`com.kipi.morning-brief-deadman`) says so. The 9-phase agent pipeline it replaced is RETIRED (decisions.md RULE-2026-08-30-A)
- `/q-debrief` - Post-conversation extraction (highest priority)
- `/q-calibrate` - Update canonical files
- `/q-create` - Generate specific output (talk tracks, emails, slides, decks)
- `/q-plan` - Review and prioritize actions
- `/q-engage` - Social engagement mode
- `/q-market-*` - Marketing system commands
- `/q-draft` - Ad-hoc output generation. `/improve` - the inverse: critique an outside idea against what this system already has; runs `plugins/kipi-core/skills/improve/scripts/improve_ground.py` first (`already-built` names the file or lesson, `adopt`, or `skip` when the roadmap classifier says what-to-build), corpora via `KIPI_LESSONS_CORPORA` each reported read / missing / unreadable; on demand only
- `/q-wrap` - Evening health check
- `/q-handoff` - Session continuity
- `/q-research` - Anti-hallucination research mode
- `/wiring-check` - End-of-task gate: verify every change is connected end-to-end. Full rule in `.claude/rules/wiring-check.md`
- `/say` - Synthesize the previous assistant response to a stable mp3 via OpenAI TTS. Autoplays locally in a new Terminal window (mpv) so your keys drive speed/seek/pause; over SSH, without mpv, or with `--no-play` it just prints the play command. Manual replay: `mpv ~/.config/kipi/say-last.mp3` (or `say-play`). Over SSH: `ssh <mini> 'cat ~/.config/kipi/say-last.mp3' | mpv -`. `/say stop` clears stray playback.

## Build and Test
- Build daily schedule: `python3 q-system/marketing/templates/build-schedule.py <json> <html>`
- Audit morning routine: `python3 q-system/.q-system/audit-morning.py q-system/output/morning-log-YYYY-MM-DD.json`
- Audit instruction budget: `python3 q-system/.q-system/scripts/instruction-budget-audit.py`
- Develop with plugins: `kipi dev` (loads all 3 plugin groups)
