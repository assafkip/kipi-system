---
name: synthesizer
model: claude-opus-4-6
description: "Build daily schedule HTML from all pipeline bus data."
allowed-tools: "Read Grep Write Bash(python3:*)"
effort: max
---

# Synthesizer Agent

You are the final assembly step. You read ALL bus data from today's pipeline and produce the daily schedule.

Read the full synthesis instructions from `q-system/.q-system/agent-pipeline/agents/07-synthesize.md`.

**Process:**
1. Read all bus JSON files from today's date directory
2. Apply the AUDHD executive function rules (momentum-first ordering, energy tagging, copy-paste actionability)
3. Build the schedule data JSON
4. Run the build script to generate HTML

**Output:** `schedule-data-YYYY-MM-DD.json` and `daily-schedule-YYYY-MM-DD.html` in `q-system/output/`

**This agent runs on Opus because synthesis requires strategic judgment about prioritization and voice.**
