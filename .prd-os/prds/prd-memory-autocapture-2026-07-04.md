---
id: prd-memory-autocapture-2026-07-04
title: Memory Outcome Auto-Capture (the referee)
status: archived
created_at: 2026-07-04T20:59:26Z
updated_at: 2026-07-04T21:39:15Z
owner: assafkipnis
reviewers: []
findings_path: .prd-os/findings/prd-memory-autocapture-2026-07-04-findings.jsonl
codex_reviewed_at: 2026-07-04T21:04:12Z
---

# Memory Outcome Auto-Capture (the referee)

> Source design doc: `q-system/output/prd-memory-autocapture-2026-07-04.md`
> (authored 2026-07-04). This spec transcribes that contract into the gated
> format. Parent: `prd-memory-outcome-scoring-2026-07-04` (PR #6, merged `49e7cd2`).
> Resolves spillover `sp-04006168`.

## Problem

Earned-trust scoring is live fleet-wide but **inert**. `memory_reflect.py` scores
memories from `q-system/memory/outcomes.jsonl`; that log is fed ONLY by the manual
CLI (`memory_outcomes.py <memory_id> <outcome> ...`). Nothing observes a session
and records "this recalled memory was useful / a dead end / corrected." So the
earned-trust surface stays silent forever unless a human hand-feeds it, which
will not happen at the cadence needed to earn signal.

Measurable done: the outcomes log fills itself from real sessions on the
design-partner instance (`4_points_consulting`), with signal good enough that
`memory_reflect` promotes genuinely-useful memories to `preferred` and demotes
contradicted ones to `dead_end` / `contested` without a human typing a CLI command.

## Goals

- Auto-populate `outcomes.jsonl` from real sessions with `useful` / `dead_end` /
  `corrected` signals, no human CLI call required.
- Every write goes through the existing single writer `memory_outcomes.record_outcome`
  with a content-hash `event_id`, idempotent on replay, zero direct log writes.
- Deterministic-first: LLM judgment used only where structurally required (the
  `corrected` path), everything else is unit-testable proxy logic.
- Silent-safe: a capture bug or a missing artifact never blocks a session close.
- Design-partner rollout on `4_points_consulting` only.

## Non-goals

- No change to `memory_reflect` scoring math (shipped in PR #6, out of scope).
- No fleet-wide enable in this PRD; deferred to a post-tuning propagation step.
- No per-session full-sweep classification over every session (Option A, rejected below).
- No new outcome *types* beyond the three the scoring engine already consumes.

## Proposed approach

**Option C, Hybrid: deterministic candidate-gen + judge ONLY on the corrected
path.** Deterministic proxies emit `useful` / `dead_end` (high-volume,
noise-tolerant). The one outcome where semantics are load-bearing, `corrected`,
routes through the ALREADY-SHIPPED `learn-from-correction` skill.

The load-bearing insight: `memory_reflect.aggregate` already tolerates noisy input
by design, a `>= 2` distinct-`event_id` corroboration gate for `preferred`,
signed time-decay (a fresh reversal outweighs a stale one-off), and a `contested`
bucket for both-signs memories. So auto-capture does not need to be a precise
judge; it needs to be an approximately-unbiased signal generator. The scoring
engine is the noise filter. That is what makes the cheap path sufficient.

Components:

1. **New artifact `q-system/memory/.session-recall.json`** (gitignored,
   session-scoped), the surfaced set. Records which memories were actually
   recalled this session so capture can only score a recalled memory.
   - Producer: the SessionStart surface scripts (`memory-scores-surface.py`,
     `memory-confidence-surface.py`) append the `memory_id`s they surfaced, via a
     single-writer helper (same discipline as `memory_outcomes`).
   - Consumer: the Stop-hook capture reads it for the candidate set, then rotates it.
   - Schema: `{ "session_id": str, "surfaced": [ {memory_id, source_file, surfaced_at} ] }`.

2. **New `q-system/.q-system/scripts/memory_autocapture.py`**, Stop-hook entry.
   Reads `.session-recall.json` + the session tool-transcript, emits deterministic
   `useful` / `dead_end` via `record_outcome`. No LLM. Proxies:
   - `useful` = a surfaced memory's `source_file` was read this session.
   - `dead_end` = surfaced, source never touched.
   - (`corrected` is NOT emitted here, it is the correction skill's job.)

3. **`corrected` via the correction skill.** `plugins/kipi-core/skills/learn-from-correction/SKILL.md`
   already fires when the founder contradicts a belief. When the contradicted
   belief maps to a surfaced `memory_id`, it calls `record_outcome(..., "corrected", ...)`.
   Conservative: no confident map → no write.

4. **Wiring.** `.claude/settings.json` + `settings-template.json` add
   `memory_autocapture.py` to the Stop hook group, guarded and advisory
   (`test -f && python3 ... 2>/dev/null || true`).

## Alternatives considered

- **Option A: Stop-hook full-sweep judge.** A Stop hook runs `claude -p` over each
  session and classifies every surfaced memory. Rejected: a real Opus/Sonnet call
  every session (fleet-wide token cost), non-deterministic, and it violates the
  deterministic-first law for the ~80% of the job that needs no semantics.
- **Option B: proxy-only, no semantic judgment at all.** Same proxies for
  useful/dead_end, but also force `corrected` from a file-edit proxy. Rejected:
  the proxy misses conversational correction (founder says "no, that changed"
  without touching the file), the one place semantics are actually load-bearing.
  Option C keeps B's cheap paths and adds the existing correction path only there.

## Scenarios

- **Deterministic `useful`.** SessionStart surfaces memory M (source_file F);
  during the session F is read; at Stop, `memory_autocapture.py` reads
  `.session-recall.json`, sees F was read, calls `record_outcome(M, "useful", ...)`.
  One line, stable `event_id`.
- **Deterministic `dead_end`.** SessionStart surfaces memory N (source_file G); G
  is never touched; at Stop, capture writes one `dead_end` for N.
- **`corrected`.** SessionStart surfaces memory M; the founder contradicts M's
  belief mid-session; `learn-from-correction` maps the contradiction to M's
  `memory_id` and calls `record_outcome(M, "corrected", ...)`.
- **Idempotent replay.** Re-running capture on the same session writes ZERO new
  lines (content-hash `event_id` dedup at the single writer holds end-to-end).
- **Silent-safe close.** No `.session-recall.json`, no transcript → the Stop hook
  exits 0 and writes nothing. Session close never blocked.
- **End-to-end trust move.** A design-partner-realistic session set is fed
  through capture; `memory_reflect` then moves at least one memory to `preferred`
  and one to `dead_end` purely from auto-captured outcomes.

## Resolved decisions

- **Architecture: hybrid (Option C), not a full LLM sweep.** Decided: deterministic
  proxies for useful/dead_end, correction-skill for corrected. Rationale: the
  scoring engine is already the noise filter (corroboration gate + signed decay +
  contested bucket), so a precise judge is unjustified cost; deterministic-first
  law wants LLM judgment only where structurally required.
- **Single writer.** Decided: capture NEVER writes `outcomes.jsonl` directly; all
  writes go through `record_outcome`. Rationale: content-hash `event_id` dedup and
  scope-boundary enforcement live at that chokepoint (lesson `single-writer-chokepoint`).
- **Surfaced set is a new session-scoped artifact.** Decided: `.session-recall.json`
  with a producer (surface scripts) and consumer (capture). Rationale: capture can
  only score a memory that was actually recalled; nothing records that today.
- **Rollout: design-partner first.** Decided: enable on `4_points_consulting` only;
  fleet propagation deferred. Rationale: 27 live cases = highest memory reuse and
  highest cost of a stale memory; tune proxy thresholds against real signal before
  the fleet pays for them.

## Risks and rollback

- **`useful` proxy over-fires.** "source_file was read" may fire for unrelated
  reads. Mitigation: the corroboration gate needs 2 distinct `event_id`s and decay
  ages out one-offs; threshold is tunable at the design-partner step. Codex-review
  the threshold.
- **Stop-hook transcript access.** If the Stop hook cannot read the session tool
  log deterministically (path/format), `useful` falls back to a narrower signal
  (source_file `mtime` changed within the session window). Confirmed at build.
- **`corrected` mapping precision.** Linking a correction to a specific surfaced
  `memory_id` is the semantic step. Kept conservative: no confident map → no write.
  A missed `corrected` is safe; a wrong one is a cheap −1 the decay + gate absorb.
- **Rollback.** Everything is behind a guarded, advisory Stop-hook entry on one
  instance. Back out = remove the one settings entry; the artifact is gitignored
  and session-scoped, and no scoring math changed. Blast radius = one instance's
  outcomes log, which the scoring engine already treats as noisy input.

## Open questions

- Is "source_file was read" the right `useful` proxy, or too generous? (Tune at
  design-partner step; Codex-review the threshold.)
- Exact Stop-hook transcript path/format on this harness, confirm at build; else
  use the mtime fallback.

## Persona Review

### Skeptic

Q1: What is the strongest argument against doing this?
A1: The proxies are coarse enough that the log could fill with mostly-noise
`useful` signals that swamp the real ones. The rebuttal is structural, not
hopeful: the corroboration gate (2 distinct events) plus signed time-decay means
a single spurious `useful` cannot mint trust, and any contradicting `dead_end`/
`corrected` outweighs a stale `useful`. If that turns out false in practice, the
design-partner-only rollout catches it before the fleet pays.

Q2: What is the smallest experiment that would disprove the thesis?
A2: Run capture over one week of real `4_points_consulting` case work and check
whether `memory_reflect`'s `preferred`/`dead_end` verdicts match founder
intuition. A mismatch (memories the founder knows are stale scored `preferred`)
disproves "proxies are approximately-unbiased."

Q3: What is the cheapest non-build alternative?
A3: Keep the manual `memory_outcomes.py` CLI and ask the founder to hand-feed
outcomes. Rejected in the problem statement: it will not happen at the cadence
needed, which is the whole reason the surface is inert today.

## Issues

```json
[
  {
    "id": "autocapture-recall-artifact",
    "finding_id": "finding-5",
    "title": "Session-scoped .session-recall.json: single-writer producer + schema + atomic keyed write",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/session_recall.py",
      "q-system/.q-system/scripts/memory-scores-surface.py",
      "q-system/.q-system/scripts/memory-confidence-surface.py",
      "q-system/.q-system/scripts/test_session_recall.py",
      "q-system/memory/schemas/session-recall.schema.json",
      ".gitignore"
    ],
    "required_checks": ["python3 q-system/.q-system/scripts/test_session_recall.py"],
    "bypass_check": "python3 q-system/.q-system/scripts/test_session_recall.py",
    "acceptance": "Surface scripts append surfaced memory_ids via a single-writer helper. .session-recall.json is keyed by session_id and written atomically (temp+rename); overlapping sessions never mix or truncate each other. A test drives a surface script with a seeded sidecar and asserts .session-recall.json lists exactly the surfaced ids for that session_id. Artifact is gitignored. Schema documented."
  },
  {
    "id": "autocapture-capture-core",
    "finding_id": "finding-4",
    "title": "memory_autocapture.py Stop-hook: deterministic useful/dead_end via record_outcome, transcript-or-mtime read",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/memory_autocapture.py",
      "q-system/.q-system/scripts/test_memory_autocapture.py"
    ],
    "required_checks": ["python3 -m pytest q-system/.q-system/scripts/test_memory_autocapture.py -q"],
    "bypass_check": "python3 -m pytest q-system/.q-system/scripts/test_memory_autocapture.py -q",
    "acceptance": "Reads .session-recall.json + the session tool-transcript; emits useful (source_file read this session) and dead_end (surfaced, source never touched) ONLY through memory_outcomes.record_outcome, never writing outcomes.jsonl directly. Transcript path is confirmed at build; if unavailable the useful proxy falls back to source_file mtime-changed-within-session-window (this fallback and its threshold are owned here, covering rejected finding-7). Idempotent: re-running on the same session writes ZERO new lines (content-hash event_id dedup). Silent-safe: no sidecar and no transcript means exit 0, zero writes. Self-gates OFF unless the current instance is allowlisted (default off), so it is inert on the skeleton and every non-partner instance."
  },
  {
    "id": "autocapture-corrected-path",
    "finding_id": "finding-6",
    "title": "corrected outcome via learn-from-correction: conservative memory_id mapping with a deterministic check",
    "priority": "p1",
    "allowed_files": [
      "plugins/kipi-core/skills/learn-from-correction/SKILL.md",
      "q-system/.q-system/scripts/correction_outcome.py",
      "q-system/.q-system/scripts/test_correction_outcome.py"
    ],
    "required_checks": ["python3 q-system/.q-system/scripts/test_correction_outcome.py"],
    "bypass_check": "python3 q-system/.q-system/scripts/test_correction_outcome.py",
    "acceptance": "learn-from-correction, when a contradicted belief maps to a surfaced memory_id, records one corrected outcome via record_outcome (a small correction_outcome.py helper holds the deterministic map-then-record logic the skill invokes). Conservative: no confident map means no write. Test proves: mapped correction produces exactly one corrected line; unmapped correction produces zero writes; replay is idempotent."
  },
  {
    "id": "autocapture-instance-guard",
    "finding_id": "finding-3",
    "title": "Design-partner-only enforcement: self-gating allowlist + guarded advisory Stop-hook wiring (settings + template sync)",
    "priority": "p1",
    "allowed_files": [
      ".claude/settings.json",
      "settings-template.json",
      "q-system/.q-system/scripts/autocapture_config.json",
      "q-system/.q-system/scripts/test_autocapture_wiring.py"
    ],
    "required_checks": ["python3 q-system/.q-system/scripts/test_autocapture_wiring.py"],
    "bypass_check": "python3 q-system/.q-system/scripts/test_autocapture_wiring.py",
    "acceptance": "autocapture_config.json is the allowlist (enabled_instances: [4_points_consulting]); the Stop-hook capture no-ops on any instance not listed (default off) so wiring the guarded advisory entry (test -f && python3 ... 2>/dev/null || true) into BOTH .claude/settings.json and settings-template.json cannot enable capture beyond the design partner. Test proves: the hook writes nothing when the current-instance identity is not in the allowlist, and the settings-template-sync invariant holds (entry present in both files). Wiring is advisory, never exit-2."
  },
  {
    "id": "autocapture-e2e-acceptance",
    "finding_id": "finding-2",
    "title": "Deterministic end-to-end acceptance: auto-captured outcomes move memory_reflect verdicts",
    "priority": "p2",
    "allowed_files": [
      "q-system/.q-system/scripts/test_autocapture_e2e.py"
    ],
    "required_checks": ["python3 q-system/.q-system/scripts/test_autocapture_e2e.py"],
    "bypass_check": "python3 q-system/.q-system/scripts/test_autocapture_e2e.py",
    "acceptance": "Replaces the vague success language with a deterministic threshold: a seeded design-partner-realistic session set is fed through capture (artifact + capture-core + corrected), then memory_reflect.aggregate is asserted to move >= 1 memory to preferred (>= 2 distinct useful event_ids) and >= 1 memory to dead_end, using ONLY auto-captured outcomes (no manual CLI lines). Read-only over the other issues' code; test-only, no source overlap."
  }
]
```
