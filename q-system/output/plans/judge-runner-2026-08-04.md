# Plan: wire a judge runner into triage (ASK-363, sp-320d30e3)

**Status:** planned, not started. Sequenced behind Sana's PR #101 split, because
she is editing `judgment_compiler.py` and `findings_writer.py` right now.

## What and why

The Judgment Compiler's entire evaluation half is unreachable. Verified by
running greps and reading the code, not recalled:

- `judgment_compiler.py:1371` counts a calibration case only when a receipt has
  **both** `judge` and `human`.
- `/prd-triage` (`plugins/prd-os/commands/prd-triage.md:55-59`) passes
  `--rationale`, `--reason-code`, `--evidence`. Never `--judge-run`.
- Grepping `plugins/ q-system/ kipi*` for `judge_run` outside tests returns
  **consumers only** (`_load_judge_run` at :770, the argparse flag at :1895)
  plus one selftest fixture at :1665. **No producer exists.**

So every triage writes a human-only receipt, `judged` stays empty forever, and
the release gates (88% agreement, kappa 0.80, 50 cases) are unreachable by
construction. `evaluate`, `policy-candidates` and `sample-check` are machinery
with no wired input. The handoff's claim that running a triage "starts the
calibration clock" is wrong: it starts the provenance clock only.

**This is a known recurring defect class in this repo.** Lesson
`a-gate-s-input-needs-a-production-producer-not-just-a-test-t` (2026-07-13):
"a consumer without a production producer is dead wiring, and tests that supply
the consumer's input verify the consumer's logic while hiding that the wiring is
dead." That is exactly what happened. ~90 tests pass on a judge path no
production code can reach, because every one of them hand-builds the judge run.

## Approach (the pick)

Add a **judge subcommand** that assembles the packet, calls one LLM, and writes
a judge-run JSON. The schema check is not new prose: the existing
`validate_judge_output` script function (`judgment_compiler.py:343`) plus its
pytest cases are the deterministic blocker, and `_load_judge_run` (:770) refuses
an unbound or malformed run at exit 2. Then `/prd-triage` calls the subcommand
and passes `--judge-run <path>` to `set-disposition`.

Options considered:

1. **Judge subcommand in `judgment_compiler.py`, invoked by the triage command.**
   THE PICK. The contract, the packet assembler and the validator already live
   there; a producer next to them shares `assemble_packet` and cannot drift from
   `validate_judge_output`.
2. Standalone script under `q-system/.q-system/scripts/`. Rejected: it would
   duplicate packet assembly, and the fleet-homogeneity principle says a shared
   capability lives in one canonical source.
3. Batch-judge historical findings retroactively. Rejected outright: this is the
   exact mistake the whole issue exists to correct. A judge scoring a decision
   whose workflow state it never saw is what produced kappa 0.032.

## The design question that was actually hard, and its answer

`input_sha256` on the judge run must equal `packet["packet_sha256"]`
(`judgment_compiler.py:784`). If the judge assembles one packet and `capture`
assembles another, the binding fails and no judged receipt can ever be written.

**Resolved by reading the code:** `packet_hash` (`judgment_compiler.py:151-154`)
excludes both `packet_sha256` and `assembled_at`. Two assemblies of unchanged
state hash identically. Further, the packet's finding block carries `body` and
`severity` only, so `_write_all` changing `disposition`/`resolved_at` does not
move the hash.

Consequence: the judge subcommand can assemble independently and still bind. No
packet file needs threading through the triage path.

## Blindness constraints (these make or break the dataset)

- The packet is already clean of the label. `assemble_packet` (:714-734) copies
  `prd_id, finding_id, severity, body, body_sha256` into the finding block, and
  `duplicates` entries carry ids plus similarity only. No disposition, no
  rationale. Verified by reading.
- **The judge gets no tools.** `duplicates[].source` is a filesystem path to a
  findings file, and `prior_receipts` lists receipt ids. A judge that can open
  files reads prior human dispositions straight out of both. Pass the packet as
  text, tools disabled.
- **Do not show the judge's answer to the founder before they decide.** If the
  human sees the prediction and agrees, measured agreement is inflated and the
  calibration set is worthless. Run it, capture it, display it only after the
  disposition is set.

## Files to touch

- `plugins/prd-os/scripts/judgment_compiler.py` — new `judge` subcommand, prompt
  constant, `prompt_sha256` derived from that constant.
- `plugins/prd-os/commands/prd-triage.md` — call the judge, pass `--judge-run`.
- `plugins/prd-os/tests/test_judgment_compiler.py` — cases below.
- `kipi` CLI allowlist — `TestCliParity` diffs bash against the Python
  subparsers both ways, so a new subcommand fails the suite until it is added.
- `plugins/prd-os/CHANGELOG.md`, `plugins/prd-os/.claude-plugin/plugin.json`.

## Output contract (already fixed, do not redesign)

Judge run JSON: `{model, prompt_sha256, review_run_id?, input_sha256, output}`
(`_load_judge_run` :776-777). `output` carries exactly the 7
`JUDGE_OUTPUT_FIELDS`, `workflow_disposition` in the 8 `WORKFLOW_DISPOSITIONS`,
`workflow_reason_code` in the 12 `REASON_CODES`, `evidence_refs` matching
`EVIDENCE_REF_RE`, finite `confidence` in [0,1]. Extra fields rejected.

`EVIDENCE_REQUIREMENTS` (:90-97): six reason codes require refs with specific
prefixes, and refs are **resolved** (opened), not pattern-matched. Judge output
failing the gate degrades to `needs-human` rather than erroring, so the runner
does not have to satisfy it. But a judge that never cites refs converts
constantly and scores nothing, since `JUDGE_TO_LEGACY["needs-human"] is None`
excludes it from metrics. Track `converted_to_needs_human` as a health signal.

## Acceptance criteria

- [ ] Reproducer first: a test asserting `evaluate()` reports zero judged cases
      after a full production-path triage. Red today. It documents the gap and
      is the end-to-end shape lesson point 3 demands.
- [ ] `judge` subcommand exists, assembles the packet, emits a judge run whose
      `input_sha256` binds against a separately-assembled packet.
- [ ] Malformed LLM output is retried a bounded number of times (3, per the
      self-healing-retry contract), then fails loudly. No silent fallback to a
      default disposition: a fabricated prediction poisons the calibration set
      worse than a missing one.
- [ ] The judge is invoked with tools disabled. A test asserts it.
- [ ] `/prd-triage` passes `--judge-run` end to end on a sandbox repo.
- [ ] After one full sandbox triage, `evaluate` reports one judged case.
- [ ] Live `.prd-os/` hash unchanged by the test run (the ledger follows
      git-common-dir, so a sandbox that copies a `.git` writes production).
- [ ] `TestCliParity` green.
- [ ] **Mechanical detection for the recurring class** (lesson point 4): a check
      asserting every field the receipt schema reads has a non-test write site.
      This class has now produced a defect twice. It earns a script, not
      vigilance.

## Patterns to follow (from this repo, not generic advice)

- **Pin the model.** Every headless `claude -p` job in this fleet exports
  `ANTHROPIC_MODEL`. Unpinned jobs silently rode a cheaper model and burned 3%
  of a weekly budget in an hour. Record the resolved model in the judge run's
  `model` field so a model change shows up in the ledger rather than
  confounding a kappa shift.
- `claude -p` as the LLM client is the established pattern here: no API key,
  uses the founder's subscription.
- Why-comments in these files cite the specific review round and executed
  reproducer that motivated them. Match that density.
- `fable-discipline`: recon before edit, negative self-test, single-writer
  chokepoint.

## Open risk, named not hidden

A judge whose prompt is tuned after seeing disagreements stops being an
independent predictor. The deterministic blocker is the receipt schema itself:
`prompt_sha256` is a required field on every judge run (`_load_judge_run`
:776-780 raises at exit 2 without it), so a changed prompt is a visible
discontinuity in the ledger rather than a silent one. Add a pytest case
asserting two runs with different prompts carry different hashes. When that hash
moves, prior cases are a different experiment and should not be pooled.
