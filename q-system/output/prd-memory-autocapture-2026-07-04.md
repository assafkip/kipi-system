# PRD: Memory Outcome Auto-Capture

- **Slug:** `prd-memory-autocapture`
- **Date:** 2026-07-04
- **Parent:** `prd-memory-outcome-scoring-2026-07-04` (shipped, PR #6 merged `49e7cd2`)
- **Spillover resolved by this PRD:** `sp-04006168` (the agent deciding WHEN a recall was useful/dead_end/corrected)
- **Author disposition:** senior-staff engineering call, autonomous run 2026-07-04
- **Design partner:** `4_points_consulting` (27 live cases, highest memory reuse, highest cost of a stale memory)

---

## 1. Problem

Earned-trust scoring is live fleet-wide but **inert**. `memory_reflect.py` scores
memories from `q-system/memory/outcomes.jsonl`; that log is fed ONLY by the manual
CLI (`memory_outcomes.py <memory_id> <outcome> ...`). Nothing observes a session
and records "this recalled memory was useful / a dead end / corrected." So the
surface stays silent forever unless a human hand-feeds it — which will not happen
at the cadence needed to earn trust signal.

**Done = the outcomes log fills itself** from real sessions on the design-partner
instance, with signal good enough that `memory_reflect` promotes genuinely-useful
memories to `preferred` and demotes contradicted ones to `dead_end` / `contested`
without a human typing a CLI command.

## 2. The load-bearing insight (why this is cheaper than it looks)

`memory_reflect.aggregate` already tolerates noisy input by design:

- **Corroboration gate:** a memory needs `>= 2` DISTINCT `event_id` useful outcomes
  to reach `preferred`. One noisy false-positive `useful` cannot mint trust — it
  lands in `tentative`.
- **Signed time-decay:** a fresh `dead_end` (weight ~1.0) outweighs a stale
  `useful` (weight ~0.25 at 60d). A wrong signal ages out; a real reversal bites now.
- **Contested bucket:** any memory with both signs is flagged for re-verify, not
  silently trusted.

Therefore auto-capture does **not** need to be a precise judge. It needs to be an
**approximately-unbiased signal generator**. That reframes the architecture: the
expensive per-session LLM sweep is unjustified; cheap deterministic proxies plus
one narrow judge are enough, because the scoring engine is the noise filter.

## 3. Approach — three options, one pick

**Option A — Stop-hook LLM judge (full sweep).** A Stop hook runs `claude -p` over
each session, classifies every surfaced memory into useful/dead_end/corrected.
- Pro: semantic, catches all three outcomes in one place.
- Con: a real Opus/Sonnet call every session (token cost the whole fleet pays),
  non-deterministic, violates the deterministic-first law for the 80% of the job
  that does not need semantics.

**Option B — Deterministic-only proxies (no LLM).** From the session's tool log:
`useful` = a surfaced memory's `source_file` was read this session; `corrected` =
that file was edited after the memory was surfaced; `dead_end` = surfaced, source
never touched.
- Pro: free, deterministic, unit-testable, fleet-safe.
- Con: proxies are coarse and miss conversational correction (founder says "no,
  that changed" without touching the file).

**Option C — Hybrid: deterministic candidate-gen + judge ONLY on the corrected
path. [THE PICK]** Deterministic proxies emit `useful` / `dead_end` (the high-volume,
noise-tolerant paths). The one outcome where semantics are load-bearing —
`corrected` — routes through the ALREADY-SHIPPED `learn-from-correction` skill
(`plugins/kipi-core/skills/learn-from-correction/SKILL.md`), which already fires
when the founder contradicts a belief. That skill, when the contradicted belief
maps to a surfaced memory_id, calls `record_outcome(..., "corrected", ...)`.

**Why C:**
1. Honors the deterministic-first law (CLAUDE.md) — LLM judgment only where it is
   structurally required.
2. Token cost near zero: no per-session sweep. The judge fires only when a
   correction already happened (rare, event-driven).
3. Reuses machinery that exists and already detects the exact event.
4. Isolates the fuzzy call to the outcome that is cheapest to get wrong: a spurious
   `corrected` is a single `-1` the decay + corroboration gate absorbs.

## 4. The missing artifact: the surfaced set (session-scoped recall record)

Capture can only score a memory that was actually **recalled this session**. Today
the surface scripts (`memory-scores-surface.py`, `memory-confidence-surface.py`)
print memories at SessionStart but leave no machine-readable record of WHICH ones.

New artifact: `q-system/memory/.session-recall.json` (gitignored, session-scoped).
- **Producer:** the SessionStart surface scripts append the `memory_id`s they
  surfaced (single-writer helper, same discipline as `memory_outcomes`).
- **Consumer:** the Stop-hook capture reads it to know the candidate set, then
  clears/rotates it.
- **Schema:** `{ "session_id": str, "surfaced": [ {memory_id, source_file, surfaced_at} ] }`.

This closes the wiring loop (producer + consumer + schema) required by
`wiring-check.md`.

## 5. Files to touch

New:
- `q-system/.q-system/scripts/memory_autocapture.py` — Stop-hook entry. Reads
  `.session-recall.json` + the session tool-transcript, emits deterministic
  `useful`/`dead_end` via `record_outcome`. Single responsibility, no LLM.
- `q-system/.q-system/scripts/test_memory_autocapture.py` — reproducer-first tests.
- Schema doc for `.session-recall.json`.

Modified:
- `q-system/.q-system/scripts/memory-scores-surface.py` + `memory-confidence-surface.py`
  — append surfaced memory_ids to `.session-recall.json`.
- `plugins/kipi-core/skills/learn-from-correction/SKILL.md` — on a correction that
  maps to a surfaced memory_id, call `record_outcome(..., "corrected", ...)`.
- `.claude/settings.json` + `settings-template.json` — wire `memory_autocapture.py`
  into the Stop hook group (guarded `test -f && python3 ... || true`, advisory).

## 6. Acceptance criteria (reproducer-first)

- [ ] **Surfaced-set producer:** a test drives `memory-scores-surface.py` with a
      seeded sidecar, asserts `.session-recall.json` lists exactly the surfaced ids.
- [ ] **Deterministic `useful`:** a synthetic session where a surfaced memory's
      `source_file` was read produces one `useful` outcome in `outcomes.jsonl` with
      a stable content-hash `event_id` (no dupes on re-run).
- [ ] **Deterministic `dead_end`:** a surfaced memory whose source was never
      touched produces one `dead_end`.
- [ ] **`corrected` path:** a simulated founder correction that maps to a surfaced
      memory_id produces one `corrected` outcome via the learn-from-correction path.
- [ ] **Idempotent:** re-running capture on the same session writes ZERO new lines
      (event_id dedup at the single writer holds end-to-end).
- [ ] **End-to-end trust move:** feed a design-partner-realistic session set; assert
      `memory_reflect` moves at least one memory to `preferred` and one to
      `dead_end` purely from auto-captured outcomes. Show it green.
- [ ] **Silent-safe:** with no `.session-recall.json` and no transcript, the Stop
      hook exits 0 and writes nothing (never breaks a session close).
- [ ] `python3 plugins/prd-os/scripts/prd_runner.py gates run` exits 0.

## 7. Patterns to follow (from this instance's own code)

- **Single-writer chokepoint:** all outcome writes go through
  `memory_outcomes.record_outcome` — capture NEVER writes `outcomes.jsonl` directly
  (lesson `single-writer-chokepoint.md`).
- **Content-hash event_id:** reuse `_auto_event_id(memory_id, outcome, date, note)`
  so replay is idempotent (finding-3, parent PRD).
- **Swallow-and-continue in hooks:** every Stop-hook path wraps in
  `try/except -> exit 0`, mirroring `_safe_load_scores` in `memory-scores-surface.py`
  — a capture bug must never block a session close.
- **Guarded, advisory wiring:** `test -f <script> && python3 ... 2>/dev/null || true`,
  matching the SessionStart entry shipped in PR #6.
- **Fable-discipline:** verify against a copy of the log with a negative self-test
  (a session that should produce NOTHING produces nothing).

## 8. Rollout (design-partner first, then fleet)

1. Build + land on skeleton behind the guarded Stop-hook entry.
2. Enable on `4_points_consulting` only (it is the design partner). Watch
   `outcomes.jsonl` fill for ~1-2 weeks of real case work.
3. Tune proxy thresholds against real signal (is "file was read" too generous?).
4. When the design partner's `preferred`/`dead_end` verdicts match founder
   intuition, propagate fleet-wide via `kipi update` (same silent-safe path this
   PRD's parent uses).

## 9. Risks / open design questions for review

- **`useful` proxy generosity.** "source_file was read" may over-fire (a file read
  for unrelated reasons). Mitigation: the corroboration gate needs 2 distinct, and
  decay ages out one-offs. Tunable at step 3. Codex-review this threshold.
- **Session-transcript access from a Stop hook.** Confirm the Stop hook can read the
  session's tool log deterministically (path/format). If not available, `useful`
  falls back to a narrower signal (memory's source_file `mtime` changed during the
  session window). Flag for the design partner build.
- **`corrected` mapping precision.** Linking a founder correction to a specific
  surfaced `memory_id` is the one semantic step. Keep it conservative: no confident
  map → no write (a missed `corrected` is safe; a wrong one is a cheap −1 anyway).

## 10. Scope boundaries

- `memory_reflect` scoring math stays untouched (it shipped in PR #6).
- Fleet-wide enable is deferred to step 8 (design-partner first).
- The per-session full-sweep design (Option A in section 3) was not chosen; it is
  carried in section 3 as the record of why the hybrid path won.
