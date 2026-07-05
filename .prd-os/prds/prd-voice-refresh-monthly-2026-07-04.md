---
id: prd-voice-refresh-monthly-2026-07-04
title: Voice Refresh Monthly
status: archived
created_at: 2026-07-04T23:12:15Z
updated_at: 2026-07-05T00:08:12Z
owner: assafkip
reviewers: []
findings_path: .prd-os/findings/prd-voice-refresh-monthly-2026-07-04-findings.jsonl
codex_reviewed_at: 2026-07-04T23:17:18Z
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

## Resolved decisions (were open questions; founder-approved 2026-07-04)

- Cadence + lookback: nudge on the 1st of each month. Lookback = "since last
  refresh," tracked by a timestamp file (`automation/.voice-refresh-last`),
  falling back to last 30 days if the timestamp is missing. No gaps, no
  double-counting.
- Corpus growth: ACCRETE with a rolling 12-month window. New meetings append;
  meetings older than 12 months age out, so signal grows without letting a
  3-year-old voice outvote current-Assaf.
- Majority-vote critic: v2. Deferred, tracked here, not built. Stage 2 stays
  single-pass for now.
- Warn-flagged meetings (degraded diarization): AUTO-EXCLUDE from the corpus AND
  list them in the run report, so a good one can be hand-rescued.

## Decisions addressing Codex review

- Freshness SLA: the voice skill is stale after 45 days without a refresh
  (monthly cadence + 15-day grace). launchd-health covers a dead nudge.
- Orchestrator WRAPS the three existing scripts (harvest, synthesize,
  fingerprint); never modifies them. They stay in `q-system/.q-system/scripts/`.
  Only NEW automation (orchestrator, nudge, plist, installer) lives at repo-root
  `automation/`, per the instance-automation rule. Resolves the repo-layout
  tension: interactive command is a plugin command (propagates by design);
  scheduled automation is instance-local repo-root.
- Stage 2 headless dependency: the orchestrator checks `claude -p` availability
  first; if absent it stops with an `environmental-trigger` diagnosis. No silent
  stale merge.
- Contamination gate is ENFORCING, not advisory: the orchestrator REFUSES Stage 2
  on any corpus containing a review-flagged (>700-word turn) meeting.
- Merge mechanics: the pipeline emits a delta file
  (`q-system/output/voice-corpus/voice-delta.md`) proposing changes against
  `voice-dna.md`. `/voice-refresh` surfaces it for approval; on approval the same
  commit + plugin-version-bump + marketplace-pull flow used this session applies.
  voice-dna.md is never written unattended.
- Prior-art reuse: the nudge reuses the lessons-daily launchd + slack-notify +
  launchd-health patterns, not a second scheduling style.

## Issues

```json
[
  {
    "id": "voice-refresh-orchestrator",
    "title": "Repo-root orchestrator chaining Stages 2-3 over a corpus, idempotent and retry-safe",
    "finding_id": "finding-4",
    "allowed_files": ["automation/voice_refresh.py", "automation/test_voice_refresh.py"],
    "required_checks": ["python3 -m pytest automation/test_voice_refresh.py -q"],
    "bypass_check": "python3 -m pytest automation/test_voice_refresh.py -q -k contamination_or_headless",
    "acceptance": "WRAPS (never modifies) granola-voice-synthesize.py + granola-voice-fingerprint.py; checks claude -p availability and stops with an environmental-trigger diagnosis if absent; REFUSES Stage 2 on any corpus containing a review-flagged (>700-word turn) meeting; logs each step; a second run on an unchanged corpus is a no-op."
  },
  {
    "id": "voice-refresh-command",
    "title": "/voice-refresh interactive command: Granola pull, harvest, orchestrate, gated merge proposal",
    "finding_id": "finding-7",
    "allowed_files": ["plugins/kipi-core/commands/voice-refresh.md", "automation/test_voice_refresh_command.py"],
    "required_checks": ["python3 automation/test_voice_refresh_command.py"],
    "bypass_check": "python3 automation/test_voice_refresh_command.py",
    "acceptance": "Pulls since-last-refresh Granola meetings, runs harvest, invokes the orchestrator, emits a voice-delta.md proposal; NEVER writes voice-dna.md directly; test asserts frontmatter, CLAUDE.md registration, and no voice-dna.md write path."
  },
  {
    "id": "voice-refresh-schedule",
    "title": "Monthly launchd nudge (repo-root) via slack-notify.sh, registered with launchd-health",
    "finding_id": "finding-9",
    "allowed_files": ["automation/voice-refresh-nudge.sh", "automation/com.kipi.voice-refresh.plist", "automation/install-voice-refresh.sh", "automation/test_voice_refresh_schedule.py"],
    "required_checks": ["python3 automation/test_voice_refresh_schedule.py"],
    "bypass_check": "python3 automation/test_voice_refresh_schedule.py",
    "acceptance": "plist is valid XML scheduling the nudge on the 1st monthly; nudge routes the founder ping ONLY through slack-notify.sh (no osascript); installer registers with launchd-health; test asserts all three."
  }
]
```
