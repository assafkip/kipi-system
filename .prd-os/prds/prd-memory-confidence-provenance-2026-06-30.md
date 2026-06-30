---
id: prd-memory-confidence-provenance-2026-06-30
title: Memory Confidence Provenance
status: in-review
created_at: 2026-06-30T17:01:25Z
updated_at: 2026-06-30T17:07:22Z
owner: assafkipnis
reviewers: []
findings_path: .prd-os/findings/prd-memory-confidence-provenance-2026-06-30-findings.jsonl
codex_reviewed_at: 2026-06-30T17:07:22Z
---

# Memory Confidence Provenance

## Problem

Auto-memory frontmatter (`name`, `description`, `metadata.type`, `decay`) records
no certainty and no origin. At recall — SessionStart injection or the model
reading a memory file mid-session — a founder-stated fact and a model-inferred
guess are byte-indistinguishable. Observed failure mode: the model surfaces its
own prior inference back to the founder as established fact, because nothing on the
record says "this was a guess."

The `decay` field (memory-freshness.md) added freshness awareness on the TIME
axis. There is no equivalent on the TRUST axis. Comparison (gap analysis,
2026-06-30): memanto tags every record with `confidence` (0-1, default 0.8) and
`provenance` (explicit_statement|inferred|corrected|validated|observed|imported);
kipi has neither.

Measurable: 32 existing auto-memory files, 0 carry any certainty/origin signal.
After ship: a new memory CAN carry the signal, an invalid value is blocked at
write, and low-confidence / inferred memories surface at SessionStart with a
marker, the same way `[FAST]` surfaces today.

## Goals

- Two OPTIONAL frontmatter fields on auto-memory: `confidence` (float 0.0-1.0) and
  `provenance` (enum: explicit_statement, inferred, corrected, validated, observed, imported).
- A PostToolUse validator, self-scoped to the auto-memory dir, BLOCKS (exit 2) a
  write whose `confidence` is out of [0,1] or whose `provenance` is not in the enum.
  Absent fields pass. Deterministic; mirrors `lessons-validator.py`.
- A SessionStart surfacer prints a warning block listing memories with
  `confidence < 0.5` OR `provenance` in {inferred, observed}, so they are treated
  skeptically at recall. Mirrors `memory-freshness-check.py` / the `[FAST]` marker.
- No forced backfill: the 32 existing field-less files validate clean and behave
  exactly as today.
- Both hooks wired in `.claude/settings.json`; new pairing registered in
  `skill-hook-pairing.md`; propagation confirmed via `kipi update --dry`.

## Non-goals

- NOT required fields. Optional, validated-when-present (like `decay`).
- NO semantic retrieval / vector search. That is the larger memanto gap; explicitly
  deferred to a separate PRD.
- NO automatic confidence assignment and NO confidence decay-over-time. The writer
  sets the value; there is no background recompute.
- NO external service or DB. Frontmatter + git only.
- NO change to `q-system/memory/` session-state files (open-loops, handoff). Scope
  is the auto-memory dir (`~/.claude/projects/<slug>/memory/`) only.

## Proposed approach

The established field-as-frontmatter + hook-not-prompt pattern, in three parts.

```
WRITE PATH                              RECALL PATH
Write tool -> memory/*.md               SessionStart
  |                                       |
  v  PostToolUse                          v
memory-confidence-validator.py          memory-confidence-surface.py
  - self-scope on auto-memory dir         - scan memory/*.md frontmatter
  - field absent -> exit 0                 - confidence<0.5 OR provenance in
  - confidence out of [0,1] -> exit 2        {inferred,observed} -> list it
  - provenance not in enum -> exit 2       - print [LOW-CONF]/[INFERRED] block
  - else exit 0                            - always exit 0
```

1. **Schema** — `.claude/rules/memory-confidence.md` documents the two fields and
   the trust-axis semantics (mirror of `memory-freshness.md`). The rule is spec;
   the hooks are enforcement (the auto-memory dir lives outside the project tree,
   so path-scoped rule loading does not reach it — same reason the freshness hook
   exists).
2. **Validator** — `q-system/.q-system/scripts/memory-confidence-validator.py`,
   stdin JSON, self-scoped on `tool_input.file_path`, fast exit 0 off-scope,
   `block()` -> exit 2. Stdlib only. Copied skeleton from `lessons-validator.py`.
3. **Surfacer** — `q-system/.q-system/scripts/memory-confidence-surface.py`,
   reuses `get_memory_dir()` resolution from `memory-freshness-check.py`, prints a
   warning block, always exit 0.

fable-discipline applied: recon done (3 sibling scripts read this session); each
script ships a paired test that pipes JSON at a TEMP memory file (never the live
dir) and includes a NEGATIVE self-test (corrupt a valid input, prove the validator
FAILS) so a green run is not a rubber stamp; the validator is the single write-time
chokepoint; why-comments cite this PRD as the scar.

## Alternatives considered

- **Single combined `trust` field** — Rejected: provenance is categorical (where
  it came from), confidence is scalar (how sure). Collapsing them conflates source
  with certainty and loses the ability to surface `inferred` independent of score.
- **Required fields + one-time backfill of 32 files** — Rejected: breaks every
  existing memory on first validate, large diff, no payoff. `decay` already proved
  optional-when-present works.
- **Extend `memory-freshness-check.py` instead of a new surfacer** — Rejected:
  AUDHD coding rule (one function, one job); freshness is the time axis, confidence
  the trust axis; separate scripts are independently testable. (Shared frontmatter
  parse could become duplication — capture if it does.)
- **Advisory warn instead of exit-2 block** — Rejected: range + enum are
  deterministic; the repo no-prompt-only rule wants the deterministic slice blocked,
  not suggested.

## Scenarios

- **Valid inferred write.** Model writes a memory it inferred, sets
  `confidence: 0.4`, `provenance: inferred`. Validator exit 0. Next SessionStart,
  surfacer lists it under `[LOW-CONF / INFERRED]`; model verifies before asserting.
- **Typo write.** Model writes `provenance: infered`. Validator exit 2, stderr
  "provenance 'infered' not in enum"; the write is flagged back to the model.
- **Legacy file.** An existing field-less memory is edited. Validator exit 0
  (absent = pass). No behavior change.
- **Off-scope write.** A canonical `.md` (not in the auto-memory dir) is written.
  Validator exits 0 fast (self-scoped).

## Resolved decisions

- **Both fields vs confidence-only.** Decided: ship both. Rationale: cheap together;
  `inferred` provenance is what justifies a low confidence number.
- **Required vs optional.** Decided: optional, validated-when-present. Rationale: no
  forced backfill; mirrors `decay`.
- **Block vs warn.** Decided: block on invalid value, pass on absent. Rationale:
  range/enum are deterministic; catch typos at write.
- **Test location.** Decided: `test_*.py` beside the scripts in
  `q-system/.q-system/scripts/`. Rationale: avoids a new dir (folder-structure
  rule); keeps test next to the unit it covers.
- **Reaching every reader (closes finding-1).** Decided: the trust signal reaches
  all three read paths. (a) Direct file Read already exposes the field — it is
  frontmatter the model sees on any Read, so mid-session reads are covered with no
  extra work. (b) SessionStart surfacer is the active push for low-conf/inferred.
  (c) `MEMORY.md` index gets a `[low-conf]` marker convention (mirror of `[fast]`),
  documented in `memory-confidence.md`, so an at-a-glance index scan sees it too.
  Previously deferred; un-deferred here to close the gap.
- **Issue build order (closes finding-2).** Decided: mcp-03 (wire + doc) depends on
  the scripts produced by mcp-01 and mcp-02. Issues build in id order; mcp-03's
  wiring test asserts both scripts exist before checking the settings.json entries.

## Risks and rollback

- **Blast radius:** two new scripts + two `.claude/settings.json` hook entries +
  one rule + one doc line. No change to existing memory files.
- **Silent no-op risk:** the auto-memory dir is outside the project tree; if the
  validator/surfacer resolves the path wrong it silently does nothing. Mitigation:
  copy `get_memory_dir()` verbatim from `memory-freshness-check.py`; a test asserts
  it resolves and the surfacer finds a seeded file.
- **Over-block risk:** validator blocks a non-memory write if scope match is too
  broad. Mitigation: self-scope on the exact auto-memory dir path like
  `lessons-validator.py` scopes on `q-system/lessons/`; a test asserts an off-scope
  path exits 0.
- **Surfacer noise:** too many low-confidence memories drown the signal. Mitigation:
  threshold 0.5 + provenance set; tune later.
- **Rollback:** remove the two hook entries from `settings.json`; the fields become
  inert frontmatter. No data migration to undo.

## Open questions

- Threshold for "low confidence" surfacing — 0.5 chosen; revisit if noisy.
- Should `provenance: corrected` also surface (high-trust but notable)? Leaning no for v1.
- (Resolved: `MEMORY.md` `[low-conf]` index marker is now in scope — see Resolved decisions / finding-1.)

## Persona Review

### Skeptic

Q1: What is the strongest argument against doing this?
A1: Confidence is self-reported. A sycophantic model can mark every guess 0.9 and
the signal is worthless. v1 ships only the mechanism + surfacing; honesty of the
score is a model-behavior problem. Partial mitigation: `provenance: inferred`
surfaces regardless of the confidence number, so origin can't be hidden behind a
high score. Score calibration (cross-check vs the sycophancy-harness) is a v2.

Q2: What is the smallest experiment that would disprove the thesis?
A2: Seed 3 inferred memories, run a session, check whether the
`[LOW-CONF/INFERRED]` surfacing actually changes whether the model verifies before
asserting. If it ignores the marker, the feature is inert.

Q3: What is the cheapest non-build alternative?
A3: A prompt-only convention ("note confidence in the body"). Rejected by the
repo's no-prompt-only rule and by the same logic that forced `decay` to need a
hook — the model forgets conventions; only the hook makes it non-optional.

## Issues

```json
[
  {
    "id": "mcp-01-validator",
    "title": "PostToolUse validator: block invalid confidence/provenance on auto-memory writes",
    "allowed_files": [
      "q-system/.q-system/scripts/memory-confidence-validator.py",
      "q-system/.q-system/scripts/test_memory_confidence_validator.py"
    ],
    "required_checks": ["python3 q-system/.q-system/scripts/test_memory_confidence_validator.py"],
    "acceptance": "confidence 1.5 -> exit 2; provenance 'madeup' -> exit 2; valid 0.4+inferred -> exit 0; neither field -> exit 0; off-scope path -> exit 0; negative self-test proves a corrupted input fails.",
    "priority": "p1"
  },
  {
    "id": "mcp-02-surfacer",
    "title": "SessionStart surfacer: flag low-confidence / inferred memories at recall",
    "allowed_files": [
      "q-system/.q-system/scripts/memory-confidence-surface.py",
      "q-system/.q-system/scripts/test_memory_confidence_surface.py"
    ],
    "required_checks": ["python3 q-system/.q-system/scripts/test_memory_confidence_surface.py"],
    "acceptance": "seeded memory with confidence<0.5 OR provenance in {inferred,observed} appears under a [LOW-CONF] header; field-less memory does not; always exit 0; resolves auto-memory dir outside project tree.",
    "priority": "p1"
  },
  {
    "id": "mcp-03-wire-and-doc",
    "title": "Wire both hooks + author rule + register pairing",
    "allowed_files": [
      ".claude/settings.json",
      ".claude/rules/memory-confidence.md",
      ".claude/rules/skill-hook-pairing.md",
      "q-system/.q-system/scripts/test_memory_confidence_wiring.py"
    ],
    "required_checks": ["python3 q-system/.q-system/scripts/test_memory_confidence_wiring.py"],
    "acceptance": "settings.json contains the validator (PostToolUse) and surfacer (SessionStart) entries; both scripts exist and are executable; memory-confidence.md present with frontmatter; skill-hook-pairing.md Wired-pairings line names the new pairing.",
    "priority": "p2"
  }
]
```
