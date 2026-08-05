# Changelog

All notable changes to the `prd-os` plugin are recorded here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow semantic versioning; see `README.md` for the bump policy and the distinction between plugin version and config schema version.

## [0.16.2] - 2026-08-04

### Fixed (Codex review, PR #103 round 6) — an append-only ledger cannot roll back
Third distinct defect in one transaction. The sequence was mutate findings ->
append receipt -> write anchor, with rollback-of-findings as the failure path.
Rollback cannot undo an append, so any failure after the append left a phantom
receipt in the append-only ledger while the command reported refusal for a
decision that had already taken effect.

The root cause was the rollback model, not the anchor write. `capture_episode`
now RECOVERS FORWARD past the append: the append is the single irreversible
step, everything before it is validated and reversible, and everything after
it is derived and recomputable. The tip anchor is a pure function of the
ledger (count + last hash), so a failed anchor write is a stale derived
artifact, not a lost transaction.

`_write_anchor_or_warn` makes one bounded inline repair attempt and never
escalates to a refusal: exit 0, findings and ledger agree, the receipt is
durable, and only the anchor is stale.

### Also corrected
The warning names `verify` for inspection, not `reanchor` unconditionally.
`reanchor` repairs an anchor that EXISTS and under-counts but deliberately
refuses a MISSING anchor (with no baseline it cannot tell a crashed write from
a truncation), which is exactly the state when the failure hits the first
receipt. The first draft of the warning gave advice that would have been
refused in that case.

A stale docstring in `capture_episode` claiming an under-counting anchor is
"deliberately NOT an error" was removed; PR #97 changed that, and `verify` now
reports receipts beyond the anchor.

### Tests
`TestNoPhantomReceiptWhenTheAnchorWriteFails` INDUCES the failure (a directory
occupying the tip path makes the write raise OSError) rather than asserting
about it. Proven red against a mutant restoring the raise-and-roll-back
behaviour: 2/2 red, 2/2 green restored.

## [0.16.1] - 2026-08-04

### Fixed (Codex review, PR #103 round 5) — the disposition transaction lost updates
`cmd_set_disposition` acquired the ledger lock AFTER `_load_findings`, so it
serialised stale snapshots instead of the read-modify-write transaction. Two
concurrent dispositions each loaded the same snapshot, each mutated its own
finding in its own copy, and each wrote the WHOLE list back: the second
silently reverted the first while both processes exited 0 and both receipts
recorded success. Lost disposition state, invisible to both writers.

The lock now opens before the load and closes after the receipt append, so the
read, mutation, packet assembly, findings write and receipt append are one
critical section.

Taken UNCONDITIONALLY. The judgment-disabled branch previously used a
`nullcontext`, reasoning that with no receipt coming there was no window to
close. That reasoning was about the write-to-receipt observation gap
(sp-0c725cde) and does not extend to lost updates, which happen with or
without a receipt — the reproducer demonstrates the race with
`KIPI_JUDGMENT_CAPTURE=0`, on the branch that had no lock at all.

### Tests
`TestDispositionTransactionIsOneCriticalSection` drives the real
`set-disposition` CLI in two concurrent processes against a real findings file.
The review's own reproducer stubbed seven seams, which cannot distinguish a
real race from one manufactured by its harness.

The case is ITERATED eight rounds. A lost update is a race: a single attempt
wins or loses on timing alone, and the single-shot first version passed against
the unfixed file on one run and failed on the next — flaky in both directions
and worthless as a guard. Eight rounds make the red reliable (3/3 runs red
pre-fix) while the green stays deterministic (3/3 green post-fix), because the
fix admits no losing interleaving.

## [0.16.0] - 2026-08-04

### Changed — one constructor for the judge's view, replacing four seams
PR #103 went through four adversarial Codex rounds that found five majors,
every one in the same dimension: the judge's blindness and citation integrity.
Blindness was enforced at four independent seams and three failed — tool
availability (`--allowedTools` is a permission allowlist, not an availability
control), prompt content (`duplicates[].source` survived), stdout (a note
saying "do not show this" instead of not emitting it), and evidence refs (a
syntax check, then existence, but never relevance). A property enforced at N
sites is not a chokepoint, and a fifth clean round would not have proved
sufficiency — only that the reviewer had not yet found the next insufficient
guard. This applies fable-discipline's single-writer rule to an invariant
instead of a data path.

`judge_view(packet) -> (view, citable)` is now the single writer of both:

- **The perceivable view** is built from the `JUDGE_VIEW_SPEC` ALLOWLIST, not
  by deep-copying the packet and popping known pointers. A field a future
  assembler starts copying is invisible by default. `duplicates[].source` and
  `remediation[].source` (paths into ledgers carrying other findings' human
  dispositions) are both absent; `scope.source` is kept because it is the only
  citable proof of scope.
- **The citable set** is the closed set of refs derivable from that same view.
  Relevance stops being a rule to enforce and becomes structural: you can only
  cite what you were shown. Membership is strictly stronger than the two layers
  it replaces — a ref in the set necessarily exists, because the view was
  assembled from real state.

All nine accepted prefixes are classified: `finding:`, `judgment:`, `prd:`,
`issue:`, `receipt:`, `commit:` and `scope:` are closed over view fields, so
the existence-only carve-out is EMPTY. `spillover:` and `test:` are refused by
construction — no spillover block exists in the packet and nothing enumerates
test paths, so the judge cannot honestly cite either. Nothing is stranded:
`duplicate` keeps `finding:`/`issue:` and `already-remediated` keeps
`receipt:`/`commit:`.

`repo_state.commit_sha` is deliberately NOT citable. It is the CURRENT commit
and always exists, so an existence check accepted `commit:<HEAD>` as proof of
the very remediation under review. Only `remediation[].commit_sha` counts.

`run_judge` no longer takes a `Config`: with citations checked by membership,
nothing in it needs to open the repo. `_judge_block_from_run` takes the citable
set too, so a hand-written `--judge-run` file cannot smuggle a non-citable ref
into a receipt. `_packet_duplicate_refs` and the per-ref resolution inside
`run_judge` are deleted as subsumed.

### Tests
29 new cases in `TestJudgeViewIsTheOnlyConstructorOfTheJudgesWorld`, all
table-driven, each mutation-proven to fail for the reason it names:
blacklist-pop instead of allowlist kills 10, making HEAD citable kills exactly
1, and "refuse everything" kills the 8 survival cases while leaving the
refusal cases green. The survival table over all nine prefixes is the
acceptance criterion: with an empty carve-out, "refuse everything" would pass a
membership test trivially while converting every disposition to needs-human and
scoring zero calibration cases.

Two pre-existing tests were fixed rather than the gate weakened: the G-2 case
cited finding-1 as its own duplicate against a zero-duplicate packet (green
only because relevance went unchecked) and now carries a real producer-written
duplicate candidate.

## [0.15.7] - 2026-08-04

### Fixed (Codex review, PR #103 round 4) — the judge binding was broken outright
`capture_from_triage` assembled the context packet AFTER the disposition write.
`findings_xref.cross_reference` computes duplicate candidates only for findings
whose disposition is currently `pending`, so the judge assembled while the
finding was pending and saw cross-PRD candidates, and by capture time those
candidates were gone, the packet hash had moved, and `_load_judge_run` refused
the run as stale. **Every finding with a cross-PRD duplicate candidate was
un-capturable with a judge run.**

The packet is now assembled BEFORE the write, inside the same critical section,
and passed into `capture_from_triage`. That fixes the binding and is also the
semantically correct moment: a receipt freezes DECISION-TIME context, and
decision time is before the decision is applied.

**On the design claim this falsifies.** The plan held that the judge could
assemble independently because `packet_hash` excludes `assembled_at` and
`packet_sha256`. That exclusion is real and was verified. The conclusion did not
follow: it needed the underlying state to be UNCHANGED between the two
assemblies, and the disposition write is precisely a change to that state. The
earlier binding test passed because its fixture had no duplicates — it asserted
the property on the one input incapable of exercising it.

## [0.15.6] - 2026-08-04

### Fixed (Codex review, PR #103 round 3) — a duplicate claim must cite a packet candidate
`EVIDENCE_REQUIREMENTS["duplicate"]` accepts any `finding:`/`issue:`/`spillover:`
prefix, and `resolve_evidence_refs` resolves `issue:` by checking that a spec
file exists. So the judge could cite ANY real issue in the repo as proof that a
finding duplicates something, with no duplicate candidate in its packet at all —
and that unsupported decision was scored as supported.

Prefix and existence are each necessary and neither is sufficient. The missing
property is RELEVANCE: a claim has to be checkable against the view the judge was
actually given. A `duplicate` reason code may now only cite a candidate from the
packet's own `duplicates` list; anything else is dropped and
`evidence_gate_errors` degrades the disposition to needs-human.

Scoped to `duplicate` deliberately. Other codes legitimately cite refs the packet
does not enumerate (`commit:` for already-remediated, `scope:` for scope-removed),
and rejecting those would convert every disposition to needs-human and score
nothing — the same failure in the opposite direction. A paired negative
self-test guards that edge.

**Attribution:** `evidence_gate_errors` and `EVIDENCE_REQUIREMENTS` are untouched
by rounds 1-3; the prefix-only check is original code. Round 1's resolution fix
strictly narrowed this hole without closing it, so this is an independent
pre-existing defect, not a regression introduced by a prior round.

## [0.15.5] - 2026-08-04

### Fixed (Codex review, PR #103 round 2) — the judge summary leaked its own prediction
`cmd_judge` printed `workflow_disposition` in its stdout summary. `/prd-triage`
runs that command inside the founder's interactive session, so the prediction
landed in the transcript they read BEFORE setting a disposition — the exact
contamination the blindness rule exists to prevent. A founder who sees the
prediction and agrees inflates measured agreement, and the calibration set stops
measuring anything.

The original shipped the leak AND a `note` field telling the reader not to show
it. That is prose doing a job that belongs to code: the value was already on
screen by the time anyone read the warning. The summary now withholds the
prediction; the run file still records it, and `set-disposition --judge-run`
consumes it without displaying it.

## [0.15.4] - 2026-08-04

### Fixed (Codex review, PR #103 round 1) — two majors, both dataset-integrity
- **The judge was not actually blind.** `_judge_argv` passed `--allowedTools ""`,
  which is a permission ALLOWLIST and does not remove tool availability. The
  availability control is `--tools ""` (`claude --help`: "Use "" to disable all
  tools"). The paired test asserted the wrong flag, so it encoded the bug rather
  than catching it — a test can only protect the property it actually names.
- **Judge citations were never resolved.** `validate_judge_output` checks ref
  SYNTAX, so an invented but well-formed ref like `finding:prd-nope/finding-999`
  satisfied the evidence gate and was stored as a supported decision that the
  release gates counted. Judge refs now go through `resolve_evidence_refs`, which
  opens each one; unresolvable refs are DROPPED rather than retried, leaving
  `evidence_gate_errors` to degrade the disposition to needs-human — the gate
  working, already counted as `converted_to_needs_human`.

  This one was self-inflicted twice over: the judge prompt promised that refs are
  resolved by `resolve_evidence_refs`, and that same sentence was what satisfied
  the prompt-only-enforcement guard. A gate cleared with an untrue claim about
  our own code. The claim is now true.

## [0.15.3] - 2026-08-04

### Fixed (Codex review, PR #102 round 3 minor — sp-9dc72a7e)
`cross_check_findings` documented the deleted PRD-date exemption and pointed at
`prd_runner._prd_predates_floor`, a function that no longer exists. A docstring
naming a deleted helper is a false claim about the code, and the next reader
would have gone looking for it. Rewritten to state what the gate actually does
(no date logic at all) and to record why all three date shapes failed. Zero
references to the dead names remain in either script.

## [0.15.2] - 2026-08-04

### Changed
- Restacked the judge runner onto the 0.14.2 receipt gate (no date exemption, cross-check under the writer lock). No behaviour change in the judge runner itself.

## [0.15.1] - 2026-08-04

### Added — the fail-soft judge call is now countable
`/prd-triage` continues without `--judge-run` when the judge call fails, so a
model outage costs a calibration case rather than an author's ability to close
findings. That trade is right, but it failed SILENTLY: nothing counted human
receipts carrying no judge, so a judge erroring on every triage for a month was
indistinguishable from "not enough triage volume yet" — both leave `cases` short
of 50 with a red gate and no way to tell which. That is the same silent-hole
class this whole feature exists to close, and the same shape as 41c0876.

`evaluate` now reports `unjudged_decision_rate` (human receipts with no judge
block / human receipts) and gates on it via `zero_unjudged_decisions`. Threshold
is literally zero, matching `zero_gate_bypasses`: a tolerance here would be a
budget for losing calibration cases to an outage.

## [0.15.0] - 2026-08-04

### Added — the judge runner, the producer that never existed (sp-320d30e3)
The Judgment Compiler's entire evaluation half was unreachable. `_load_judge_run`
and `--judge-run` existed, `evaluate` counted a calibration case only when a
receipt carried BOTH `judge` and `human`, and NO production code ever wrote a
judge run: `/prd-triage` never passed the flag. Every triage produced a
human-only receipt, `judged` stayed empty forever, and all four release gates
(50 cases, 88% agreement, kappa 0.80, per-class recall) were unreachable by
construction. ~90 tests passed on that path because every one of them
hand-built the judge run.

- **`kipi judgment judge --prd <id> --finding <id> --output <f>`** assembles the
  packet, calls one LLM through `claude -p`, validates the reply against the
  existing `validate_judge_output`, and writes a judge run. Wired into
  `/prd-triage`, which now passes `--judge-run`.
- **The judge runs with tools OFF.** `duplicates[].source` is a path to a
  findings file and `prior_receipts` lists receipt ids; a judge that can open
  files reads prior HUMAN dispositions out of both, and the calibration set
  stops measuring prediction and starts measuring leakage. `source` is also
  dropped from the prompt text (not the packet, so the hash still binds).
- **Bounded retry (3), then a loud failure.** No fallback disposition: a
  fabricated prediction poisons the calibration set worse than a missing one.
  A failed judge writes no run file at all.
- **The prompt is pinned by `prompt_sha256`**, a required receipt field, so
  tuning the prompt after seeing disagreements is a visible discontinuity in
  the ledger rather than a silent redefinition of the experiment.
- The model is pinned and recorded on each run, so a model change shows up in
  the ledger instead of confounding a kappa shift.
- `/prd-triage` degrades rather than blocks: if the judge call fails, triage
  continues without `--judge-run`. A model outage costs one calibration case,
  never an author's ability to close findings.

### Added — mechanical detector for a class that has now bitten twice
`test_every_receipt_populating_flag_has_a_production_caller` fails when a flag
that is the sole production input to a receipt field is passed by no slash
command and no `kipi` dispatcher path. Definition sites are deliberately not the
corpus: an `add_argument` proves the flag exists, which was never in doubt. Run
red before the fix, naming `--judge-run` exactly.

## [0.14.2] - 2026-08-04

### Fixed (Codex review, PR #102 round 2) — BLOCKER: the floor exempted the future
A PRD-creation-date floor exempts every FUTURE decision on a pre-floor PRD, not
just the legacy ones. 35 of the 36 real PRDs predate the floor, so the gate was a
near-permanent no-op — the exact opposite of "receipts are required from here on".

The signal was wrong, so the mechanism is deleted rather than hardened a third
time. `_prd_predates_floor`, `_PRD_ID_DATE` and `_PRD_DATE_EARLIEST` are gone and
the gate reads no date at all: this gate fires when a PRD is APPROVED, and a PRD
being approved now is being decided now, whatever date its id carries. A test
asserts none of those three names comes back, so the class is provably gone
rather than merely unused.

Measured before removing the exemption, because "a gate that cannot be satisfied
gets switched off" is a real risk that deserved a number: of the 36 real PRDs, 21
are archived and 13 approved and can never reach this gate again. Exactly ONE is
still in-review, with 13 dispositioned findings, and its remedy is one
`set-disposition` re-run per finding, which mints the receipt as a side effect.

This retires the whole date-inference lineage: PR #101 rounds 2/7/8
(`resolved_at`), 0.14.0 (prd-id date), 0.14.1 (date-shape hardening).

### Fixed (Codex review, PR #102 round 2) — MAJOR: the lock did not span the check
The gate read the ledger under `ledger_lock`, RELEASED it, and only then
cross-checked the findings files. A concurrent, perfectly valid triage landing in
that gap writes a disposition the stale ledger snapshot cannot see, so approval
false-blocks on a missing receipt that does exist. The round-4 fix locked the
read; the comparison needed the same span. Both now run inside one critical
section. The paired test asserts `ledger_lock` depth > 0 at the moment
`cross_check_findings` is called — re-entrancy makes that probe safe.

## [0.14.1] - 2026-08-04

### Fixed (review of PR #102) — the date class had RELOCATED, not died
`_prd_predates_floor` matched a date-SHAPED suffix and then string-compared it,
so `prd-evade-0000-00-00` and `prd-evade-1970-01-01` each bought a free
exemption from the receipt requirement. That is precisely the defect 0.14.0
claimed to kill: the floor moved off `resolved_at` because a strippable field
handed out a free pass, and a suffix no calendar can produce handed out the same
pass through the new mechanism. 0.14.0's own docstring made the argument against
it ("the alternative is the same hole in a new shape") and then did not apply it.

The suffix is now parsed with `strptime` AND checked against a plausibility
floor, both failing closed. `strptime` alone is insufficient: `1970-01-01`
parses perfectly. The bound (2026-01-01) is MEASURED, not guessed — the 36
prd_ids under `.prd-os/findings/` span 2026-05-13 to 2026-08-04, so it sits
months before the earliest real PRD and cannot false-block one.

Regression is table-driven so the next relocation of this class is caught by an
existing check rather than by review. Two of its rows (`2026-02-30`,
`2026-06-31`) exist only because a mutation run showed the real-date guard could
be deleted with every other row still green: the plausibility floor happens to
subsume `0000-00-00`, and string ordering happens to subsume `2026-13-45`.

## [0.14.0] - 2026-08-04

### Changed — PR #101 split: the integrity half is required, the agreement half warns
PR #101 took 7 Codex review rounds and rounds 7 and 8 were regressions caused by
the round-6 fix. The 8 rounds partition cleanly, so the PR was split rather than
patched a ninth time.

- **Kept as blocking (rounds 1-5, integrity).** Fail closed on an unreadable
  ledger, exact `prd_id` prefix match, verify the chain before trusting a
  receipt, and read under the writer's lock. Four defects, zero self-inflicted
  regressions. These protect the calibration set: `cmd_evaluate` reads ONLY the
  ledger, so a missing receipt is a permanent invisible hole in it.
- **Demoted to a warning (rounds 6-8, field agreement).** `_decision_fingerprint`
  compared the MUTABLE findings file against the IMMUTABLE receipt. It caused two
  of its own regressions, and three of its four tests existed to stop it blocking
  legitimate work rather than to catch a real threat. When the two disagree the
  receipt is still the honest record, so `advance approved` now prints a warning
  and does not block. A gate that false-blocks gets switched off, and an off gate
  protects nothing.
- **`evaluate` reports `decision_disagreement_count`** and gates on it
  (`zero_decision_disagreements`). The demotion is not a silent drop: blocking a
  human's approval over drift is a false block, blocking AUTOMATION over it is
  the right severity. Same shape as 41c0876, which made the release gates read
  the evidence-gate bypass rate.

### Fixed — the date-inference defect class, killed by construction
Rounds 2, 7 and 8 were ONE defect: inferring "was this decided after the floor"
from `resolved_at`, a mutable strippable field on a hand-editable file. The
round-8 code admitted the inference was undecidable ("undateable AND unclaimed:
cannot judge, do not guess") and left a documented hole — switch capture off,
strip the date, and the missing receipt is invisible.

The gate runs at `advance approved` for ONE named PRD, and PRD ids carry their
creation date. So the floor is now read from the PRD id and no `resolved_at` is
parsed at all: a PRD dated at or after the floor requires a receipt for every
dispositioned finding, unconditionally; a PRD predating the floor is exempt
(pre-compiler decisions can never have receipts). Nothing enforces a prd_id
format, so an id whose date cannot be parsed FAILS CLOSED. `verify --cross-check`
is unchanged and still reports both classes as errors — it is a diagnostic and
stays maximally informative.

### Fixed — the persist path is one critical section (sp-0c725cde)
A defect in merged code, not only in #101. `_write_all` published the disposition
and only afterwards did `capture_from_triage` take `ledger_lock` internally. The
approval gate reads the ledger under that lock, so a gate landing in the gap saw
a dispositioned finding with no receipt and false-blocked. Reproduced with an
out-of-process observer that acquired the lock mid-persist and reported
`dispositioned=1 receipts=0`. `ledger_lock` is now re-entrant per thread (flock
keys on the open file description, so a nested acquire on a second fd deadlocks
the caller against itself — measured) and findings_writer holds it across the
findings write and the capture. Spillover still fans out after the receipt lands.

## [0.13.7] - 2026-08-04

### Fixed (Codex review, PR #101 round 7)
- The since-floor shielded real conflicts. `""` sorts before every timestamp, so
  a dispositioned finding with no `resolved_at` was skipped even when its
  receipt disagreed. The floor exists to exempt findings that CANNOT have a
  receipt; one that HAS a receipt is not in that category, so the floor no
  longer applies to it. A finding that is both undateable and unclaimed stays
  exempt, or every legacy PRD blocks forever.

## [0.13.6] - 2026-08-04

### Fixed (Codex review, PR #101 round 6) — a regression from round 5
- Re-dispositioning rejected -> accepted without a new `--rationale` falsely
  blocked approval. findings_writer keeps the previous rationale on the record
  (only `pending` clears it), while the receipt captured the FLAG, which was
  absent. The fingerprint added in 0.13.5 then correctly reported two different
  decisions. The receipt now freezes the rationale the RECORD carries, which is
  what a receipt is for.

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
