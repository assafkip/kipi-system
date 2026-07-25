---
id: prd-prevent-fact-fanout-2026-07-25
title: Block a leaked instance fact before the updater fans it out
status: approved
created_at: 2026-07-25T18:04:48Z
updated_at: 2026-07-25T18:11:07Z
owner: updater-owner
reviewers: []
findings_path: .prd-os/findings/prd-prevent-fact-fanout-2026-07-25-findings.jsonl
codex_reviewed_at: 2026-07-25T18:08:50Z
---

# Block a leaked instance fact before the updater fans it out

## Problem

`kipi update` copies generic skeleton content into 23 subtree instances in one
run. Nothing in that run looks for instance facts. A client name or a deal
amount left in a generic source is copied into every instance, committed there,
and only surfaces later when someone runs `kipi check`.

Measured, not assumed:

- `grep -rl semantic_separation_violations` returns `validate-separation.py`
  and two test files. Neither `kipi-update.sh` nor `capability-gate.py` calls
  it, so no separation check runs during an update.
- `sdc-update-propagation-proof` (closed 2026-07-25) proves the leak is
  detectable in the final state. Detection after a 23-instance fan-out is a
  post-mortem, not a control.
- The blast radius is the whole fleet, in a single command, with a commit in
  each instance carrying the fact into that repo's history.

## Goals

- A leaked instance fact stops the update BEFORE any instance is written to.
- The abort names the file, the line, and the fact class, so the fix is obvious.
- The gate is deterministic and adds no new false-positive burden to a run that
  is clean today.
- Every path that copies generic content into an instance runs the same gate,
  not just `kipi update`.

## What this gate can and cannot promise (finding-1)

It blocks the fan-out of facts the classifier can SEE. `semantic_leakage_findings`
only reads Markdown/YAML-style records: `label: value`, bold-field, and table
rows. A client name in prose, a heading, JSON, shell, Python, or most config
syntax produces no finding, so it passes this gate untouched.

That is a bound on the gate, not a reason to skip it: the chokepoint has to
exist before detection is worth widening, and every classifier improvement
lands behind it automatically. Widening the grammar is issue
`pff-classifier-reach` below, and until it ships this gate must not be
described as "leaks cannot fan out."

## Non-goals

- Fixing the classifier's existing false positives. `semantic_leakage_findings`
  reports 11,549 findings on this repo, of which 11,275 are
  `unclassified_populated_record` and most of the remaining 246 high-confidence
  hits are YAML frontmatter (`name:` in `.claude/agents/*.md`) read as client
  identity. Narrowing that grammar is `sdc-semantic-classifier`'s job.
- Retroactively cleaning the existing findings out of the repo.
- Scanning instance-owned content. Only generic, propagating sources matter
  here; instance state is the instance's own.

## Proposed approach

A delta gate in the preflight of every propagation entry point.

1. **Fingerprint with counts (finding-4).** A new script records each finding as
   `path + fact_class + sha256(offending line)` **and the number of occurrences**.
   Hashing the line rather than pinning the line NUMBER means reformatting does
   not churn the baseline, while changing the value does. Carrying the count
   means a baselined line cannot be duplicated, or removed and reintroduced,
   as a free replay.

2. **Baseline scoped to what is auditable (finding-5).** The gate blocks on the
   high-confidence classes (`client_identity`, `pricing`, `dated_interaction`,
   `sourced_interaction`, `source_identity`, `case_proof_gap`): 246 findings
   across 203 files today, versus 11,275 `unclassified_populated_record` hits
   that are frontmatter noise. A 246-entry baseline can be read by a human; an
   11,549-entry one cannot, and an unreadable baseline is an unaudited
   allowlist. `unclassified_populated_record` is reported as a warning, never a
   block, until the classifier narrows.

3. **Every propagation entry point, not just the updater (finding-3).**
   `kipi-update.sh` is not the only path that copies generic content into an
   instance. `kipi-new-instance.sh` seeds `q-system` and copies
   `settings-template.json`, `.claude/`, and `plugins/`; `kipi-migrate.py` adds
   `q-system` from remote main; `build-template-repo.sh` copies the working
   tree into a distributable template. Each calls the same gate before it
   copies anything.

4. **Dereferenced sources are in scope (finding-2).** `containment-targets.py`
   excludes tracked symlinks, but `kipi-update.sh` rsyncs `plugins/*/` with a
   trailing slash, which dereferences them: `plugins/memory-lifecycle` is a
   symlink to an external repo whose contents reach every instance while never
   entering the target manifest. The gate resolves what is actually copied, and
   refuses to propagate a source it cannot scan.

5. **Fail closed and version locked (finding-6).** The gate is NOT wrapped in
   the `[ -f ... ]` guard the adjacent settings preflight uses -- a missing
   script must abort, not silently skip. The baseline records the classifier's
   code hash and the target-scope schema; a mismatch aborts rather than
   trusting a baseline built by a different classifier.

6. **Baseline lifecycle (finding-7).** Re-baselining is an explicit, separate
   command, never implicit in a run. It prunes fingerprints whose findings no
   longer exist, so a stale entry cannot linger as a permanent permit, and it
   reports adds and removals separately so a classifier change cannot smuggle a
   real leak in alongside expected churn.

```
kipi update | kipi new | kipi migrate | build-template-repo
  -> preflight: settings-template-sync-check      (existing, update only)
  -> preflight: propagation-leak-gate --check     (new, all four) <-- aborts here
  -> copy / rsync / commit into instances
```

## Alternatives considered

- **Zero-tolerance gate (abort on any finding).** Rejected: the repo reports
  11,549 findings today and 246 even in the high-confidence classes, nearly all
  false positives. This gate would block every update on day one, so it would
  be switched off within a day and protect nothing.
- **Post-sync check per instance.** Rejected: by the time an instance's final
  state can be judged, the fact is already written and committed there. That is
  the detection this PRD exists to replace.
- **Fix the classifier first, then gate absolutely.** Rejected as a
  PREREQUISITE, accepted as parallel work: narrowing the grammar across 11k
  findings is unbounded, and the fan-out risk is live now. Note the corrected
  claim (finding-7): classifier changes do NOT make the baseline shrink for
  free. Removed findings leave stale entries and newly classified lines read as
  new violations, so the baseline needs the explicit prune/report lifecycle in
  step 6 above.
- **Block in a git pre-commit hook on the skeleton instead.** Rejected: it
  catches the fact entering the skeleton but not a fact that arrived by another
  path (a merge, a generated file, an older commit, a dereferenced symlink into
  an external repo). Corrected claim (finding-3): the updater is NOT a single
  chokepoint either, which is why the gate is wired into all four propagation
  entry points rather than one.

## Scenarios

- **A leaked client name in a record line.** The founder pastes a real prospect
  into `q-system/marketing/templates/outreach.md` as `- Client: Northwind` and
  runs `kipi update`. The preflight reports `outreach.md:3: client_identity`
  and exits non-zero. No instance is read or written. `git status` in all 23
  instances is unchanged.
- **A leaked client name in prose (the gate's blind spot, finding-1).** The
  same name pasted as a sentence produces no finding and propagates. This is
  the bound stated above; the scenario is listed so nobody reads the previous
  one as full coverage.
- **A clean run.** No new fingerprints. The preflight prints one line and the
  update proceeds exactly as before.
- **A new instance.** `kipi new` runs the same gate before seeding `q-system`,
  so a leak cannot enter a fresh instance through a path the updater never
  touches.
- **A symlinked plugin.** A fact lands in the external repo behind
  `plugins/memory-lifecycle`. The gate resolves the dereferenced source that
  rsync will actually copy, finds it, and aborts.
- **A deliberate new generic record.** Someone adds a legitimate `label: value`
  line that the classifier reads as a fact. The run aborts and names it. They
  either rewrite it as a placeholder or re-baseline explicitly, which produces
  a diff listing adds and removals separately.

## Resolved decisions

- **Delta, not absolute.** Decided: block only on fingerprints absent from the
  baseline. Rationale: measured false-positive volume makes an absolute gate
  undeployable, and an undeployable gate is worse than none.
- **Preflight, not per-instance.** Decided: abort the whole run before the
  instance loop. Rationale: a leak in the skeleton is identical for every
  instance; stopping once prevents all 23 writes rather than 22 of them.
- **Fingerprint on line CONTENT, not line number.** Decided:
  `path + fact_class + sha256(line)`. Rationale: reformatting a file must not
  churn the baseline, while changing the value must register as new.
- **Re-baselining is explicit.** Decided: a separate command, never implicit in
  an update. Rationale: an auto-updating baseline silently absorbs the exact
  leak the gate exists to stop.
- **Blocking scope is the high-confidence classes.** Decided: block on the six
  named fact classes; warn on `unclassified_populated_record`. Rationale: a
  246-entry baseline is auditable and an 11,549-entry one is not, and an
  unaudited allowlist is not evidence of anything (finding-5).
- **Occurrence counts are part of the fingerprint.** Decided: baseline entries
  carry a count. Rationale: without one, a baselined line is a permanent
  replay permit for duplicates and reintroductions (finding-4).
- **The gate never silently skips.** Decided: a missing gate script or a
  classifier/scope version mismatch aborts. Rationale: the adjacent settings
  preflight's `[ -f ... ]` guard would turn a deleted gate into a green run
  (finding-6).

## Risks and rollback

- **Blast radius:** the gate can stop all fleet updates. It is fail-closed by
  design, and that is the point, but a false positive blocks every instance at
  once. Mitigated by the delta design: a run that is clean today stays clean.
- **The baseline becomes a dumping ground.** Someone silences a real leak by
  re-baselining. Mitigated by keeping re-baselining an explicit command whose
  output is a reviewable diff in a committed file, never a side effect, and by
  reporting adds separately from removals.
- **A real leak is already present at baseline creation (finding-5).** The
  first baseline blesses what exists. Nothing in the delta design proves those
  246 entries are false positives, so a fact leaked before this ships stays
  eligible to propagate forever. Mitigated only partly by the auditable size;
  `pff-baseline-provenance` requires a per-entry justification for every
  high-confidence class entry rather than a bulk accept.
- **Migration cost:** one committed baseline file plus one preflight call.
- **Rollback:** remove the preflight call. The updater returns to its current
  behaviour; nothing else depends on the gate.

## Open questions

- None blocking. The baseline's long-term shrink path depends on
  `sdc-semantic-classifier` work that is out of scope here.

<!--
## Persona Review (optional, fill in before /prd-review)

Phase 0 of the prd-os planning-personas experiment (PRD prd-planning-personas-2026-05-13).
For non-trivial PRDs, answer the three Skeptic questions below before invoking /prd-review.
Brief answers are fine. The goal is to force one round of adversarial thinking before Codex.

### Skeptic

Q1: What is the strongest argument against doing this?
A1:

Q2: What is the smallest experiment that would disprove the thesis?
A2:

Q3: What is the cheapest non-build alternative?
A3:

When done with these questions, uncomment this section and move it to live just before `## Issues` below.
-->

## Issues

<!--
After review and approval, populate the fenced JSON block below. The manifest is
read by TWO consumers and every entry must satisfy both:
  - `prd_split.py` materializes one issue spec per entry (needs `id`).
  - the approval gate proves every ACCEPTED finding is covered by an entry (needs
    `finding_id` + a `bypass_check`). One entry per accepted finding.

Required keys per entry (spine-native -- both consumers):
  - id (kebab-case, unique across the repo)            -- prd_split.py
  - finding_id (the accepted finding it covers, e.g. "finding-1") -- approval gate
  - title (non-empty string)
  - allowed_files (non-empty list of glob patterns)
  - required_checks (non-empty list, e.g. ["pytest -q"]). The stop-gate checks
    three receipts (verified, reviewed, findings_triaged); they are meaningless
    unless the spec documents what must be verified, so an empty list is rejected.
  - bypass_check (a command proving no bypass remains) OR
    bypass_exempt: "<reason>"                          -- spine contract

Optional keys:
  - priority (default p1)
  - disallowed_files, required_reviews, acceptance

Authoring a manifest with `id` but no `finding_id` (the pre-spine shape) is
rejected at approve. The template-vs-runner contract test enforces this list.
-->

```json
[
  {
    "id": "pff-gate-fingerprint-counts",
    "finding_id": "finding-4",
    "title": "Fingerprint leak findings with occurrence counts",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/propagation-leak-gate.py",
      "q-system/.q-system/scripts/test/test-propagation-leak-gate.py"
    ],
    "disallowed_files": ["kipi-update.sh", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/scripts/test/test-propagation-leak-gate.py"],
    "required_reviews": ["security"],
    "acceptance": "Write the failing duplicate-and-reintroduce reproducer first. A baselined line duplicated, removed and re-added, or reused for another record must register as new.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/scripts/test/test-propagation-leak-gate.py -k 'count and replay'"
  },
  {
    "id": "pff-baseline-provenance",
    "finding_id": "finding-5",
    "title": "Require per-entry justification for a baselined high-confidence fact",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/propagation-leak-gate.py",
      "q-system/.q-system/state/propagation-leak-baseline.json",
      "q-system/.q-system/scripts/test/test-propagation-leak-baseline.py"
    ],
    "disallowed_files": ["kipi-update.sh", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/scripts/test/test-propagation-leak-baseline.py"],
    "required_reviews": ["security"],
    "acceptance": "Write the failing bulk-accept reproducer first. Blocking scope is the six high-confidence classes; every baselined entry in those classes carries a justification and a bulk accept without one is refused.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/scripts/test/test-propagation-leak-baseline.py -k 'bulk_accept and refused'"
  },
  {
    "id": "pff-baseline-lifecycle",
    "finding_id": "finding-7",
    "title": "Prune stale baseline entries and report adds separately from removals",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/propagation-leak-gate.py",
      "q-system/.q-system/scripts/test/test-propagation-leak-baseline.py"
    ],
    "disallowed_files": ["kipi-update.sh", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/scripts/test/test-propagation-leak-baseline.py"],
    "required_reviews": ["updater-owner"],
    "acceptance": "Write the failing stale-entry reproducer first. Re-baselining prunes fingerprints whose findings are gone and reports adds and removals as separate sets.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/scripts/test/test-propagation-leak-baseline.py -k 'stale and pruned'"
  },
  {
    "id": "pff-dereferenced-sources",
    "finding_id": "finding-2",
    "title": "Scan what rsync actually copies, including dereferenced symlinks",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/propagation-leak-gate.py",
      "q-system/.q-system/scripts/test/test-propagation-leak-sources.py"
    ],
    "disallowed_files": ["kipi-update.sh", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/scripts/test/test-propagation-leak-sources.py"],
    "required_reviews": ["security"],
    "acceptance": "Write the failing symlinked-plugin reproducer first. A fact behind a tracked symlink that rsync dereferences must be found, and a source the gate cannot scan must refuse to propagate.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/scripts/test/test-propagation-leak-sources.py -k 'symlink and refused'"
  },
  {
    "id": "pff-updater-preflight",
    "finding_id": "finding-6",
    "title": "Wire the gate into kipi update fail-closed and version locked",
    "priority": "p0",
    "allowed_files": [
      "kipi-update.sh",
      "q-system/.q-system/scripts/test/test-kipi-update-leak-preflight.sh"
    ],
    "disallowed_files": ["instance-registry.json", "q-system/canonical/**", ".prd-os/**"],
    "required_checks": ["bash q-system/.q-system/scripts/test/test-kipi-update-leak-preflight.sh"],
    "required_reviews": ["updater-owner", "security"],
    "acceptance": "Write the failing no-instance-written reproducer first. A new leak aborts before any instance is read or written; a missing gate script or a classifier/scope version mismatch aborts rather than skipping.",
    "bypass_check": "bash q-system/.q-system/scripts/test/test-kipi-update-leak-preflight.sh --assert-no-silent-skip"
  },
  {
    "id": "pff-all-propagation-entrypoints",
    "finding_id": "finding-3",
    "title": "Run the gate on every path that copies generic content into an instance",
    "priority": "p0",
    "allowed_files": [
      "kipi-new-instance.sh",
      "kipi-migrate.py",
      "build-template-repo.sh",
      "q-system/.q-system/scripts/test/test-propagation-entrypoints.py"
    ],
    "disallowed_files": ["instance-registry.json", "q-system/canonical/**", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/scripts/test/test-propagation-entrypoints.py"],
    "required_reviews": ["updater-owner", "security"],
    "acceptance": "Write the failing entry-point-inventory reproducer first. Enumerate every script that copies generic content into an instance and prove each one calls the gate before copying.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/scripts/test/test-propagation-entrypoints.py -k 'every_entrypoint and gated'"
  },
  {
    "id": "pff-classifier-reach",
    "finding_id": "finding-1",
    "title": "State and measure how much of a leak the classifier can see",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/tests/separation/test_semantic_client_leakage.py",
      "q-system/.q-system/tests/separation/fixtures/fact-grammar.json"
    ],
    "disallowed_files": ["kipi-update.sh", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/separation/test_semantic_client_leakage.py"],
    "required_reviews": ["security"],
    "acceptance": "Write the failing prose-leak fixture first. Pin the classifier's blind spots (prose, headings, JSON, code, config) as explicit RED fixtures so the coverage bound is measured and visible rather than assumed.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/separation/test_semantic_client_leakage.py -k 'blind_spot and measured'"
  }
]
```
