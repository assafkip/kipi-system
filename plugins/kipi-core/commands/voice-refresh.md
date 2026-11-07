---
description: Refresh the founder-voice DNA from new Granola meetings (interactive, MCP-backed). Pulls meetings since the last refresh, harvests Assaf-only speech, runs the Stage 2-3 orchestrator, and presents a founder-gated delta. Never auto-writes voice-dna.md.
argument-hint: "[optional: since YYYY-MM-DD to override the lookback]"
---

# /voice-refresh

Interactive monthly refresh of the founder-voice skill. This command runs in a
session because Stage 1 needs the Granola MCP, which is not reachable headless.
PRD prd-voice-refresh-monthly-2026-07-04.

## Steps

1. **Determine lookback.** Read `automation/.voice-refresh-last` (an ISO-8601 UTC
   instant). Lookback = since that timestamp; if missing, last 30 days. An
   explicit `since <date>` argument overrides. The orchestrator in step 4 writes
   that file itself, so do not write it here and do not treat its absence as
   normal: a missing stamp after a completed run is a defect, not a first run.

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
   It emits `q-system/output/voice-corpus/voice-delta.md`, stamps
   `automation/.voice-refresh-last`, and writes
   `automation/.voice-delta-pending` when the delta has a personal half.

5. **Ship the two halves separately.** `voice-delta.md` is split:

   - **Routine.** Style patterns. Merge them through a reviewed PR without
     waiting on the founder: edit the skeleton `voice-dna.md`, bump the
     kipi-core `plugin.json` version, commit, open the PR, and let review run.
     Never push them straight to main.
   - **Personal.** Patterns mined from a personal disclosure (layoffs, a
     mental-health leave, health, family, money). `voice-dna.md` fans out to
     every instance, so these are FOUNDER-GATED: show the block and ask for one
     short yes/no covering it, in the same turn, never as a wait-for-approval
     turn of its own. On a yes, merge via the same PR flow. On a no, drop them.
   - After he answers either way, write the current ISO-8601 UTC instant to
     `automation/.voice-delta-answered`. That is what stops the 7-day
     unanswered-delta alert; nothing clears it on its own.

6. **Do not stamp by hand.** Step 4 already wrote
   `automation/.voice-refresh-last`. It is stamped on every completed run
   including a no-op, and deliberately NOT stamped on a refusal. Writing it here
   is the ASK-3405 defect: the stamp used to hang off the founder-gated merge, so
   it never landed and the lookback fell back to 30 days every run.

## Hard rule

`voice-dna.md` is only ever changed by a reviewed merge: a PR for the routine
half, a founder yes plus a PR for the personal half. This command never edits it
directly, and the orchestrator never opens it at all. Report flagged/excluded
meetings so a good one can be hand-rescued.

## If nobody answers

`voice-refresh-nudge.sh` runs `voice_refresh.py --stale-check` on its monthly
timer. Seven days after a delta with a personal half goes unanswered, that prints
one line, which `slack-notify.sh` files into Sana's Linear triage. It fires once
per delta, never per run.
