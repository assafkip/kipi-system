---
description: Evidence ledger + system manifest, and the four gates that read them. Conclusions are derived from stored verified facts, never issued first and evidenced afterward.
paths:
  - "**/canonical/**"
  - "**/memory/**"
  - "**/output/outreach/**"
  - "**/methodology/**"
  - "**/scripts/**"
  - "**/*.jsonl"
---

# Evidence Ledger: store the evidence, derive the conclusions (ENFORCED)

**The enforcement is four hooks, always live regardless of this file.** This rule is
the map; the gates fire on their own. That is why it is paths-scoped rather than
always-on: prose that duplicates a coded gate is budget, not enforcement.

A conclusion delivered in chat is a shipped artifact. It steers the next draft three
turns later. So conclusions are derived from a stored, verified evidence base -- never
issued first and evidenced afterward.

## The scar

2026-07-28, Prodigy_Gold. A read-only trace of a client's automation produced six
confident conclusions. All six were reversed later in the same session by evidence
available from the first minute. One survived long enough to shape a client email
draft. The founder caught the pattern; no hook, lint, or gate did. It was a recurrence
of the same complaint from 2026-07-14, whose fix closed the floor and left the seam as
a behavioral expectation.

Measurements survived recomputation. Inferences did not. Every recomputed number
matched; every claim about what the numbers meant moved. That split is where the gates
below sit.

RCA: `q-system/output/rca/rca-conclusions-before-evidence-2026-07-28.md` (instance).

## The two data primitives

| File | What it declares |
|---|---|
| `<instance>/canonical/evidence.jsonl` | one verified fact per row: `{claim_id, claim, source, command, result, verified_at}` |
| `<instance>/canonical/system-manifest.json` | which workflows/files constitute each data path |

Record a fact the moment you verify it. The ledger is the single writer; a row without
a `command` and a `result` is refused, so an inference cannot be stored in the shape of
a measurement.

```bash
python3 q-system/.q-system/scripts/evidence_ledger.py add \
  --claim "Brightspeed export holds 1177 rows, 332 hand-typed dates" \
  --source "~/Downloads/export.xlsx" \
  --command "python3 -c 'openpyxl ... Date Sold'" \
  --result "real dates: 845 | hand-typed: 332 | future-dated: 0 | max: 2026-07-21"

python3 q-system/.q-system/scripts/evidence_ledger.py check      # validate every row
python3 q-system/.q-system/scripts/system_manifest.py check      # validate the manifest
```

Derived docs (`system-map.md`, client drafts, handoffs) are VIEWS of the ledger. When
they disagree with it, the ledger wins and the doc is rewritten.

## The four gates (all coded, none prose)

| Gate | Fires | Blocks on |
|---|---|---|
| `read-first-gate.py` | PreToolUse, first Write/Edit of a session | `anti-hallucination.md` unopened, or zero lesson files opened while a lessons corpus exists |
| `code_claim_grounding_guard.py` | Stop | check one: a repo file claimed but never opened. check two: a named manifest subsystem whose declared members were not all read |
| `client-output-evidence-gate.py` | PostToolUse on `output/outreach/` | a number (2+ digits) or a quoted span (4+ words) that traces to no ledger row |
| `handoff-provenance-lint.py` | PostToolUse on `memory/last-handoff.md` | a measurement-shaped line with no `[verified: ...]`, no `ev-` claim id, and no `{{UNVERIFIED}}` |

Each carries a stated HONEST BOUNDARY in its docstring naming what it does NOT catch.
Reading that boundary is part of trusting the gate's silence -- the 2026-07-28 failure
happened entirely inside a boundary a gate had already documented.

## Escape hatches, best first

1. **Verify it.** Run the command, record the row.
2. **Label it.** `{{UNVERIFIED}}` / `{{UNVALIDATED}}` / `{{NEEDS_PROOF}}` on the line.
   Labelling an inference is the correct move, not a lesser one. The defect is prose
   that hides which kind of statement it is making.
3. **Bypass the file.** One marker per gate, no stacking: `evidence-gate-skip`,
   `handoff-provenance-skip`, `grounding-guard-skip`. Last resort; it turns the gate
   off for that file or that answer.

## What is NOT covered (say it, do not hide it)

- A false claim carrying no numbers and no quotes passes the output gates untouched.
  Reversal #6 ("nobody works in the shared sheet") would clear every gate here.
- An incomplete manifest certifies incomplete reading. Keeping it true is a human job.
- The gates prove a file was opened, not that it was read carefully or applied.
- `[verified: I checked]` passes and proves nothing. These remove ambiguity, not the
  possibility of lying.

## Open decision (founder)

The arbitration rule between token-discipline (narrow targeted reads) and completeness
(exhaustive passes) is unwritten. Token discipline pushes toward the narrow reads that
produced this failure; nothing arbitrates. Until it is decided, the manifest is the
tiebreaker for any declared data path: name it, read all of it.

## The provenance vocabulary

One table, `q-system/.q-system/scripts/provenance-vocabulary.json`, read at
runtime by `memory-confidence-validator.py` and `handoff-provenance-lint.py`.
`ev-<id>` outranks every enum value because it points at a row carrying the
command AND its output. `{{UNVERIFIED}}` is exactly `provenance: inferred`.
Adding a value is a data change in one place, never a code change in two.

## Cross-references

`quick-plan.md` (the read-first contract this makes executable) ·
`rca-mode.md` (the diagnostic mirror) · `skill-hook-pairing.md` (why each of these is a
hook and not a paragraph) · `wiring-check.md` (load-path proof).
