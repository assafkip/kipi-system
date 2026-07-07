# Plan: confidence + provenance on auto-memory

Date: 2026-06-30
Status: approved (founder went with the three default picks)
Feeds: PRD via prd-os (gated path), then fable-discipline implementation

## What / why

Auto-memory stores facts but records no confidence and no origin. At recall a
founder-stated fact and a model-inferred guess are indistinguishable, so the
model can repeat its own guess back as fact. memanto (gap analysis this session)
tags every memory with confidence + provenance; kipi does not. Close that gap
with two frontmatter fields and two guard hooks. No DB, no external engine.

## Approach (the pick)

Mirror the existing `decay` field pattern exactly: optional frontmatter field,
documented in a rule, enforced/surfaced by deterministic hooks. Two fields:

- `confidence: 0.0-1.0` — model's certainty. Absent = treat as founder-stated/high.
- `provenance: explicit_statement | inferred | corrected | validated | observed | imported`

Two enforcement pieces (the no-prompt-only rule):

1. **Validator** (PostToolUse Write, scoped to auto-memory dir). Field present and
   invalid (confidence out of [0,1], provenance not in enum) -> exit 2 block.
   Field absent -> pass. Mirrors `lessons-validator.py`.
2. **Recall surfacer** (SessionStart). Surfaces low-confidence (< 0.5) and
   `inferred`/`observed` memories so they are treated skeptically, same as `[FAST]`
   today. Mirrors `memory-freshness-check.py`. Separate script (one job each).

Picks (founder-approved): both fields; optional + validated-when-present (no forced
backfill of the 32 existing files); validator blocks on invalid value.

## Files to touch

- NEW `.claude/rules/memory-confidence.md` — spec (mirror `memory-freshness.md`)
- NEW `q-system/.q-system/scripts/memory-confidence-validator.py` — PostToolUse Write, exit 2 on invalid
- NEW `q-system/.q-system/scripts/memory-confidence-surface.py` — SessionStart, prints low-conf/inferred warnings
- NEW test (location TBD in PRD) — negative self-test: proves validator FAILS on bad value, passes on good + absent
- EDIT `.claude/settings.json` — wire validator (PostToolUse) + surfacer (SessionStart)
- EDIT `.claude/rules/skill-hook-pairing.md` "Wired pairings" line — register the new pairing

## Acceptance criteria

- [ ] Memory file with `confidence: 1.5` -> validator exit 2 (reproducer, shown failing first)
- [ ] Memory file with `provenance: madeup` -> validator exit 2
- [ ] Memory file with valid `confidence: 0.4` + `provenance: inferred` -> validator exit 0
- [ ] Memory file with NEITHER field -> validator exit 0 (existing 32 files unaffected)
- [ ] File outside auto-memory dir -> validator exit 0 fast (self-scoped)
- [ ] SessionStart surfacer lists a seeded low-confidence memory under a `[LOW-CONF]` header
- [ ] Negative self-test: corrupt a valid input, prove the check fails (green is not a rubber stamp)
- [ ] Both hooks wired in `.claude/settings.json`; `kipi update --dry` confirms propagation
- [ ] `python3 plugins/prd-os/scripts/prd_runner.py gates run` exits 0

## Patterns to follow (from this instance's own code)

- Validator: `q-system/.q-system/scripts/lessons-validator.py` — stdin JSON, self-scope
  on `tool_input.file_path`, fast exit 0 off-scope, `block()` -> exit 2, stdlib only.
- Surfacer: `q-system/.q-system/scripts/memory-confidence` ... model on
  `memory-confidence-surface.py` after `memory-freshness-check.py` — frontmatter parse,
  print warning block, always exit 0.
- Field-as-frontmatter + hook-not-prompt: `.claude/rules/memory-freshness.md` is the
  template for `memory-confidence.md`.
- QROOT + memory-dir resolution: copy `get_memory_dir()` from `memory-freshness-check.py`
  (auto-memory lives outside the project tree at `~/.claude/projects/<slug>/memory/`).

## fable-discipline notes for implementation

- Recon: done (read the 3 sibling scripts this session).
- Verify against a copy with a negative self-test: test pipes JSON payloads at a temp
  memory file, never the live memory dir.
- Single-writer chokepoint: the validator hook is the one gate every memory write passes.
- Why-comment anchored to scar: cite this gap analysis (kipi memory had no confidence
  signal; inferred guess == stated fact at recall).
- Degenerate cases: missing frontmatter, no fields, confidence=0, confidence=1.0,
  confidence=1.5, empty provenance, unknown provenance.
