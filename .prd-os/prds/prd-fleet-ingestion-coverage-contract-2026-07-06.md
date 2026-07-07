---
id: prd-fleet-ingestion-coverage-contract-2026-07-06
title: Fleet-shared ingestion coverage contract (canonical + kipi-update + drift-check)
status: draft
created_at: 2026-07-06T23:52:27Z
updated_at: 2026-07-07T00:10:28Z
owner: assaf
reviewers: []
findings_path: .prd-os/findings/prd-fleet-ingestion-coverage-contract-2026-07-06-findings.jsonl
---

# Fleet-shared ingestion coverage contract

## Problem

Four instances ingest documents, and each has a DIFFERENT, partial answer to the
question "did I read the whole file, and is what I read real?":

| Instance | Path | Coverage counting | Provenance integrity | Formats |
|----------|------|-------------------|----------------------|---------|
| QEP (`Pure_spectrum_Q`) | `.../qep_agent` | STRONG (attempted/captured/`truncated`, `UnreadFileError` reconciliation, fail-closed crediting) | none | csv/xlsx/docx/txt/zip |
| product (`ktlyst-hub/product`) | `ktlyst_v2/ingestion` | WEAK (no receipt, silent `max_pages` cap, empty-engine short-circuit) | STRONG (page-anchored `block_id` per unit, construction-site grounding gate, verbatim source-derivation) | pdf only |
| kipi-investigations (`intel/...`) | `investigations/ingest` | none (8 silent-loss modes, audited) | none | pdf/docx/xlsx/csv/md/txt |
| 4_points (`consulting/...`) | ad-hoc per-case + `pdf-extract.py` | half (PDF page-token manifest, buried) | none | pdf-ish, per-case |

Two consequences the founder named (2026-07-06): (1) each tool loses evidence a
different way, and (2) they DRIFT — a capability added to one never reaches the
others. For a fleet of investigation/extraction tools where the whole value is
"we read everything and every claim traces to real evidence," divergent
ingestion is a credibility hole that widens with every independent change.

No single tool has the complete answer. QEP proves "we read every unit." The
product proves "every unit we kept is real and every citation traces to one."
The complete receipt is BOTH, and today it lives in neither.

## Goals

- ONE canonical ingestion-coverage contract, defined once in the skeleton,
  imported by all four instances, so their capabilities are identical and cannot
  silently diverge.
- The contract combines the two proven halves: QEP's attempted-vs-captured
  counting + reconciliation-fails-loud, AND the product's per-unit addressable
  provenance + construction-site grounding gate.
- Distribution rides the existing `kipi update` channel; a deterministic
  `--check` required_check blocks any instance that drifts from canonical.
- Reader primitives cover pdf / docx / xlsx / csv, so every adopter gains the
  formats it does not read today (capability uplift, not just parity).
- Adoption is incremental: an instance can consume the contract type + one reader
  at a time; the drift-check governs only what has been adopted.

## Non-goals

- Not rewriting each instance's downstream logic (entity extraction, OE queries,
  IR observations). The contract governs the READ boundary and its receipt only.
- Not adding OCR quality work; a no-text page is REPORTED as a coverage gap, same
  as today.
- Not forcing same-day migration of all four. This PRD ships the contract + the
  drift-check + the first adopter; the other three adopt via their own PRDs.
- Not a runtime service. This is a library + a check, no network, no daemon.

## Proposed approach

### The contract (best-of-breed from both audits)

A single module (canonical in the skeleton). Two composable layers:

```
# Layer 1 — COUNTING (from QEP): did we read every unit?
@dataclass ReadResult:
    unit: str            # "page" | "sheet" | "row" | "fenced_block" | "doc_part"
    attempted: int       # units the source actually contains (source-truth)
    captured: int        # units whose content was kept
    truncated: bool      # a cap/failure kept us from full capture (fail closed)
    dropped: list[Drop]  # one entry per dropped unit, WITH a reason
    def recall(self) -> float   # captured/attempted (1.0 if attempted == 0)

# reconciliation gate (from QEP's UnreadFileError): every enumerated unit must
# have a result or reconcile() raises and names the miss. No silent skip.
def reconcile(enumerated: list[UnitId], results: list[ReadResult]) -> None

# Layer 2 — PROVENANCE (from the product): is every kept unit real + traceable?
BLOCK_ID = "{kind}.p{page}.{index}"   # stable, page-anchored, format-validated
@dataclass Block:
    block_id: str        # deterministic id, unique (dupes fail closed)
    unit: str; page: int; bbox: tuple | None
    text: str            # DERIVED from source, never caller-supplied

# construction-site gate (from ir/extractor): a downstream reference to a
# block_id not in the read set raises; claim text is derived from the block,
# not supplied. "Captured" becomes unfakeable.
def ground(reference_block_id: str, read_blocks: dict[str, Block]) -> Block
```

The two layers are the complete receipt only together: Layer 1 counts what was
read; Layer 2 proves each counted unit is real and every citation traces back to
one. QEP contributes Layer 1, the product contributes Layer 2, and the shared
contract is the first place both exist at once.

### Reader primitives

One reader per format (`read_pdf`, `read_docx`, `read_xlsx`, `read_csv`, `read_md`),
each returning `(list[Block], ReadResult)`. Each fixes the audited losses for its
format at the source (all sheets not first, formula cells preserved/counted,
header/footer parts read, code-fence content kept, `max_pages`/`max_sheets` caps
COUNTED into `truncated`, swallowed per-unit failures recorded in `dropped`).

### Distribution + drift-check (founder pick: skeleton module + kipi update + --check)

- Canonical module lives ONCE in the skeleton (kipi-system). Exact importable
  placement is issue-1's concern (candidates: a `q-system/`-tree package on the
  kipi-update sync set, vs a dedicated python lib under `plugins/`); the
  constraint is that `kipi update` already rsyncs it to every instance and app
  code can import it via a documented shim.
- A `--check` script (modeled on `export-fable-mirror.sh --check`) diffs each
  instance's copy against a fresh export of canonical and exits non-zero on
  drift. It is wired as a required_check + a `kipi update` preflight, so a drifted
  or hand-edited instance copy is caught deterministically, not by inspection.
- Adoption ledger: the check governs only modules an instance has adopted (a
  manifest per instance), so partial adoption is legal and still drift-protected.

Reproducer-first: the contract ships with a planted-loss harness (the existing
`coverage-proof-harness.py`, generalized) that asserts every reader reports every
planted loss; each adopter re-runs it against its own wiring.

## Alternatives considered

- **Let each tool port QEP independently** (the earlier plan) — Rejected: three
  copies diverge the first time one changes; that is the exact drift the founder
  called out. One canonical source is the only structural fix.
- **Adopt QEP's contract as-is** — Rejected: QEP has no provenance layer. The
  product audit showed the receipt is incomplete without per-unit `block_id` +
  the grounding gate. Best-of-breed beats best-single.
- **Publish a pip package instead of skeleton-sync** — Considered, not chosen
  (founder pick was kipi-update). A package adds a publish + version-bump ritual
  that fights "always identical"; kipi update already reaches every instance.
- **Per-instance mirror export (fable-style)** — Close second; folded in as the
  MECHANISM of the `--check`, but canonical distribution rides kipi update, not a
  separate per-instance export invocation.

## Scenarios

- **A capability is added once, reaches all four.** Someone adds xlsx
  merged-cell handling to the canonical `read_xlsx`. `kipi update` ships it to
  every instance; the `--check` confirms each instance now matches canonical.
  No per-tool reimplementation, no drift.
- **An instance hand-edits its copy.** An analyst tweaks the ingest module inside
  4_points directly. The `--check` required_check fails on the next run/commit,
  naming the drifted file, forcing the change back to canonical.
- **The product gains docx/xlsx.** The product is PDF-only today. Adopting the
  shared readers gives it docx/xlsx/csv coverage with the receipt + provenance
  built in.
- **A citation cannot be faked.** A downstream claim references `t.p4.2`; the
  grounding gate confirms that block was actually read and derives the claim text
  from it. A reference to an unread block raises.

## Resolved decisions

- **Homogeneity is the governing principle.** Decided: all document-ingesting
  instances carry identical capabilities via one canonical contract, never
  per-tool copies. `[USER-DIRECTED]` (2026-07-06: "always lean toward homogeneity
  ... critical they are always on the same page with their capabilities").
- **Distribution = skeleton module + kipi update + `--check` drift blocker.**
  `[USER-DIRECTED]` (2026-07-06, AskUserQuestion).
- **Contract = QEP counting + product provenance (best-of-breed).** Rationale:
  two audits proved neither tool has the complete receipt alone.
  `[CLAUDE-RECOMMENDED -> pending review]`.
- **Four adopters.** kipi-investigations, QEP, 4_points, product. Product
  inspection cleared by founder (cluster preflight, 2026-07-06). `[USER-DIRECTED]`.

## Risks and rollback

- **Blast radius is fleet-wide by design.** A canonical change reaches every
  instance via kipi update. Mitigation: additive-only contract, per-instance
  adoption manifest, the `--check` as the deterministic backstop, and the
  planted-loss harness as the regression gate before any propagation.
- **Import-path fragility across three parent dirs.** The four instances live
  under `intel/`, `consulting/`, `ktlyst-hub/`. Mitigation: issue-1 pins ONE
  documented import shim; the `--check` proves the imported copy is canonical.
- **Adoption stalls (a tool keeps its old reader).** Mitigation: ship the
  contract WITH the first adopter (kipi-investigations, already drafted) as proof;
  the other three adopt via their own already-drafted PRDs.
- **Rollback:** the contract is a new module + a check. Un-adopt an instance by
  reverting its import + dropping it from the adoption manifest; canonical stays.
  No data migration.

## Open questions

- Import placement: `q-system/`-tree package vs a `plugins/` python lib. Which is
  cleanest for app code under all three parent dirs? (issue-1)
- Does the product's construction-site gate belong in the shared contract, or stay
  product-local and be REFERENCED by the contract? (It is downstream of the read;
  the shared piece may be just the `block_id` + `ground()` primitive, not the full
  IR schema.)
- Threshold policy for `recall`-below-flag: per-format default vs global.
- Is the adoption manifest per-instance state, or centralized in the skeleton?

## Persona Review

### Skeptic

Q1: Strongest argument against? Four tools with different jobs may not want
identical ingestion; a shared contract could over-couple an OE-query tool to an
investigation graph tool. Counter: the contract governs only the READ boundary +
receipt, which is genuinely identical work everywhere; downstream logic stays
per-tool. The audits showed the read boundary is where all four independently
fail.

Q2: Smallest experiment to disprove? Ship the contract + adopt it in ONE tool
(kipi-investigations). If wiring the import + drift-check across even one instance
is disproportionately painful, the kipi-update distribution assumption is wrong
and a package is the real answer.

Q3: Cheapest non-build alternative? A shared SPEC doc (the receipt shape written
down) that each tool implements to, plus a conformance test suite. No shared code,
just a shared standard. Rejected as the full answer (a spec drifts as fast as
code with no single source) but the conformance harness is worth building regardless.

## Issues

<!--
Populated after /prd-review + triage. One entry per accepted finding.
Intended breakdown (finding_ids assigned post-review):
  1. canonical contract module: ReadResult + reconcile() + Block + ground(); import
     placement + shim; the planted-loss conformance harness.
  2. reader primitives (pdf/docx/xlsx/csv/md), each fixing its audited losses,
     each returning (blocks, receipt).
  3. distribution: kipi-update carries canonical; --check drift-blocker wired as a
     required_check + kipi update preflight; per-instance adoption manifest.
  4. first adopter proof: wire kipi-investigations _ingest_one onto the contract
     (its instance PRD becomes the consumer), harness green end-to-end.
Each needs: id, finding_id, title, allowed_files, required_checks (reproducer-first
+ the --check), bypass_check.
-->

```json
[]
```
