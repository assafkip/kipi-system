# Changelog

All notable changes to the `prd-os` plugin are recorded here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow semantic versioning; see `README.md` for the bump policy and the distinction between plugin version and config schema version.

## [0.13.5] - 2026-08-04

### Fixed (Codex review, PR #101 round 5) — closed as a CLASS
- The coverage check compared `disposition` only, so a hand-edited `rationale`
  passed as covered. Rounds 2-5 each found a different unchecked field
  (identity only, then disposition, then rationale). Rather than patch a third
  field, `_decision_fingerprint` is now the single definition of "the same
  decision" and is applied to BOTH sides, so a newly frozen field cannot go
  unchecked on one of them. Empty-vs-absent rationale is normalised, because
  that difference is not a decision change and must not read as tampering.

## [0.13.4] - 2026-08-04

### Fixed (Codex review, PR #101 round 4)
- **The approval gate read the ledger without the writer's lock.** capture
  appends the receipt and then writes the tip; observed between those two the
  ledger holds N+1 records against a tip of N, which the new chain check calls
  "receipts BEYOND the tip anchor" and blocks approval over a concurrent capture
  that was perfectly fine. The writer got a lock in 0.12.0 and the reader never
  did. Ledger and tip are now read together under `ledger_lock`.

## [0.13.3] - 2026-08-04

### Fixed (Codex review, PR #101 round 3)
- **The approval gate trusted receipts it never verified.** It called
  `read_ledger` (JSON parse only) and never `verify_ledger`, so a receipt
  appended by hand -- correct prd_id, finding_id and disposition, broken chain
  -- authorized approval. A hash chain no consumer checks is decoration, and
  this gate is the consumer that matters. It now verifies the chain and tip
  first and refuses on any integrity error.

## [0.13.2] - 2026-08-04

### Fixed (Codex review, PR #101 round 2)
- **A receipt for an EARLIER decision satisfied the gate.** Coverage was
  identity-only `(prd_id, finding_id)`, so hand-editing the findings file to a
  different disposition left the stale receipt standing in for a decision that
  was never captured -- and approval passed. The check now compares the
  finding's current disposition against the latest human-bearing receipt, and
  says so specifically when they disagree.

## [0.13.1] - 2026-08-04

### Fixed (Codex review, PR #101)
- **The required receipt gate failed OPEN on an unreadable ledger.** It caught
  every exception and returned 0, defended in the PR body as "a bug in the check
  must not cause an approval outage". That conflated a buggy gate with a corrupt
  ledger, and a corrupt or truncated ledger is precisely the integrity failure
  the gate exists to catch. It now fails CLOSED on any read error; the only
  fail-open case left is the compiler not being installed at all.
- Substring matching let a missing receipt for `prd-alpha-2` block approval of
  `prd-alpha`. Now an exact `<prd_id>/` prefix match.

## [0.13.0] - 2026-08-04

### Added
- **The Judgment Compiler is now REQUIRED, not just available.** It shipped
  writing a receipt on every triage and requiring one nowhere, so
  `KIPI_JUDGMENT_CAPTURE=0`, a hand-edited findings file, or an ignored capture
  failure each left a hole no gate could see -- and a ledger with unnoticed
  holes cannot be the calibration set it exists to be. `_judgment_receipt_gate`
  now blocks `advance approved` when a finding dispositioned since
  `JUDGMENT_RECEIPT_FLOOR` carries no receipt. The floor is the point: ~342
  findings were adjudicated before the compiler existed and can never have
  receipts, and a gate that cannot be satisfied gets switched off.

### Fixed
- Spillover evidence refs matched a value in ANY JSON field, so an id quoted
  inside a description resolved as if it were the item (sp-fcb3573e).

## [0.12.0] - 2026-08-04

### Fixed (Codex review round 5, PR #97)
- **`release_gates.passed` could return True over a ledger containing decisions
  that bypassed the evidence gate.** The PRD listed "no schema or evidence-gate
  bypasses" as a release condition and no code read it: `_release_gates` was
  called before the bypass rates were even computed. Executed repro: 60 perfect
  cases plus one reason-code-less rejection returned `passed=True` with
  `ungated_decision_rate=0.016`. Since `passed` is the field that authorizes
  auto-decide, a caller could have enabled automation on known-invalid
  calibration data. Two gates added (`zero_gate_bypasses`,
  `zero_unsupported_judge_dispositions`) and the rates are now computed before
  the gates that read them. Minor version bump: the evaluate output gains
  fields and previously-passing gate sets can now legitimately fail.

### Note on the review process
- Codex round 5 observed that this defect lived in code unchanged since the
  first feature commit, and concluded rounds 1-4 were miscalibrated. Recorded
  rather than argued with: four review passes and a mutation run all cleared a
  gate that never read its own documented condition.

## [0.11.6] - 2026-08-04

### Fixed (Codex review round 3, PR #97)
- **`reanchor` could bless a truncated ledger when the anchor was missing.**
  The round-1 implementation filtered every "tip anchor" error out of its chain
  check — including the MISSING-anchor error — so deleting the anchor AND
  truncating, then reanchoring, wrote a fresh anchor over the surviving prefix
  and made the deletion permanent. This falsified that function's own comment
  claiming it "can never launder tampering"; the comment is now corrected
  rather than quietly dropped. Reanchor repairs exactly one state (an anchor
  that exists and under-counts) and refuses a missing anchor over a non-empty
  ledger, pointing at `verify --cross-check` — the independent source — to
  establish what should be there. An empty ledger with no anchor stays a clean
  no-op, so a fresh repo is not made to cry wolf.

## [0.11.5] - 2026-08-04

### Fixed (Codex review round 2, PR #97)
- **`reanchor` shipped in Python and in the docs but the `kipi judgment`
  dispatcher rejected it**, so the documented recovery for an interrupted
  anchor write did not exist at the CLI. The Python subparsers and the bash
  allowlist are two hand-edited lists of the same thing; a `TestCliParity`
  class now diffs them both ways and checks the usage text, so a subcommand
  cannot ship reachable-in-one-place again. Verified by re-introducing the bug:
  the parity tests go red.

## [0.11.4] - 2026-08-04

### Fixed (Codex review, PR #97 — both findings had executed reproducers)
- **Receipts beyond the tip anchor were trusted.** An under-counting anchor was
  treated as fine so a crashed anchor-write would not false-alarm; the cost was
  that receipts past the anchor sat OUTSIDE deletion detection while `verify`
  still reported "chain intact". Verify now refuses when
  `len(records) != tip.count` in either direction, and a new `reanchor`
  subcommand re-covers a legitimate tail. Reanchor refuses a truncated ledger
  and refuses a broken chain, so it cannot launder tampering: it only ever
  extends coverage over receipts that already verify.
- **A refused receipt rolled the findings file back but left the spillover
  append standing.** Because that ledger is append-only, the standing gate saw
  permanent open work for a disposition the command had just reported as rolled
  back. Spillover now fans out only after the receipt lands.

## [0.11.3] - 2026-08-04

### Testing
- Pinned the shared-ledger-root behavior with a test. During this PRD's own
  dogfood run, a sandbox that had copied a `.git` directory wrote its receipts
  into the MAIN checkout's ledger — `_ledger_root` follows
  `git rev-parse --git-common-dir`, which is the intended shared-across-worktrees
  behavior, but it surprises exactly where it hurts. The behavior was right and
  the harness was wrong; a test now states which, and `capture` reports the
  resolved ledger path in its output so the operator can see where a receipt
  actually landed.

## [0.11.2] - 2026-08-04

### Testing
- Mutation-tested the suite: 17 single-invariant corruptions applied to a copy,
  16 killed. The run exposed that 7 checks were shadowed by other checks in
  every test (`sequence`, the prev-hash link, and 5 read-path validators the
  suite never reached because it only exercised the write path). Added a
  `reseal_ledger` helper that rebuilds a fully self-consistent chain so each
  test can break exactly one invariant, plus a real 6-process concurrency test.
  The single surviving mutation is a defensive build-time duplicate-id assert
  that no normal path can reach; its enforced half is the read-side check, and
  the code now says so rather than implying coverage it does not have.

## [0.11.1] - 2026-08-04

### Fixed (adversarial review, 17 findings)
- **Blocker — concurrent capture forked the ledger and every writer exited 0.**
  `capture_episode` was an unlocked read-modify-append while the ledger sits at
  the SHARED worktree root by design. Now `fcntl.flock`-guarded across
  read+build+append+anchor. Repro: 6 concurrent captures -> 6 receipts, chain
  intact.
- Deleting the tip anchor restored the entire truncation hole for one `rm`; a
  missing anchor over a non-empty ledger is now an error (an empty ledger with
  no anchor is still a clean fresh repo).
- Evidence refs are RESOLVED, not just prefix-matched: `finding:`, `prd:`,
  `issue:`, `judgment:`, `receipt:`, `spillover:`, `commit:`, `test:`/`scope:`
  are each opened, and a ref pointing at nothing is refused.
- `set-disposition` rolls the findings file back when receipt capture fails, so
  the two ledgers cannot diverge on partial failure.
- `verify` resolves policy-candidate receipt citations and checks case_count.
- Scope regex anchored (`## Out of Scope` used to hash as `## Scope`); bare
  `except Exception` narrowed and partial duplicate lists discarded;
  `needs-human` abstentions no longer counted as human overrides; degenerate
  Cohen's kappa returns 0.0 not 1.0; judge stores raw + stored output hashes and
  validates the stored one; unvalidated packets no longer exit 1 with a
  traceback; receipts deepcopy their packet; `human_review_rate` uses a set union.

### Known bypass (deliberately not closed here)
- Omitting `--reason-code` skips the evidence gate. Closing it changes the
  contract of a command every fleet instance inherits, so it is its own issue
  (spillover `sp-1caf70c9`). Interim: the receipt records a null code plus a
  `human.reason_code` missing-context entry, and `evaluate` reports
  `ungated_decision_rate` so the bypass is counted rather than assumed.

## [0.10.2] - 2026-08-04

### Fixed
- **Judgment ledger truncation was undetectable.** Found by self-attack before
  the feature shipped: a prev-hash chain proves each retained line follows the
  previous one, but any PREFIX of a valid chain is itself a valid chain, so
  `head -1 judgments.jsonl` still returned `VERIFY PASS`. Deletion was the one
  tamper class the chain structurally could not see. Closed with three
  independent checks: a monotonic `sequence` field (catches middle deletion and
  reordering), a tip anchor `.prd-os/judgments-tip.json` recording count + last
  hash (catches tail truncation and whole-file deletion; tamper-EVIDENT not
  tamper-proof, since the same writer owns both files), and
  `verify --cross-check` which requires a receipt for every dispositioned
  finding by reading the findings ledgers — an independent source the judgment
  writer does not control. A missing tip anchor does not hard-fail, so ledgers
  predating the anchor still verify.

## [0.10.0] - 2026-08-04

### Added
- **Judgment Compiler** (`scripts/judgment_compiler.py`, PRD
  prd-judgment-compiler-2026-08-04, ASK-363): append-only, hash-chained triage
  episode receipts in `.prd-os/judgments.jsonl` (shared worktree ledger root),
  a deterministic decision-context assembler (unknown stays unknown, every
  fact carries a source), a split judge contract (technical_validity separate
  from workflow_disposition, canonical 12-code reason enum), a disposition
  evidence gate (duplicate / already-remediated / scope-removed /
  out-of-scope / owned-by-other-prd / superseded require stable references:
  judge output degrades to needs-human, human decisions hard-fail), a
  prospective v2 evaluator with release gates (≥88% agreement, kappa ≥0.80,
  ≥80% per-class recall, ≥50 cases), deterministic 5% sampling, and a
  policy-candidate detector that cannot self-install.
  `findings_writer.py set-disposition` now captures a receipt per
  adjudication (new optional flags `--reason-code`, `--evidence`, `--actor`,
  `--judge-run`; kill switch `KIPI_JUDGMENT_CAPTURE=0`). Paired tests:
  `tests/test_judgment_compiler.py` (48 cases, written red-first).

## [Unreleased]

### Added
- **Execution-discipline layer (fable-discipline merge, prd-fable-discipline-2026-07-04)**:
  the fable-discipline skill (recon before edit, verify-against-a-copy with a
  negative self-test, single-writer chokepoints, scar-anchored why-comments)
  merges INTO prd-os as its execution-discipline layer, ending the
  two-sibling-systems arrangement (prd-os owned the work-item procedure,
  fable-discipline owned the per-edit procedure; one idea split across two
  load paths). Rationale for the shape of the merge: the Leonxlnx/taste-skill
  production lesson — graduated phrasing ("use sparingly") gets ignored in
  production; only binary zero-or-fail rules and mechanical counts hold —
  matching this repo's own scars (autonomy-contract phrase patching, hook
  blind spots). The pre-merge SKILL.md is preserved verbatim at
  `skills/prd-os/references/fable-discipline-v1.md`. Future behavior changes
  to the discipline layer get an entry here plus a de-kipi'd export to the
  public mirror (assafkip/fable-discipline, founder decision 2026-07-03);
  the executable blocker for mirror drift is
  `scripts/export-fable-mirror.sh --check` (exits non-zero on divergence;
  required_check on every discipline-layer issue).

## [0.5.0]

### Added
- **Cross-PRD findings advisory**: `findings_xref.py` surfaces prior
  `rejected`/`deferred` findings from sibling PRDs that closely match a pending
  finding (token-shingle Jaccard — a deterministic read-only script, no LLM). Wired into
  `/prd-triage` via `findings_writer.py advisory`, which swallows every xref
  failure so it can never block triage. Threshold resolves flag > config
  `xref_threshold` > 0.6, validated to a finite [0,1] value.
- **`/prd-os-init`** (`prd_os_init.py`): one-time bootstrap that writes
  `.prd-os/config.json` with defaults. Idempotent, non-destructive, validates
  what it writes. The runners previously pointed at it but it did not exist.
- **`/prd-map`** (`prd_map_runner.py` + `codebase_map.schema.json`): facts-only
  codebase snapshot for grounding PRDs. `codebase_map_path` added to config.
- **PRD template sections**: `Alternatives considered`, `Scenarios`, and
  `Resolved decisions` give the cold-context reviewer the decision space.
- **Review rubric**: a penalty-of-being-wrong lens for assigning severity
  (alongside the existing dimensions, including Recurring gap classes).

### Fixed
- `kipi-dsse` `issue_runner.py` defaulted `issues_dir` to `issues` while
  `config.py` used `.prd-os/issues`; a no-config repo wrote issue specs to one
  path and the runner looked in another. Aligned to the canonical default.

### Removed
- Legacy issue-execution stack: `scripts/issue_runner.py`,
  `hooks/scope_hook.py`, `hooks/stop_gate.py` (and their tests). Issue
  execution and scope/stop enforcement are owned by the `kipi-dsse` plugin
  ("the spine goes native"); the prd-os copies were unreachable (no `issue-*`
  commands here) and could not even read kipi-dsse's state schema, so both
  plugins' hooks fired on every edit with the prd-os copy failing open. prd-os
  now ships no hooks. The PRD-side concurrency guard is unaffected — it reads
  `active-issue.json` directly via `concurrency.py`.

### Notes
- All 0.4.0 capabilities preserved (spillover gate, persona/skeptic review,
  gap-classes dimension). The additive parts of this release add capability;
  the removal deletes only dead duplicates, no reachable behavior.

## [0.4.0]

### Added
- **Spillover gate** (`.prd-os/spillover.jsonl`): out-of-scope findings are
  captured to a durable ledger, and `prd_runner.py spillover add|list|check|resolve`
  manages it. `gates run` now FAILS while any spillover item is open, so an
  out-of-scope finding can never be silently dropped. `resolve` requires a closed
  issue (or an explicitly recorded `--void` reason).
- A `deferred` triage disposition AUTO-creates an open spillover item
  (findings_writer); `rejected` stays terminal. Moving a finding off `deferred`
  clears its item.
- `prd-archive` + `issue-closeout` report each spillover item, its resolving
  issue, the fix, and the system impact.

## [0.3.0]

### Added
- `templates/gap-classes.md`: a catalog of recurring defect classes (scaling,
  security, correctness/concurrency, cross-cutting) distilled from a
  reproducer-first, adversarially-reviewed build where ~50 defects were caught
  before merge. General by construction; no product specifics.
- `templates/review-rubric.md`: a sixth review dimension, "Recurring gap
  classes," that checks a PRD's design against the catalog.
- `commands/prd-review.md`: `/prd-review` now reads `gap-classes.md` alongside
  the rubric and feeds it to Codex, so dimension 6 has its source.

## [0.1.0] - 2026-04-16

### Added
- Initial plugin scaffold.
- `.claude-plugin/plugin.json` manifest (name, version, description, author).
- Directory tree for `commands/`, `hooks/`, `scripts/`, `templates/`, `tests/`, and `skills/prd-os/`.
- `skills/prd-os/SKILL.md` placeholder describing the planned system.
- `README.md` documenting the package layout, portable-core vs repo-local split, and versioning policy.
- This changelog.

### Notes
- Scaffold only. No runner logic, no commands, no hooks, no templates, no tests are wired.
- No changes to the host repo's settings, commands, or runtime.
- Config schema version not yet defined; lands with the runner port in step 3.
