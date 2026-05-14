---
id: prd-prd-os-receipts-and-phase0-measure-2026-05-14
title: Complete prd-os infrastructure (receipts writer + Phase 0 measurement)
status: archived
created_at: 2026-05-14T16:06:54Z
updated_at: 2026-05-14T16:28:26Z
owner: assaf
reviewers: []
findings_path: .prd-os/findings/prd-prd-os-receipts-and-phase0-measure-2026-05-14-findings.jsonl
codex_reviewed_at: 2026-05-14T16:28:09Z
---

# Complete prd-os infrastructure (receipts writer + Phase 0 measurement)

## Problem

Two gaps surfaced during the autonomous run of `prd-planning-personas-2026-05-13`:

1. **Receipts writer is missing.** `plugins/prd-os/scripts/issue_runner.py` `cmd_close` does not write to `.prd-os/receipts.jsonl`, but `plugins/prd-os/scripts/prd_runner.py` archive READS from it via `_load_receipts_for_prd` to gate archival. I had to hand-write `.prd-os/receipts.jsonl` to unblock archive on the last PRD. Every future prd-os run will hit this unless the close-to-write path is wired.

2. **Phase 0 of the planning-personas experiment has no measurement tooling.** The PRD's kill/continue criterion (50% reduction in vague-goal-class + empty-non-goals-class findings on persona-applied PRDs vs the baseline) requires a script that classifies findings, detects which PRDs ran personas, and computes the rate per group. The classifier (`classify_findings.py`) exists but nothing wires it into a verdict.

Both gaps trace to the same source (the planning-personas PRD) and share the same target (`plugins/prd-os/scripts/`). They ship together as one PRD with two atomic issues.

## Goals

**Primary outcome (single success metric):**

After this PRD is archived, the next prd-os run (drafting an unrelated PRD through to archive) completes without any manual editing of `.prd-os/receipts.jsonl`. The archive succeeds because `cmd_close` wrote the receipts as a side effect of each issue close. Additionally, `phase0_measure.py` correctly classifies the existing `prd-planning-personas-2026-05-13` (which has a non-empty `## Persona Review` section) as `personas-applied` and emits a valid JSON verdict.

Supporting outcomes:
- `phase0_measure.py` can be invoked at any time to print a verdict (`continue` / `kill` / `insufficient-data`) against the planning-personas Phase 0 kill criterion, with a per-group breakdown.
- Every invocation of `phase0_measure.py` appends a measurement row to `q-system/memory/working/prd-personas-baseline.md` so the audit trail accumulates without separate bookkeeping.
- `phase0_measure.py` output passes a JSON schema: top-level keys `personas_applied`, `no_personas`, `verdict`, `recommendation`. Both group keys contain `prds: list[str]`, `total_findings: int`, `concerning_findings: int`, `rate: float`. `verdict` is one of the three documented strings. `recommendation` is a non-empty human-readable string. (Addresses finding-5.)

## Non-goals

- Modifying `prd_runner.py` or the archive gate logic. The reader side is correct; only the writer side is broken.
- Adding concurrency locks for `.prd-os/receipts.jsonl`. Single-writer-per-close means a simple append is safe.
- Auto-running `phase0_measure.py` from a hook (Stop, PostToolUse, `/prd-archive`). Manual invocation is sufficient for v0.
- Changing the receipt schema beyond the minimal fields. `prd_id` and `finding_id` are the only fields the reader enforces; audit fields (`closed_at`, `receipts`) are nice-to-have.
- Updating any other PRDs or issue specs to backfill the missing receipts they wrote manually. The fix is forward-looking only.
- Refactoring the issue runner's CLI surface or argument parsing. The fix is a localized addition inside `cmd_close`.

## Proposed approach

### Issue 1: fix `cmd_close` to write receipts

Files modified:
- `plugins/prd-os/scripts/issue_runner.py` (modify `cmd_close`; add `_write_receipt` helper; add `_extract_finding_id_from_spec` helper)
- `plugins/prd-os/tests/test_issue_runner.py` (add 4 tests)

Insertion point: `cmd_close` lines 325-342 in `issue_runner.py`. The receipt write goes AFTER `path.write_text(new_text)` on line 338 (spec is now `status: closed`) and BEFORE `_write_state(cfg, _empty_state())` on line 340 (state still has populated receipts).

Receipt record schema (validated against `_load_receipts_for_prd` in `prd_runner.py:509-529`):

```json
{
  "prd_id": "<from-marker-comment-in-issue-spec>",
  "finding_id": "<from-marker-comment>",
  "issue_id": "<from-state>",
  "closed_at": "<iso-utc-z>",
  "receipts": {"verified": "...", "reviewed": "...", "findings_triaged": "..."}
}
```

`prd_id` and `finding_id` are the only fields the reader enforces; everything else is audit metadata.

Finding-id recovery: parse the marker comment that `prd_split.py` injects after the issue spec frontmatter. The marker format is:

```
<!-- generated-by: prd_split.py prd=<prd_id> finding=<finding_id> at=<iso> -->
```

Import `MARKER_RE` from `prd_split.py` rather than re-defining it.

Edge cases:
- Issue spec lacks the marker (shouldn't happen on prd_split-generated issues, but be defensive). Emit a warning to stderr, skip the receipt write, still close the issue.
- `receipts_path` parent directory doesn't exist yet. `mkdir(parents=True, exist_ok=True)` before opening.
- **Idempotency (addresses finding-3):** before appending, scan `receipts_path` for an existing record with the same `(prd_id, finding_id)` pair. If found, skip the append silently. This is a read-then-append pattern, not a write-and-dedup-later pattern. The cost is one file read per close, which is fine for any realistic file size. Duplicate close attempts (retries, autonomous re-runs, manual reruns) therefore never produce duplicate receipt records. The reader already dedupes via set semantics, so existing archive behavior is unchanged.
- **Concurrency:** simple `path.open("a")` after the idempotency check. Each issue close runs in a single process; concurrent closes against the same `(prd_id, finding_id)` are blocked by the issue runner's own active-state contract (only one issue can be in-progress at a time).

### Issue 2: build `phase0_measure.py`

New files:
- `plugins/prd-os/scripts/phase0_measure.py` (the script)
- `plugins/prd-os/tests/test_phase0_measure.py` (tests)

Existing primitives reused:
- `classify_findings.py:classify_jsonl(path)` for finding classification
- `config.py:load(strict=True)` for `cfg.prds_dir` and `cfg.findings_dir`
- CLI convention from `findings_writer.py`: JSON to stdout, exit codes 0/2

Behavior:
1. Walk `cfg.prds_dir/*.md`. Strip HTML comments via `re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)` and search for a non-commented `## Persona Review` heading. If found AND at least one `### Skeptic` answer line is non-empty, classify the PRD as `personas-applied`. Otherwise `no-personas`.
2. For each PRD, find its findings file at `cfg.findings_dir/<prd-id>-findings.jsonl`. Call `classify_jsonl`. Skip if missing.
3. Aggregate per group: sum vague-goal-class + empty-non-goals-class as the "concerning" count; sum total. Compute rate = concerning / total per group.
4. **Apply the kill criterion (corrected for finding-4):** the parent PRD says the experiment is "killed" (don't build v0) when the template-only approach achieves a 50% reduction in concerning findings versus baseline. Therefore:
   - If `personas_applied.rate <= 0.5 * no_personas.rate`: verdict is **`kill`**. Template scaffold worked. Do NOT ship `/prd-personas`.
   - If `personas_applied.rate > 0.5 * no_personas.rate`: verdict is **`continue`**. Reduction not achieved. Ship `/prd-personas`.
   - If either group has fewer than 3 PRDs with findings, verdict is **`insufficient-data`**.
5. Print structured JSON to stdout. Schema (addresses finding-5): top-level keys `personas_applied`, `no_personas`, `verdict`, `recommendation`. Each group has `prds`, `total_findings`, `concerning_findings`, `rate`.
6. Side effect (addresses finding-2): append one row to `q-system/memory/working/prd-personas-baseline.md` table per invocation.
7. Exit code 0 always (measurement, not a gate).

## Risks and rollback

### Risks

- **Issue specs missing the marker comment.** Defensive warn-and-continue handles this without blocking close. Risk is low and contained.
- **Receipts file growing unbounded.** Each close appends one line. After 100 PRDs with 4 findings each, the file is 400 lines (~50 KB). Not a real concern.
- **Phase 0 detector false positive.** Founder pastes commented scaffold into PRD body without uncommenting. Detection should still classify as `no-personas` because non-empty answer detection requires text after `A1:`. Test case 3 covers this.
- **Phase 0 detector false negative.** Founder runs Skeptic session manually but doesn't paste the section into PRD spec. Classified as `no-personas` even though personas were considered. Acceptable: measurement is about durable record, not conversation.
- **Tests interact with the live `.prd-os/` directory.** Test fixtures must use `tmp_path` exclusively. The existing `test_issue_runner.py` `fake_repo` fixture pattern enforces this; new tests follow the same pattern.
- **Persona detector layout coupling (addresses finding-6).** The detector depends on the exact heading conventions (`## Persona Review`, `### Skeptic`, `A1:`/`A2:`/`A3:`) used in both PRD templates and the parent PRD. This is intentional coupling, not hidden: changing the convention requires updating templates and detector together. v0 accepts this rather than adding a frontmatter marker, which would require every PRD to opt in explicitly.

### Rollback

- Revert `plugins/prd-os/scripts/issue_runner.py` to pre-PRD `cmd_close`. New helpers are dead but harmless.
- Delete `plugins/prd-os/scripts/phase0_measure.py` and `plugins/prd-os/tests/test_phase0_measure.py`.
- Revert rows appended to `q-system/memory/working/prd-personas-baseline.md` (data appends; one git revert).
- No state machine changes. No data migration.

Rollback cost: 3 file reverts. Blast radius: zero.

## Open questions

- **Should `cmd_close` block when the marker is missing?** Resolved: no. Warn and continue. Blocking close on a malformed spec creates more friction than it prevents.
- **Should `phase0_measure.py` block (exit non-zero) on the `kill` verdict?** Resolved: no. It is a measurement tool, not a gate.
- **Should the measurement script run automatically on `/prd-archive`?** Resolved: no for v0. Manual invocation is sufficient until evidence shows the founder forgets.
- **Should the receipt schema include the issue spec path?** Deferred. The reader only requires `prd_id` and `finding_id`.

## Persona Review

This PRD intentionally skips the planning-personas Skeptic session. Per the `prd-planning-personas-2026-05-13` design notes, small mechanical infrastructure PRDs (bug fix + small new script, ~150 lines total, no scope ambiguity) should skip the persona session because ceremony cost exceeds the value. This is the system's own decision rule applied recursively.

The skip is recorded here so Codex review can challenge the decision if it disagrees.

## Issues

<!--
After review and approval, populate the fenced JSON block below with one
entry per atomic issue. Required keys per entry: id, title, finding_id, allowed_files, required_checks.
-->

```json
[
  {
    "id": "prdos-receipts-writer",
    "title": "Fix cmd_close to write to .prd-os/receipts.jsonl",
    "finding_id": "finding-1",
    "priority": "p0",
    "allowed_files": [
      "plugins/prd-os/scripts/issue_runner.py",
      "plugins/prd-os/tests/test_issue_runner.py"
    ],
    "required_checks": [
      "pytest -q plugins/prd-os/tests/test_issue_runner.py"
    ],
    "acceptance": "cmd_close appends a {prd_id, finding_id, issue_id, closed_at, receipts} record to cfg.receipts_path after status flip, before state clear. Idempotent on (prd_id, finding_id). MARKER_RE from prd_split.py imported and used to recover finding_id. New tests cover: success path, parent-dir creation, marker-missing warning, end-to-end unblock of /prd-archive.",
    "required_reviews": ["codex-review"]
  },
  {
    "id": "phase0-baseline-doc-scope",
    "title": "Update prd-personas-baseline.md format to support measurement-row appends",
    "finding_id": "finding-2",
    "priority": "p2",
    "allowed_files": [
      "q-system/memory/working/prd-personas-baseline.md"
    ],
    "required_checks": [
      "grep -q 'measurement' q-system/memory/working/prd-personas-baseline.md"
    ],
    "acceptance": "Baseline doc extended with section documenting the row format phase0_measure.py will append. Existing rows preserved. Doc notes phase0_measure.py is the only writer going forward."
  },
  {
    "id": "phase0-idempotency-rule",
    "title": "Document idempotency contract for receipt writes in issue_runner.py",
    "finding_id": "finding-3",
    "priority": "p2",
    "allowed_files": [
      "plugins/prd-os/scripts/issue_runner.py"
    ],
    "required_checks": [
      "grep -q 'idempotent' plugins/prd-os/scripts/issue_runner.py"
    ],
    "acceptance": "cmd_close docstring (or nearby comment block) documents the (prd_id, finding_id) idempotency key and explains concurrent / rerun behavior inline."
  },
  {
    "id": "phase0-measure-script",
    "title": "Build phase0_measure.py with corrected kill-criterion verdict",
    "finding_id": "finding-4",
    "priority": "p1",
    "allowed_files": [
      "plugins/prd-os/scripts/phase0_measure.py",
      "plugins/prd-os/tests/test_phase0_measure.py",
      "q-system/memory/working/prd-personas-baseline.md"
    ],
    "required_checks": [
      "test -f plugins/prd-os/scripts/phase0_measure.py",
      "pytest -q plugins/prd-os/tests/test_phase0_measure.py"
    ],
    "acceptance": "phase0_measure.py implements the corrected verdict logic: personas_applied.rate <= 0.5 * no_personas.rate => kill. Emits documented JSON schema. Appends one row to baseline.md per invocation.",
    "required_reviews": ["codex-review"]
  },
  {
    "id": "phase0-measure-acceptance-tests",
    "title": "Strengthen Issue 2 tests: JSON schema, baseline append, sample verdicts",
    "finding_id": "finding-5",
    "priority": "p2",
    "allowed_files": [
      "plugins/prd-os/tests/test_phase0_measure.py"
    ],
    "required_checks": [
      "pytest -q plugins/prd-os/tests/test_phase0_measure.py"
    ],
    "acceptance": "Tests assert: stdout is parseable JSON with documented schema; baseline.md has exactly one new row after invocation; verdict computation is correct for synthetic kill / continue / insufficient-data cases."
  },
  {
    "id": "phase0-layout-coupling-note",
    "title": "Document persona-detector PRD-layout coupling in phase0_measure.py docstring",
    "finding_id": "finding-6",
    "priority": "p3",
    "allowed_files": [
      "plugins/prd-os/scripts/phase0_measure.py"
    ],
    "required_checks": [
      "grep -q 'Persona Review' plugins/prd-os/scripts/phase0_measure.py",
      "grep -q 'Skeptic' plugins/prd-os/scripts/phase0_measure.py"
    ],
    "acceptance": "Module docstring names the layout coupling (## Persona Review, ### Skeptic, A1/A2/A3 conventions) and points to plugins/prd-os/templates/prd.md as the paired source of truth."
  }
]
```
