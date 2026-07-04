---
id: prd-memory-outcome-scoring-2026-07-04
title: Memory Outcome Scoring
status: archived
created_at: 2026-07-04T19:28:37Z
updated_at: 2026-07-04T20:06:45Z
owner: assafkipnis
reviewers: []
findings_path: .prd-os/findings/prd-memory-outcome-scoring-2026-07-04-findings.jsonl
codex_reviewed_at: 2026-07-04T19:33:52Z
---

# Memory Outcome Scoring

<!-- prompt-only-enforcement-skip: design doc. The enforcement this PRD proposes
     is executable (memory-reflect.py, byte-stability tests, single-writer
     record_outcome, source-fingerprint check) and gets built + guarded during
     issue execution. The prose here describes that design, it does not claim a
     prompt enforces anything at runtime. -->

## Problem

kipi's memory/lessons trust today is **declared once, at write time, and never
re-tested against reality.**

- `memory-confidence.md`: `confidence` (0.0-1.0) and `provenance` are stamped by
  the writer when the memory is created. Nothing updates them afterward.
- `memory-freshness.md`: `decay` (fast/medium/slow) is a discrete, author-chosen
  label that triggers *verification*, not a measured signal.

So a memory the author felt 0.9 sure about, that has since been cited five times
and been wrong twice, still reads 0.9 at recall. There is no record of how a
memory or lesson *performed when it was actually used*. Concretely observed gaps:

1. **No outcome capture.** When a recalled memory turns out useful, a dead end,
   or wrong, that result is not written anywhere. The next session cannot learn
   from it. (`sycophancy-core.md`: "a belief only confirmed and never challenged
   is suspect" — but nothing tracks the challenge/confirm history.)
2. **No corroboration gate.** One confident write mints a trusted memory. There
   is no "seen useful twice, by two separate uses" bar before a memory is treated
   as reliable.
3. **Blanket staleness only.** `decay: fast` flags a memory for re-verification
   on a clock, not on whether the thing it points at actually changed. A lesson
   pinned to a file the code has since rewritten is not distinguished from one
   whose file is untouched.

graphify's `reflect.py` (MIT, github.com/Graphify-Labs/graphify) is a deployed,
deterministic, no-LLM implementation of exactly this earned-trust layer. This PRD
folds its scoring model into kipi's memory system as a NEW axis, without touching
the two existing ones.

## Goals

- Add an **earned-trust** layer: a deterministic score per memory/lesson computed
  from recorded real-use outcomes (`useful` / `dead_end` / `corrected`).
- **Time-decayed signed scoring** with a half-life (default 30 days): a fresh
  dead end outweighs a months-old useful.
- **Corroboration gate:** a memory is only promoted to "preferred" after >= N
  distinct useful outcomes (default 2). One outcome cannot mint trust.
- **Contested tracking:** memories with both positive and negative outcomes are
  surfaced as contested; recency decides the leaning verdict.
- **Derived sidecar, never mutate durable truth:** scores live in a separate
  artifact keyed by memory id. The memory `.md` frontmatter (`confidence`,
  `provenance`, `decay`) is never rewritten by this system.
- **Source-fingerprint staleness:** for a memory/lesson that cites a file, store a
  content hash; flag "re-verify" only when that file's content actually changed.
- Deterministic and testable: no LLM, stable sort orders, byte-stable output for a
  fixed input and a fixed `now`. Reproducer-first.

## Non-goals

- **Automatic outcome capture UX.** v1 defines the append-only event format and a
  single writer for it; wiring a hook/command that auto-records outcomes on every
  recall is a follow-up. v1 can be exercised by hand-written events + tests.
- **No LLM anywhere.** No semantic summarization, no LLM judge of "was this
  useful." Outcome tagging is an explicit signal, not an inference.
- **Do not modify the existing `confidence`/`provenance`/`decay` fields** or their
  validators. This is an additive axis, not a rewrite.
- **No cross-instance propagation** of scores in v1 (scores are local, like the
  memory files themselves). Lessons-corpus scoring can come later.
- **Not a graph.** kipi is not adopting graphify's knowledge-graph; only the
  scoring model from `reflect.py`.

## Proposed approach

Three pieces, all under `q-system/.q-system/scripts/`, QROOT = `q-system/`.

**1. Outcome event log (the input).**
Append-only JSONL at `q-system/memory/outcomes.jsonl`. One line per recorded
outcome:

```json
{"memory_id": "feedback_rate_floor_250", "outcome": "useful", "date": "2026-07-04", "note": "drove the pricing reply", "source_file": "q-system/my-project/..."}
```

`outcome` in {`useful`, `dead_end`, `corrected`}. `source_file` optional. A single
writer function (`record_outcome`) is the only thing that appends, so the format
stays one shape (single-writer-chokepoint lesson, already in the corpus).

**2. `memory-reflect.py` (the engine).**
Port of `reflect.py`'s scoring, adapted to kipi's ids:
- Time-decayed signed score per `memory_id`: `useful` = +decay, `dead_end` /
  `corrected` = -decay, half-life 30d (`0.5 ** (age_days / half_life)`).
- Split into **preferred** (>= 2 distinct useful, positive score), **tentative**
  (useful but under the corroboration bar), **contested** (both signs; verdict by
  recency), **dead ends** (negative-only).
- Emit a sidecar `q-system/memory/.memory-scores.json` keyed by `memory_id`:
  `{status, score, uses, last, source_fingerprint, provenance:[recent events]}`.
  Deterministic (sorted keys, indent 2, explicit `now`).
- Source-fingerprint = SHA256 of the cited file's content (content only, so it is
  path-independent). On read, recompute and mark `stale: true` when it differs.

**3. Recall surface.**
Extend the existing `memory-confidence-surface.py` SessionStart path (or a sibling
`memory-scores-surface.py`) to print an earned-trust block: preferred memories to
lean on, contested ones to treat skeptically, and any `stale` re-verify flags.
MEMORY.md index gets an optional marker (e.g. `[contested]`) mirroring `[fast]` /
`[low-conf]`.

Pipeline: `record_outcome` appends -> `memory-reflect.py` aggregates -> sidecar ->
surface reads sidecar at session start. The `.md` files are read-only to this
system.

## Alternatives considered

- **Mutate `confidence` in the frontmatter on each outcome.** Rejected: destroys
  the author's *declared* trust signal (they are orthogonal — declared vs earned),
  makes the memory file churn on every use, and couples a fast-moving score to a
  slow-moving document. graphify learned this and kept a sidecar; we follow it.
- **LLM judge to decide if a recall was useful.** Rejected: non-deterministic,
  costs tokens, and violates the no-prompt-only / deterministic-enforcement
  doctrine. The outcome is an explicit tag, not an inference.
- **Reuse `decay: fast` as the staleness signal.** Rejected: it is clock-based and
  blanket; it cannot tell "the file this lesson cites was rewritten" from "a day
  passed." Content-fingerprinting is precise and is the safe over-flag direction.
- **Fold this into the lessons-autolearn pipeline instead.** Rejected for v1:
  that pipeline is about distilling/scrubbing/publishing lesson *text*; scoring is
  a separate concern (how a lesson performed, not what it says). They can meet
  later (score-weighted lesson surfacing), but coupling them now over-scopes both.

## Review resolutions (Codex, 2026-07-04)

- **F1 (data path).** v1 scores ONLY `q-system/memory/` memories. The recall
  surface explicitly labels its coverage ("earned-trust for q-system/memory")
  so it never implies it covers the auto-memory store at
  `~/.claude/projects/<project>/memory/`. Auto-memory scoring is a named v2 (it
  needs a second event-log location). No mismatch: the store scored and the store
  surfaced are the same.
- **F2 (unbounded log).** The engine reads the whole log but `outcomes.jsonl` gets
  a `compact` subcommand: fold events older than `max(2 * half_life, 180d)` into a
  per-`memory_id` decayed-score summary line, preserving the aggregate. Compaction
  is deterministic and idempotent; a bounded-read test asserts a compacted log
  yields the same sidecar as the full log. Ships in the same change as the reader.
- **F3 (dedup / corroboration integrity).** Each event carries a required
  `event_id` (caller-supplied stable key; `record_outcome` rejects a duplicate
  `event_id` already in the log). "Distinct useful" for the corroboration gate =
  distinct `event_id`, so a replayed/duplicate write cannot promote a memory.
- **F4 (fingerprint source).** The sidecar stores the canonical `source_file`
  (relative to QROOT) beside the hash. Resolution ports graphify's candidate-root
  search (QROOT first, then cwd); a missing/renamed file => `stale: true` (the safe
  over-flag direction). Multi-source memories are out of scope for v1 (one
  `source_file` per memory); the writer rejects a list.
- **F5 (reach to every reader).** Earned-trust reaches two read surfaces: the
  SessionStart block and the MEMORY.md index marker (`[contested]` / `[stale]`).
  A raw `Read` of a memory `.md` deliberately does NOT carry earned-trust, because
  mutating the file was an explicitly rejected alternative — this exactly mirrors
  how the memory age-warning and the pi metric surface at recall/index, not in
  every file. The reach boundary is documented, not hidden.
- **F6 (staleness of the sidecar).** The SessionStart surface hook runs
  `memory-reflect.py` first (fast, no LLM), then reads the fresh sidecar. So the
  sidecar is never read stale relative to the log at session start. A
  `record_outcome` mid-session does not auto-refresh; that is acceptable because
  the surface is a session-boot artifact.

## Scenarios

- **Earned promotion.** Over three sessions, `record_outcome` logs
  `feedback_rate_floor_250` as `useful` twice (distinct dates). `memory-reflect.py`
  scores it positive and, having >= 2 distinct useful, marks it `preferred` in the
  sidecar. Next SessionStart, the surface lists it under "lean on these."
- **Contested, recency wins.** A memory is logged `useful` once (60 days ago) then
  `corrected` once (today). Decayed signed score goes negative; the memory shows as
  `contested`, verdict "recency leans dead end," and is surfaced for skepticism —
  not silently trusted.
- **Stale re-verify.** A lesson cites `plugins/prd-os/scripts/prd_runner.py`. The
  file is edited. On the next reflect run the stored fingerprint no longer matches;
  the sidecar marks the lesson `stale: true`; the surface flags "re-verify before
  relying."
- **No outcomes yet.** A memory with zero recorded outcomes never appears in the
  sidecar. Its existing `confidence`/`decay` behavior is unchanged. Additive only.

## Resolved decisions

- **Sidecar, not frontmatter.** Decided: scores in `.memory-scores.json`.
  Rationale: declared trust and earned trust are orthogonal; never let the earned
  score overwrite the author's declared one (graphify's exact separation).
- **Half-life 30d, corroboration 2.** Decided: match graphify's proven defaults,
  both as CLI flags. Rationale: no reason to diverge from a shipped tuning without
  data; expose them so they can be tuned later.
- **JSONL event log, single writer.** Decided: append-only + one `record_outcome`
  chokepoint. Rationale: single-writer-chokepoint lesson; one shape, one place to
  validate.

## Risks and rollback

- **Blast radius:** additive. New scripts + one new JSONL + one new sidecar. No
  existing memory file, validator, or rule changes behavior. Rollback = delete the
  two artifacts and the surface hook line; the memory system reverts exactly.
- **Garbage-in:** outcomes are only as good as what gets recorded. v1 mitigates by
  making capture explicit and tested; auto-capture (a later PRD) is where recording
  discipline gets enforced. Documented as a known v1 limitation, not hidden.
- **Sidecar/`.md` drift:** a scored `memory_id` whose `.md` was deleted/renamed is
  dropped from the surface (known-ids gate), mirroring graphify's stale-node drop.
- **Determinism regressions:** guarded by a byte-stability test (same input + fixed
  `now` => identical sidecar bytes).

## Open questions

- Should the recall surface be a new hook script or an extension of
  `memory-confidence-surface.py`? (Leaning: sibling script, so the two trust axes
  stay independently testable — matches skill-hook-pairing scope discipline.)
- Where should the outcome log live for auto-memory files (which sit under
  `~/.claude/projects/<project>/memory/`) vs `q-system/memory/`? v1 targets
  `q-system/memory/`; auto-memory scoring may need a second log location.

## Persona Review

### Skeptic

Q1: What is the strongest argument against doing this?
A1: v1 ships the scoring engine but not the auto-capture, so with zero recorded
outcomes it does nothing until someone (or a later PRD) feeds it events. The risk
is building a scorer that sits idle. Mitigation: the engine is small, fully tested
standalone, and directly unblocks the auto-capture follow-up; the format + single
writer are the hard part and they ship here.

Q2: What is the smallest experiment that would disprove the thesis?
A2: Hand-log 10-15 real outcomes across a week of actual kipi memory use, run
reflect, and check whether the preferred/contested/stale verdicts match the
founder's own read of which memories have been pulling weight. If the verdicts feel
noise, the model (not the code) is wrong and we stop before auto-capture.

Q3: What is the cheapest non-build alternative?
A3: Do nothing and rely on the founder correcting stale memories in-session
(current state). Cheapest, but it does not persist the correction history, so the
same dead end gets re-derived across sessions — which is the exact pain.

## Issues

<!--
5 accepted findings -> 5 entries (1:1). F2 (compaction) was deferred, so it has no
entry (spillover tracks it). Three module files are built:
  memory_outcomes.py  (event log + record_outcome + event_id dedup + scope)
  memory_reflect.py   (scoring: decay, corroboration, contested, sidecar, fingerprint)
  memory-scores-surface.py (SessionStart: run reflect, print block, MEMORY.md marker)
Some entries share allowed_files (5 findings across 3 files) -> executed serially in
listed order; each later issue amends the shared file. Serialization is intended.
-->

```json
[
  {
    "id": "memory-outcome-log",
    "finding_id": "finding-3",
    "title": "Outcome event log + single-writer record_outcome with event_id dedup",
    "allowed_files": ["q-system/.q-system/scripts/memory_outcomes.py", "q-system/.q-system/scripts/test_memory_outcomes.py"],
    "required_checks": ["python3 -m pytest q-system/.q-system/scripts/test_memory_outcomes.py -q"],
    "bypass_check": "python3 -m pytest q-system/.q-system/scripts/test_memory_outcomes.py -q -k dedup",
    "priority": "p1"
  },
  {
    "id": "memory-scope-boundary",
    "finding_id": "finding-1",
    "title": "Scope scoring to q-system/memory only; record_outcome rejects out-of-scope memory_id",
    "allowed_files": ["q-system/.q-system/scripts/memory_outcomes.py", "q-system/.q-system/scripts/test_memory_outcomes.py"],
    "required_checks": ["python3 -m pytest q-system/.q-system/scripts/test_memory_outcomes.py -q"],
    "bypass_check": "python3 -m pytest q-system/.q-system/scripts/test_memory_outcomes.py -q -k scope",
    "priority": "p1"
  },
  {
    "id": "memory-reflect-engine",
    "finding_id": "finding-4",
    "title": "memory_reflect.py: decay + corroboration + contested + sidecar + source-fingerprint resolver",
    "allowed_files": ["q-system/.q-system/scripts/memory_reflect.py", "q-system/.q-system/scripts/test_memory_reflect.py"],
    "required_checks": ["python3 -m pytest q-system/.q-system/scripts/test_memory_reflect.py -q"],
    "bypass_check": "python3 -m pytest q-system/.q-system/scripts/test_memory_reflect.py -q -k fingerprint",
    "priority": "p1"
  },
  {
    "id": "memory-scores-surface",
    "finding_id": "finding-5",
    "title": "SessionStart earned-trust surface + MEMORY.md [contested]/[stale] index markers",
    "allowed_files": ["q-system/.q-system/scripts/memory-scores-surface.py", "q-system/.q-system/scripts/test_memory_scores_surface.py"],
    "required_checks": ["python3 -m pytest q-system/.q-system/scripts/test_memory_scores_surface.py -q"],
    "bypass_check": "python3 -m pytest q-system/.q-system/scripts/test_memory_scores_surface.py -q -k marker",
    "priority": "p1"
  },
  {
    "id": "memory-scores-trigger",
    "finding_id": "finding-6",
    "title": "Surface runs memory_reflect before reading the sidecar so it is fresh at SessionStart",
    "allowed_files": ["q-system/.q-system/scripts/memory-scores-surface.py", "q-system/.q-system/scripts/test_memory_scores_surface.py"],
    "required_checks": ["python3 -m pytest q-system/.q-system/scripts/test_memory_scores_surface.py -q"],
    "bypass_check": "python3 -m pytest q-system/.q-system/scripts/test_memory_scores_surface.py -q -k trigger",
    "priority": "p1"
  }
]
```
