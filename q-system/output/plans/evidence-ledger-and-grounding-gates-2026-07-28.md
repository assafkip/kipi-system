# Plan: evidence ledger + system manifest + the four gates that read them

**Date:** 2026-07-28
**Source:** `projects/Prodigy_Gold/q-system/output/rca/rca-conclusions-before-evidence-2026-07-28.md`
**Where it ships:** kipi-system skeleton (fleet-wide), NOT the Prodigy_Gold instance.
**Founder directive:** build the structural fixes from the RCA action items. Evidence
ledger and manifest first, since the gates depend on both. Reproducer first: the
failing check is written before the fix.

## What and why

Six conclusions reversed in one session; one reached a client email draft. The coded
gate that ran on every turn (`code_claim_grounding_guard.py`) was silent by design --
its own docstring names the seam it does not cover. Everything below closes that seam
with executable code, because a rule that only exists as prose is the
prompt-only-enforcement pattern this repo bans.

## Approach

Two data primitives, then four gates that read them. Nothing is a prose rule.

| # | Artifact | RCA item | Kind |
|---|---|---|---|
| 1 | `evidence_ledger.py` + `canonical/evidence.jsonl` | store the evidence, derive the conclusions | code |
| 2 | `system_manifest.py` + `canonical/system-manifest.json` | "did I read all of subsystem X" becomes computable | code |
| 3 | `code_claim_grounding_guard.py` subsystem coverage | close the documented seam | gate |
| 4 | `client-output-evidence-gate.py` | numbers in client-facing drafts trace to a ledger row | gate |
| 5 | `read-first-gate.py` | emission into context is not delivery | gate |
| 6 | `handoff-provenance-lint.py` | inherited claim cannot look like a verified one | gate |

**Why a ledger and not a better markdown file.** Reversal #5 rode in on
`last-handoff.md` because prose has no field for "how do you know this". A row that
cannot be written without `command` and `result` cannot carry an inference disguised
as a measurement. Measurements survived recomputation in that session; inferences did
not. The ledger stores only the survivors.

**Rejected -- one mega-gate.** A single script covering all four would fire on
everything and get bypassed reflexively. Four narrow gates, each with its own scope
and its own bypass marker, stay trustworthy.

**Rejected -- an LLM judge for grounding.** The founder's standing rule: deterministic,
script-based solutions over LLM-instruction fixes. Every check below is regex, set
membership, or file inspection.

## Instance path resolution

Instances name their content dir differently (`q-consult/`, `q-prodigy/`, and the
skeleton's own `q-system/`). `evidence_ledger.instance_root()` is the single resolver:
glob `q-*` for a dir containing `canonical/`, prefer a non-`q-system` one, fall back to
`q-system`. Precedent: `capability-map-gen.py:390`. Every new script imports it rather
than re-deriving the path.

## Files to touch

New, all under `q-system/.q-system/scripts/`:

- `evidence_ledger.py` (module + CLI: `add`, `list`, `check`, `resolve`)
- `test_evidence_ledger.py`
- `system_manifest.py` (module + CLI: `check`, `list`, `members`, `mentions`)
- `test_system_manifest.py`
- `client-output-evidence-gate.py`
- `test_client_output_evidence_gate.py`
- `read-first-gate.py`
- `test_read_first_gate.py`
- `handoff-provenance-lint.py`
- `test_handoff_provenance_lint.py`

Modified:

- `q-system/.q-system/scripts/code_claim_grounding_guard.py` (subsystem coverage +
  self-test cases; the HONEST BOUNDARY paragraph gets rewritten, not deleted)
- `settings-template.json` (wire gates 4, 5, 6 -- gate 3 is already wired as a Stop hook)
- `.claude/rules/evidence-ledger.md` (new rule, auto-propagates to the fleet)
- `q-system/methodology/anti-hallucination.md` (point at the ledger as the durable form)

## Acceptance criteria

Each test is written and shown FAILING before its implementation exists.

- [ ] `test_evidence_ledger.py` red, then green. Covers: a row missing `command` is
      refused; a row missing `result` is refused; duplicate `claim_id` is refused;
      append is single-writer and order-preserving; `resolve` matches `1,177` to a row
      recording `1177`; `resolve` reports an unmatched number as unresolved.
- [ ] `test_system_manifest.py` red, then green. Covers: a manifest with a subsystem
      that has zero members fails `check`; a duplicate member ref fails `check`;
      `mentions()` hits on a subsystem alias, not just its id; `missing_members()`
      returns the members absent from an evidence blob and `[]` when all are present.
- [ ] `code_claim_grounding_guard.py --self-test` green, including the NEW negative
      case: an answer naming a subsystem with only one of three members in evidence
      returns that subsystem as uncovered. This is the reproducer for the exact seam
      the RCA names.
- [ ] `test_client_output_evidence_gate.py` red, then green. Covers: an outreach file
      with a number absent from the ledger exits 2; the same number present in the
      ledger exits 0; a file outside `output/outreach/` exits 0; a number on a line
      carrying `{{UNVERIFIED}}` exits 0; the skip marker exits 0.
- [ ] `test_read_first_gate.py` red, then green. Covers: a first Write with no
      `anti-hallucination.md` Read in the transcript exits 2; with the Read present
      exits 0; a second Write in a session that already wrote exits 0; lessons
      surfaced with zero lesson bodies opened exits 2.
- [ ] `test_handoff_provenance_lint.py` red, then green. Covers: a handoff bullet
      carrying a number with no provenance marker exits 2; the same bullet with
      `[verified: <command>]` exits 0; with `{{UNVERIFIED}}` exits 0; a non-handoff
      file exits 0.
- [ ] Every gate's script is referenced from `settings-template.json` AND
      `.claude/settings.json`, or listed in `FLEET_ONLY`. Proof:
      `python3 q-system/.q-system/scripts/settings-template-sync-check.py` exits 0.
- [ ] `python3 validate-separation.py` exits 0 (no new separation or model-tier break).

## Patterns to follow (from this repo's own code)

- **Hermetic self-tests.** `code_claim_grounding_guard.py:_self_test` builds a temp
  repo so the test never depends on a repo-specific path. Every new test does the same.
- **Exit-code contract.** 2 = block with stderr fed back, 0 = pass. `test -f X &&
  python3 X` in the hook makes a missing script a no-op.
- **A stated HONEST BOUNDARY.** The grounding guard documents what it does not catch.
  Every gate here carries the same paragraph, because the RCA's first lesson is that
  reading a gate's stated boundary is part of trusting its silence.
- **Bypass by explicit marker, one per hook, no stacking** (`skill-hook-pairing.md`).
- **Allowlists load from a file at runtime, not from code.** Same reason the client's
  own QA validator loads its nickname map from a table: adding an entry is a data
  change, not a code change.

## Deliberate holes (stated, not hidden)

- The subsystem gate fires whenever a manifest subsystem is named and any member is
  missing from session evidence, including a purely forward-looking mention ("I'll
  look at the ingest chain next"). Chosen over a fuzzy assertiveness detector because
  fuzzy is not deterministic. The pressure valve is the existing skip marker.
- The read-first gate proves a lesson file was OPENED. It cannot prove the RIGHT
  lesson was opened, or that it was applied.
- The client-output gate exempts single-digit numbers (list markers, ordinals). Two or
  more significant digits must resolve.
- None of these gates see chat that ends without a Stop hook firing, and none survive
  `--no-verify`-style bypasses at the git layer.
