---
description: Refresh the founder-voice DNA from new Granola meetings (interactive, MCP-backed). Pulls meetings since the last refresh, harvests Assaf-only speech, runs the Stage 2-3 orchestrator, and presents a founder-gated delta. Never auto-writes voice-dna.md.
argument-hint: "[optional: since YYYY-MM-DD to override the lookback]"
---

# /voice-refresh

Interactive monthly refresh of the founder-voice skill. This command runs in a
session because Stage 1 needs the Granola MCP, which is not reachable headless.
PRD prd-voice-refresh-monthly-2026-07-04.

## Steps

1. **Determine lookback.** Read `automation/.voice-refresh-last`. Lookback =
   since that timestamp; if missing, last 30 days. An explicit `since <date>`
   argument overrides.

2. **Pull (Stage 1, MCP).** List Granola meetings in the window and pull each
   transcript. Write the usable ones to the corpus input dir. Then run:
   `python3 q-system/.q-system/scripts/granola-voice-harvest.py <input_dir> q-system/output/voice-corpus`
   The harvest isolates `Me:` speech and flags any degraded-diarization meeting.

3. **Accrete, do not replace.** Keep meetings from the last 12 months; age out
   older ones. New meetings append to the corpus input dir.

4. **Orchestrate (Stages 2-3, headless-safe).** Run:
   `python3 automation/voice_refresh.py q-system/output/voice-corpus`
   It REFUSES to proceed if any meeting is review-flagged (contamination gate),
   and STOPS with an environmental-trigger diagnosis if `claude` is unavailable.
   It emits `q-system/output/voice-corpus/voice-delta.md`.

5. **Present the delta (FOUNDER-GATED).** Show `voice-delta.md` to the founder.
   Do NOT write `voice-dna.md`. On approval, merge via the same flow used to ship
   the voice skill: edit the skeleton `voice-dna.md`, bump the kipi-core
   plugin.json version, commit, push, pull the marketplace clone.

6. **Stamp.** On a completed run, write the current timestamp to
   `automation/.voice-refresh-last`.

## Hard rule

`voice-dna.md` is only ever changed by a reviewed merge the founder approves.
This command never edits it directly. Report flagged/excluded meetings so a good
one can be hand-rescued.
