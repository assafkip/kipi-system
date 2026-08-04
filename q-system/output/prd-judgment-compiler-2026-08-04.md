# PRD: Judgment Compiler

**Date:** 2026-08-04
**Author:** Claude (Fable 5), from the founder's handoff brief `q-system/output/claude-judgment-compiler-handoff-2026-08-04.md`
**Status:** Implementing
**Priority:** P1 (high)
**Linear:** ASK-363

---

## 1. Problem

Kipi has cheap deterministic checks (hooks, gates, tests) followed by an LLM judge
(Codex review). The missing layer is the decision context that would let anyone —
human or model — calibrate that judge against the founder's actual triage
decisions. Without it, the judge cannot be trusted with any workflow disposition,
and every one of the founder's ~342 historical decisions is unusable for
calibration because the state it depended on was never frozen.

- **Evidence (verified v1 benchmark, `founder-judge-calibration-v1-run.json`,
  hashes recorded, session `019fcb14-613e-7dd0-a3d0-8da1e4fdfc9a`):**
  50 balanced cases (20 accepted / 20 rejected / 10 deferred). Judge given only
  finding text + severity: 40% exact agreement, 35% balanced accuracy, macro F1
  0.239, Cohen's kappa 0.032. Judge predicted `accepted` 45/50 times; rejected
  recall 0%, deferred recall 10%. Mean confidence 92.2%, mean confidence on
  wrong predictions 91.1%, 10-bin ECE 0.522. Post-stratified accuracy 73.3% —
  **below** the 76.6% historical accept-all baseline.
- **Impact:** The LLM judge is a confidently uncalibrated triage proxy. Every
  finding still costs a founder decision, and repeated identical decisions
  (duplicates, already-fixed, scope-removed) are re-made by hand because
  nothing records the pattern in a machine-checkable form.
- **Root cause (RCA `rca-founder-judge-calibration-context-and-temp-2026-08-03.md`):**
  the input contract was incomplete. The founder's disposition depends on
  workflow state the blind judge never received: duplicate status, prior
  remediation, cross-PRD ownership, scope changes, issue ordering, superseding
  decisions, receipt state, and current revisions. **A disposition is not a
  property of an objection. It is a property of an objection inside workflow
  state.** Additionally, the ledger (`findings_writer.py`) mutates records in
  place: decision-time context is destroyed the moment state moves on, so no
  retroactive dataset can ever be honest (v1's own leakage scars: case 049
  carried post-adjudication text; near-identical empty-manifest findings had
  different labels because surrounding PRD state differed).

## 2. Scope

### In Scope

- **Immutable triage episode receipts:** versioned, append-only, hash-chained
  ledger `.prd-os/judgments.jsonl` at the shared worktree ledger root (the
  `_ledger_root()` pattern from `prd_runner.py`, scar sp-bc42f1d3). Corrections
  append superseding receipts; old receipts are never mutated.
- **Deterministic decision-context assembler:** repo/PRD/issue/scope/duplicate/
  remediation/ordering state resolved by code with a source reference per fact;
  missing evidence stays `unknown`, never `false`.
- **Split judge contract:** `technical_validity` separate from
  `workflow_disposition`, one canonical reason-code enum, strict schema
  validation in code.
- **Deterministic disposition evidence gate:** `duplicate`,
  `already-remediated`, `owned-by-other-prd`, `scope-removed`, `out-of-scope`,
  `superseded` require stable references or the recommendation converts /
  fails (behavior split documented in Change 4).
- **Prospective v2 calibration dataset + evaluator:** context-complete receipts
  are the dataset; evaluator reports agreement, kappa, balanced accuracy, macro
  F1, per-class precision/recall, confusion matrix, ECE, human-review rate,
  unsupported-disposition rate, missing-context rate, per-reason-code results,
  population baseline. Runs read-only.
- **Deterministic 5% live sampling** with a recorded, reproducible rule, plus
  unconditional escalation of `needs-human` / missing-context /
  invalid-schema / unsupported-evidence cases.
- **Repeated-pattern detector → policy candidates** (evidence-backed, cannot
  self-install).
- **Integration:** `findings_writer.py set-disposition` (the real triage
  chokepoint) captures a receipt per adjudication; `kipi judgment` CLI family;
  `/prd-triage` command doc updated; capability-manifest test entry.

### Out of Scope

- Reconstructing context for the 50 historical v1 cases (would fabricate
  "decision-time" context; v1 stays a context-free stress-test and regression
  artifact — brief §5).
- Replacing Codex review or changing review thresholds.
- Auto-deciding any disposition class before its release gate passes
  (§6 gates; nothing passes them at ship time because zero prospective cases
  exist yet).
- Automatic gate installation from policy candidates (promotion goes through
  the existing human-reviewed prd-os path).
- A live LLM judge invocation wired into triage. The contract, hashes, and
  validation are built; running a model per finding is a follow-on decision
  once ≥50 prospective human decisions exist.
- General eval infrastructure beyond this closed loop.

### Non-Goals

- Claiming calibration. Until prospective evidence meets the release gates, the
  judge recommends; the founder decides.
- Treating workflow disposition as proof of technical validity (the split
  contract exists precisely to keep these apart).

## 3. Changes

### Change 1: Judgment Compiler module

- **What:** New single-writer module owning receipts, context assembly, judge
  contract validation, evidence gate, evaluator, sampling, and policy
  candidates.
- **Where:** `plugins/prd-os/scripts/judgment_compiler.py`
- **Why:** Root cause = no decision-time context is ever frozen (Section 1).
- **Exact change:** Subcommands
  `assemble | capture | verify | evaluate | sample-check | policy-candidates`
  plus `--selftest` (fully in-memory, read-only-safe — v1 RCA lesson).
  Ledger: `.prd-os/judgments.jsonl` under `prd_runner._ledger_root()`.
- **Scope:** prd-os plugin (skeleton; propagates via `kipi update`).

**Receipt schema v1 (frozen; strict — unknown fields fail validation):**

```json
{
  "schema_version": 1,
  "receipt_id": "jr-<sha256(content)[:16]>",
  "captured_at": "ISO-8601 UTC",
  "finding": {"prd_id": "", "finding_id": "", "severity": "", "body": "", "body_sha256": ""},
  "review": {"source": "codex-review|...|manual", "review_run_id": "string|null"},
  "repo_state": {"branch": "string|unknown", "commit_sha": "string|unknown", "dirty": "true|false|unknown"},
  "prd_state": {"path": "", "sha256": "string|unknown", "status": "string|unknown", "revision": "string|unknown"},
  "issue_state": {"issue_id": "string|null", "manifest_sha256": "string|unknown", "issue_order": ["..."]},
  "scope": {"source": "path#section|unknown", "sha256": "string|unknown"},
  "duplicates": [{"prd_id": "", "finding_id": "", "similarity": 0.0, "source": ""}],
  "remediation": [{"issue_id": "", "finding_id": "", "closed_at": "", "commit_sha": "string|null", "source": ""}],
  "related_prds": ["..."],
  "missing_context": ["dotted.field.paths that resolved unknown"],
  "judge": null,
  "human": null,
  "sampling": {"basis_sha256": "", "rule": "sha256(salt:basis) % 10000 < 500", "salt": "kipi-judgment-sample-v1", "sampled": false},
  "supersedes": "receipt_id|null",
  "prev_receipt_sha256": "sha256-of-previous-canonical-line|null"
}
```

`judge` when present: `{"model", "prompt_sha256", "input_sha256",
"output_sha256", "output": <judge contract below>, "converted_to_needs_human":
bool}`. `human` when present: `{"actor", "decided_at", "disposition":
"accepted|rejected|deferred|pending", "reason_code": <enum|null>,
"evidence_refs": [], "rationale": "string|null"}`.

Integrity: `receipt_id` is content-derived (sha256 of the canonical record
minus `receipt_id`); `prev_receipt_sha256` chains each line to the previous
line's canonical hash (first = null); `sequence` is a monotonic 1-based
position. `verify` re-walks the chain and fails on mutation, reorder, deletion,
duplicate id, broken link, schema violation, unknown enum, or
non-finite/out-of-range confidence.

**Deletion needs a second mechanism (found by self-attack, 2026-08-04, before
ship).** A prev-hash chain proves each retained line follows the previous one.
It cannot prove the chain is COMPLETE, because any prefix of a valid chain is
itself a valid chain: `head -1 judgments.jsonl` returned `VERIFY PASS` on a
2-receipt ledger. Three independent checks close it:

1. `sequence` must equal the line's position — catches middle deletion and
   reordering.
2. Tip anchor `.prd-os/judgments-tip.json` (`count`, `last_receipt_sha256`,
   `last_receipt_id`, `updated_at`), rewritten on every append — catches tail
   truncation, whole-file deletion, and last-receipt replacement. Written after
   the ledger append, so a crash between the two under-counts, which is
   deliberately not an error (a crashed write must not raise a truncation
   alarm). A missing anchor does not hard-fail: ledgers predating it still
   verify, because absence is not a claim.
3. `verify --cross-check` requires a receipt for every dispositioned finding,
   read from the findings ledgers — a source the judgment writer does not own,
   so it survives a writer that is wrong about itself. `--since` floors it so
   pre-feature findings do not report as thousands of false gaps.

**Honest boundary:** the anchor shares a writer with the ledger, so this is
tamper-EVIDENT (accidental truncation, crashed write, partial sync, naive
edit), not tamper-proof. Only `--cross-check` is independent.

**Judge output contract (exact fields, no extras):**

```json
{
  "technical_validity": "valid | invalid | uncertain",
  "technical_reason": "...",
  "workflow_disposition": "fix-now | already-remediated | duplicate | scope-removed | out-of-scope | defer | invalid | needs-human",
  "workflow_reason_code": "<canonical enum below>",
  "evidence_refs": ["..."],
  "missing_context": ["..."],
  "confidence": 0.0
}
```

**Canonical reason-code enum (from the brief; changes require repository
evidence recorded in a PRD):** `valid-fix-now`, `already-remediated`,
`duplicate`, `owned-by-other-prd`, `scope-removed`, `out-of-scope`,
`superseded`, `defer-dependency`, `defer-ordering`, `invalid-finding`,
`insufficient-context`, `needs-human`.

**Evidence-ref grammar (stable references):** `finding:<prd_id>/<finding_id>`,
`issue:<issue_id>`, `prd:<prd_id>`, `receipt:<issue_id>` (remediation receipt),
`judgment:<receipt_id>`, `commit:<sha>`, `test:<path>`, `scope:<path#section>`,
`spillover:<id>`.

### Change 2: Deterministic decision-context assembler

- **What:** `assemble --prd <id> --finding <id>` emits a context packet from
  repository state only.
- **Where:** same module.
- **Why:** the LLM may reason over recorded facts, never manufacture workflow
  state (brief §2; v1 disagreements were dominated by hidden state).
- **Exact change:** resolves — each with `source` — duplicates
  (`findings_xref.cross_reference`, the existing advisory engine),
  remediation receipts (`cfg.receipts_path` rows matching prd/finding),
  PRD path+sha256+frontmatter status+git revision, issue manifest hash and
  ordering (PRD `## Issues` manifest), scope section hash, repo
  branch/commit/dirty (git; `unknown` when git cannot answer), related PRDs,
  superseding receipts (from the judgments ledger). Anything unresolvable is
  listed in `missing_context` and valued `unknown` — never `false`.
  The packet carries its own canonical `packet_sha256`; that hash is the
  judge's `input_sha256` and the sampling basis.
- **Scope:** prd-os plugin.

### Change 3: Split judge contract validation

- **What:** Code-level validation of the judge output contract (Change 1 JSON),
  separate from the human disposition record.
- **Why:** v1 collapsed technical judgment and workflow disposition into one
  label; a finding can be technically valid and still be a duplicate, already
  fixed, out of scope, or deferred (brief §3).
- **Exact change:** strict field set (extras fail), enum checks, finite
  confidence in [0,1], `input_sha256` must equal the context packet hash
  (stale hash fails), `output_sha256` must match the canonical output hash.
- **Scope:** prd-os plugin.

### Change 4: Disposition evidence gate

- **What:** Deterministic validation that evidence-requiring dispositions carry
  resolvable stable references.
- **Why:** unsupported dispositions must not pass as facts (brief §4).
- **Exact change:** required refs — `already-remediated` → `receipt:`/`commit:`/
  `test:`; `duplicate` → `finding:`/`issue:`/`spillover:`; `owned-by-other-prd`
  → `prd:` + `issue:`; `scope-removed`/`out-of-scope` → `scope:`; `superseded`
  → `judgment:` resolving to an existing receipt. **Behavior split (the choice
  the brief asks to document):** a **judge** recommendation missing a required
  ref is converted to `needs-human` and flagged
  (`converted_to_needs_human: true`) — matching the existing Kipi contract in
  the `cmd_advisory` script (findings_writer.py): advisory model output
  degrades to a warning, exit code stays 0. A
  **human** decision missing a required ref **fails validation (exit 2)** —
  matching the existing hard contract that `rejected`/`deferred` require
  `--rationale` in `cmd_set_disposition`.
- **Scope:** prd-os plugin.

### Change 5: Triage-flow integration (the real caller)

- **What:** `findings_writer.py cmd_set_disposition` captures a judgment
  receipt for every adjudication; new optional flags `--reason-code`,
  `--evidence` (repeatable), `--actor`, `--judge-run <json>`.
- **Where:** `plugins/prd-os/scripts/findings_writer.py` (single call site —
  line 481 function), `plugins/prd-os/commands/prd-triage.md` (usage doc).
- **Why:** a standalone script with no caller is not done (brief §Integration);
  set-disposition is the one chokepoint every triage decision already flows
  through.
- **Exact change:** validate reason-code + evidence gate *before* the findings
  file is written (fail fast, nothing mutated); after the existing write +
  spillover sync, append the receipt. Receipt append failure is loud (exit 2,
  divergence named). Kill switch `KIPI_JUDGMENT_CAPTURE=0` (rollback path).
  When `--reason-code` is absent (legacy callers), the receipt records
  `reason_code: null` and `missing_context: ["human.reason_code"]` — honest
  unknown, no fabricated default. `/prd-triage` doc instructs passing the code.
- **Scope:** prd-os plugin.

### Change 6: `kipi judgment` CLI family

- **What:** `kipi judgment <capture|assemble|verify|evaluate|sample-check|policy-candidates>`
  delegating to the module (the `kipi linear` nested-case precedent).
- **Where:** `kipi` (repo root), usage text.
- **Why:** brief §Integration — CLI only through the existing command
  architecture; founder never remembers paths.
- **Scope:** skeleton root.

### Change 7: Prospective v2 evaluator + sampling

- **What:** `evaluate` scores context-complete receipts where both judge and
  human are present (superseded receipts excluded); `sample-check` exposes the
  deterministic sampling decision.
- **Why:** brief §5–6. v1 must stay frozen; v2 is prospective-only.
- **Exact change:** agreement measured at two levels: (a) legacy 3-class
  disposition (judge `workflow_disposition` mapped: `fix-now`→accepted;
  `already-remediated`/`duplicate`/`scope-removed`/`out-of-scope`/`invalid`→
  rejected; `defer`→deferred; `needs-human`→excluded from automation metrics,
  counted in human-review rate) and (b) reason-code exact match where the human
  code exists. Release gates evaluated on (a) plus kappa. Sampling:
  `int(sha256("kipi-judgment-sample-v1:" + basis_sha256), 16) % 10000 < 500`
  — reproducible from the receipt alone, no RNG. Escalations (needs-human,
  missing-context, invalid schema, unsupported evidence) are unconditional and
  independent of the 5%.
- **Release gates (Kipi's own, not Airbnb's):** ≥88% exact agreement, kappa
  ≥0.80, ≥80% recall per automated class, zero schema/evidence-gate bypasses,
  valid receipt per automated disposition, ≥50 prospective human decisions.
  `evaluate` prints gate status; until green the judge only recommends.
- **Scope:** prd-os plugin.

### Change 8: Policy-candidate detector

- **What:** `policy-candidates` groups override/agreement patterns by
  (reason_code, context signature) and appends proposals to
  `.prd-os/judgment-policy-candidates.jsonl` (shared ledger root).
- **Why:** repeated decisions must become deterministic checks that run before
  the LLM judge (brief §7).
- **Exact change:** each candidate freezes pattern definition, supporting
  receipt ids, case count, counterexamples + the search that produced them
  (a candidate without a counterexample search fails validation), proposed
  deterministic rule, proposed tests, expected false-positive risk, exact
  integration point (`before-llm-judge`, promotion via the existing prd-os
  review path + `gate_register`). The module contains **no** code path that
  writes `gates.jsonl`, hooks, or settings — enforced by a grep-the-tree test
  (single-writer chokepoint pattern).
- **Scope:** prd-os plugin.

## 4. Change Interaction Matrix

| Change A | Change B | Interaction | Resolution |
|----------|----------|-------------|------------|
| 5 (triage capture) | 1 (ledger) | every set-disposition appends | writer validates before findings mutation; append failure is loud exit 2 |
| 4 (evidence gate) | 5 | human decision w/ evidence-requiring code but no ref | hard fail before anything is written |
| 4 | 3 (judge contract) | judge output w/ missing required ref | converted to needs-human, flagged, never silently dropped |
| 2 (assembler) | 3 | judge input hash must equal packet hash | stale hash fails capture |
| 1 | 8 (candidates) | candidates cite receipt ids | `verify` checks refs resolve; candidates cannot alter receipts |
| 5 | existing spillover sync | deferred findings still fan out to spillover | receipt append runs after `_sync_spillover_for_finding`; both fire |
| 7 (evaluate) | v1 artifacts | none — separate script, separate dataset | v1 files untouched; regression R-1/R-2 |

## 5. Files Modified

| File | Change Type | Lines Added | Lines Removed |
|------|------------|-------------|---------------|
| `plugins/prd-os/scripts/judgment_compiler.py` | Add | ~1100 | 0 |
| `plugins/prd-os/scripts/findings_writer.py` | Edit | ~60 | ~2 |
| `plugins/prd-os/commands/prd-triage.md` | Edit | ~25 | ~5 |
| `kipi` | Edit | ~20 | 0 |
| `plugins/prd-os/tests/test_judgment_compiler.py` | Add | ~850 | 0 |
| `q-system/.q-system/capability-manifest.json` | Edit | +1 entry | 0 |
| `q-system/output/prd-judgment-compiler-2026-08-04.md` | Add | this file | 0 |
| `q-system/output/judgment-compiler-operator-guide.md` | Add | ~80 | 0 |

## 6. Test Cases

Test-first: the five gap repros below were run RED against the pre-change tree
(receipts absent, no split contract, no gates), then implementation proceeds
until green. All tests use `fake_repo` tmp fixtures (fable-discipline test
isolation; fixtures derived from the real producer schemas, not invented).

### Gap repros (brief §test-first)

| # | Type | Scenario | Pass Criteria |
|---|------|----------|---------------|
| G-1 | DET | Adjudicate a finding, then change the PRD; decision-time context must survive | receipt freezes prd sha/status at decision time; `verify` still green after PRD edit |
| G-2 | DET | Record technically-valid-but-duplicate | receipt holds `technical_validity: valid` AND `workflow_disposition: duplicate` as separate fields |
| G-3 | DET | `duplicate` with no owning reference | human: exit 2; judge: converted to needs-human |
| G-4 | DET | Re-verify a judge run from stored hashes | recomputed packet hash == stored `input_sha256`; corrupted packet fails |
| G-5 | DET | Sample the same decision twice, two processes | identical sampled verdict; rule reproducible from receipt fields alone |

### Negative tests (brief-required, all DET)

| # | Scenario | Expected |
|---|----------|----------|
| N-1 | duplicate without owning reference | human exit 2 / judge → needs-human |
| N-2 | already-remediated without receipt/commit/test ref | same |
| N-3 | scope-removed without scope record | same |
| N-4 | missing context represented as `false` | assembler emits `unknown` + missing_context entry; a packet with fabricated `false` fails validation |
| N-5 | PRD changed after receipt capture | old receipt verifies green; new capture on stale packet exits 2 |
| N-6 | mutated historical receipt line | `verify` fails naming the line |
| N-7 | duplicate receipt ID | capture refuses; `verify` fails |
| N-8 | broken prev_receipt_sha256 | `verify` fails |
| N-9 | unknown reason code | exit 2 |
| N-10 | confidence outside [0,1] / NaN / bool | exit 2 |
| N-11 | judge output with extra fields | exit 2 |
| N-12 | historical v1 case presented as context-complete | `evaluate` refuses records lacking a context packet hash (reconstructed-context marker impossible: schema has no path to inject v1 rows) |
| N-13 | policy candidate with no counterexample search | candidate validation fails |
| N-14 | policy candidate self-install | no promote/install path exists; grep-tree test proves module never writes gates.jsonl/hooks/settings |
| N-15 | tail truncation (drop last receipt) | `verify` exits 2 naming the count mismatch |
| N-16 | whole-ledger deletion | `verify` exits 2 |
| N-17 | middle-receipt deletion | `verify` exits 2 (sequence contiguity) |
| N-18 | last receipt replaced with a re-hashed forgery | `verify` exits 2 naming the tip anchor |
| N-19 | tip anchor missing (legacy ledger) | `verify` passes — absence is not a claim, no hard-fail on upgrade |
| N-20 | dispositioned finding with no receipt | `verify --cross-check` exits 2; `--since` floor excludes pre-feature findings |

Negative-fire checks (rules must NOT fire): legacy `set-disposition` without
`--reason-code` still succeeds (receipt records honest null);
`KIPI_JUDGMENT_CAPTURE=0` disables capture and triage behaves exactly as
before; `pending` re-dispositions capture a superseding receipt, never mutate.

## 7. Regression Tests

| # | What to Verify | How to Verify | Pass Criteria |
|---|----------------|---------------|---------------|
| R-1 | v1 self-test | `python3 q-system/.q-system/scripts/founder-judge-calibration.py --selftest` (main checkout) | SELFTEST PASS |
| R-2 | v1 dataset verification | `... verify --dataset q-system/output/founder-judge-calibration-v1.jsonl` (main checkout) | VERIFY PASS |
| R-3 | existing findings/triage behavior | `pytest plugins/prd-os/tests/ -q` | all pre-existing tests pass |
| R-4 | remediation receipt readers | prd_runner archive gates unchanged (no edits to those functions) + R-3 | pass |
| R-5 | read-only execution | run `--selftest` + `verify` in a chmod-555 sandbox | no traceback, no write attempt |
| R-6 | `kipi check` | `kipi check` | exit 0 |
| R-7 | wiring | `/wiring-check` report | all rows evidenced |

## 8. Rollback Plan

| Change | Rollback Steps | Risk |
|--------|---------------|------|
| Triage capture (5) | `export KIPI_JUDGMENT_CAPTURE=0` (no code change), or revert the findings_writer edit | none — flag path leaves legacy behavior byte-identical |
| Module + CLI (1,6,7,8) | delete `judgment_compiler.py`, revert `kipi` case block | ledger files remain (append-only, inert without reader) |
| Ledger data | never deleted; append-only by design | n/a |

## 9. Change Review Checklist

| Check | Status | Notes |
|-------|--------|-------|
| Changes are additive | Pass | only additions + optional flags; legacy call shapes unchanged |
| No conflicts with existing enforced rules | Pass | single-writer, no-orphan-findings, skill-hook-pairing respected |
| No hardcoded secrets | Pass | repo-local state only |
| Propagation path verified | Pending | `kipi update --dry` at wiring stage (plugins/ + kipi are skeleton-owned) |
| Exit codes preserved | Pass | 0/2 contract matches findings_writer |
| AUDHD-friendly | Pass | one command per action, no pressure language |
| Test coverage for every change | Pass | G-1..G-5, N-1..N-14, R-1..R-7 |

## 10. Success Metrics

| Metric | Current | Target | How to Measure |
|--------|---------|--------|----------------|
| Prospective context-complete decisions | 0 | ≥50 before any auto-decide | `kipi judgment evaluate` (counts) |
| Exact agreement (v2, prospective) | n/a | ≥88% before auto-decide | `kipi judgment evaluate` |
| Cohen's kappa (v2) | n/a | ≥0.80 | same |
| Per-class recall (automated classes) | n/a | ≥80% each | same |
| Unsupported-disposition rate | n/a | 0 pass-throughs (all converted/blocked) | same + N-1..N-3 |
| Receipt chain integrity | n/a | `verify` green on live ledger | `kipi judgment verify` |
| v1 regression | PASS | stays PASS | R-1/R-2 |

## 11. Implementation Order

1. This PRD (done — this file).
2. Gap repros + negative tests written; red run recorded.
3. `judgment_compiler.py` core: canonical hashing, receipt schema, chain
   append/verify — then evidence gate — then assembler — then judge contract —
   then evaluator/sampling — then policy candidates. (Each lands with its
   tests green before the next starts.)
4. findings_writer integration + prd-triage doc + `kipi` CLI + manifest entry.
5. Full suite + regressions + `kipi check` + read-only run.
6. Codex review; every finding dispositioned **through the new capture path**
   (the system adjudicates its own review). Wiring check. Operator guide.
   Status → Done.

## 12. Open Questions

| Question | Owner | Deadline | Resolution |
|----------|-------|----------|------------|
| When ≥50 prospective decisions exist, which model runs the judge (codex exec vs claude -p) and at what cadence? | Assaf | after calibration data accrues | open — machinery is model-agnostic; hashes bind whichever runs |
| Should `needs-human` findings page via slack-notify.sh? | Assaf | after first live week | open — default: surfaced in `/prd-triage` output only |

## 13. Wiring Checklist (MANDATORY)

| Check | Status | Notes |
|-------|--------|-------|
| PRD file saved to `q-system/output/prd-judgment-compiler-2026-08-04.md` | Pass | this file |
| All code/config changes implemented and tested | Pending | |
| New files listed in folder-structure rule | N/A | plugin scripts dir already canonical |
| New conventions referenced in root CLAUDE.md | N/A | no new convention; CLI documented in `kipi` usage |
| New rules referenced in folder-structure rules list | N/A | no new rule file |
| Memory entry saved | Pending | at closeout |
| `kipi update --dry` confirms propagation | Pending | skeleton files changed (plugins/, kipi) |
| `kipi update` run | Pending | founder-authorized run at merge, not from worktree |
| PRD Status updated to Done | Pending | after wiring report |
