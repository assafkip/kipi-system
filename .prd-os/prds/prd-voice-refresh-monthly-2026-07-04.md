---
id: prd-voice-refresh-monthly-2026-07-04
title: Voice Refresh Monthly
status: idea
created_at: 2026-07-04T23:12:15Z
updated_at: 2026-07-04T23:12:15Z
owner: assafkip
reviewers: []
findings_path: .prd-os/findings/prd-voice-refresh-monthly-2026-07-04-findings.jsonl
---

# Voice Refresh Monthly

## Problem

The founder-voice DNA is enriched from Granola meeting transcripts, but the whole
pipeline is manual. This session hand-drove it end to end (pull, harvest,
synthesize, fingerprint, merge). There is no scheduled trigger, so the voice
skill silently drifts stale as new meetings accrue and the corpus does not grow.

Measurable state today: corpus = 3 meetings / 11.5k words, refreshed only when a
human remembers to do it. Zero automation. The naive fix (a cron job that reruns
the harness) does NOT work: Stage 1 (harvest) needs Granola transcripts, and
Granola is an interactively-authenticated MCP that is not reliably reachable from
a headless launchd/cron context.

## Goals

- A deterministic monthly cadence trigger (launchd, repo-root) that the founder
  cannot forget.
- Headless-safe execution of Stages 2-3 (synthesize + fingerprint) on an existing
  corpus, with no MCP dependency at schedule time.
- The Granola pull (Stage 1) runs where MCP works: inside an interactive session,
  via a `/voice-refresh` command.
- The merge into voice-dna.md stays founder-gated. The pipeline produces a delta
  proposal; a human approves before the voice file changes.
- Orchestration is idempotent and retry-safe (self-healing-retry contract), logs
  every step, and routes founder pings through slack-notify.sh.

## Non-goals

- Fully unattended end-to-end refresh. Impossible and undesirable: the voice-file
  merge is founder-gated by design, so a human is always in the loop.
- Headless Granola MCP. Treated as unavailable; the design routes around it rather
  than trying to make cron authenticate to Granola.
- Auto-writing voice-dna.md. Never. The merge is always a reviewed diff.
- Rebuilding the 3 harness scripts. They exist and are committed; this PRD wires
  scheduling, an interactive command, and orchestration around them.

## Proposed approach

Split the pipeline by where it can run:

```
[monthly launchd nudge]  --slack-notify-->  founder
        (repo-root, no MCP)                    |
                                               v
                                 /voice-refresh  (interactive session, MCP OK)
                                     |  Stage 1 harvest (pull + Me: extract)
                                     v
                          voice-refresh orchestrator  (headless-safe)
                                     |  Stage 2 synthesize (claude -p)
                                     |  Stage 3 fingerprint (pure python)
                                     v
                            delta proposal  --founder-gated-->  merge to voice-dna.md
```

Decomposition (formalized into the Issues block at split time):
1. Orchestrator script (repo-root, e.g. `automation/voice-refresh.sh` +
   python core): chains Stages 2-3 over a corpus dir, idempotent, retry-safe per
   the self-healing-retry contract, logs each step. Reproducer: a pytest that runs
   it on a fixture corpus and asserts corpus/findings/fingerprint outputs.
2. `/voice-refresh` interactive command: pulls the last month of Granola meetings,
   runs Stage 1 harvest, invokes the orchestrator, and presents the delta as a
   gated merge proposal. Reproducer: a validator test on the command file
   (frontmatter, registration, no auto-write of voice-dna.md).
3. Monthly launchd nudge (repo-root plist + installer): fires slack-notify.sh so
   the founder cannot forget. Reproducer: a test validating the plist XML and that
   the nudge script routes through slack-notify.sh only (no osascript).

## Risks and rollback

- MCP auth drift: if Granola auth lapses, Stage 1 fails inside the session. Mitigation:
  the command surfaces the failure to the founder (self-healing-retry stops on
  environmental-trigger, attempt 1). No silent stale merge.
- Corpus contamination (degraded diarization). Already mitigated: harvest ships the
  >700-word warn-flag that caught the Chris transcript. Flagged meetings need a human
  eyeball before Stage 2.
- Critic non-determinism: the Stage 2 adversarial critic flip-flops run to run.
  Mitigation deferred: majority-vote (run 3x, keep survivors) is a v2 hardening,
  noted as an open question.
- launchd job silent death (the income-scanner scar). Mitigation: register with the
  launchd-health watchdog so a dead nudge pings the founder.
- Rollback: all additive. Disable/remove the plist and the scripts; nothing in the
  existing voice skill or the 3 harness scripts changes. voice-dna.md is only ever
  touched by a reviewed merge, so a bad run cannot corrupt the voice file.

## Open questions

- Cadence: which day of the month, and what lookback window (last 30 days vs since
  last refresh)?
- Corpus growth: does each refresh REPLACE the corpus or ACCRETE (keep old meetings
  + add new)? Accretion grows signal but risks stale-voice drift over years.
- Majority-vote critic now or v2?
- Warn-flagged meetings: auto-exclude, or include after a surfaced human review?

## Issues

<!--
After review and approval, populate the fenced JSON block below with one
entry per atomic issue. `prd_split.py` reads this block verbatim and writes
one issue spec per entry.

Required keys per entry:
  - id (kebab-case, unique across the repo)
  - title (non-empty string)
  - allowed_files (non-empty list of glob patterns)
  - required_checks (non-empty list, e.g. ["pytest -q"]). The runner's
    stop-gate checks that three receipts are marked (verified, reviewed,
    findings_triaged). Those receipts are meaningless unless the spec
    documents what must be verified, so an empty list is rejected.

Optional keys:
  - priority (default p1)
  - disallowed_files, required_reviews, acceptance

IDs must match the repo's issue naming convention and must not collide with
existing issue specs.
-->

```json
[]
```
