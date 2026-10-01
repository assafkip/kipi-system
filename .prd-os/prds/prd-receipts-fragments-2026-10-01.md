---
id: prd-receipts-fragments-2026-10-01
title: Receipts Fragments
status: idea
created_at: 2026-10-01T20:33:05Z
updated_at: 2026-10-01T20:33:05Z
owner: sana
reviewers: []
findings_path: .prd-os/findings/prd-receipts-fragments-2026-10-01-findings.jsonl
---

# Receipts Fragments

## Problem

`.prd-os/receipts.jsonl` is one append-only, tracked file with `merge=union`
(`.gitattributes:15`). Every PR that closes an issue appends a line to it
(`issue_runner._append_receipt`, and converge's receipt commit on the PR branch).
GitHub does not run merge drivers when it computes mergeability, so the moment any
one of those PRs lands, every other open PR that appended a receipt turns
CONFLICTING on GitHub, while `git merge` locally reports it clean.

Measured 2026-10-01 against origin/main with GitHub semantics
(`git --attr-source=<empty tree> merge-tree`): 20 open kipi-system PRs held
`kipi/reviewer-approved=success`, all 20 were CONFLICTING, and 19 of the 20
conflicted on `.prd-os/receipts.jsonl` (8 also on a `plugin.json` version bump; 4
on real code). LGTM's run that day merged 0. Draining them by hand does not hold:
each merge re-conflicts every other receipt-carrying PR.

This is a measured, repeated failure, not a hypothesis. `capability_manifest.py`'s
header records the same measurement on 37 PRs (#212, #209, #208, #154, #80 clean
under `union`, CONFLICTING on GitHub) and the fix it shipped: one file per entry.

## Goals

- Two branches that each add a receipt merge cleanly under GitHub's semantics, in
  either order.
- Every consumer of the receipt trail sees exactly the receipts it sees today,
  plus new ones, with no reader learning the storage layout.
- One writer path. No new receipt lands in the monolith once fragments exist.
- Every converge receipt-transaction path keeps its current behavior and its
  current exit codes.
- The approval carry still refuses any path that is not a receipt.

## Non-goals

- Migrating or rewriting the history in `receipts.jsonl`. It stays, read-only.
- The `plugin.json` version-bump conflicts (the PR-only version-bump guard in
  `validate.yml`). A second, separate source of conflicts; its own change.
- Draining the 20 currently open PRs. That runs separately, in series.
- Changing what a receipt contains (`receipts-ledger-check.py`'s closed key
  allowlist stays the content rule, now applied per fragment).

## Proposed approach

Fragments, one receipt per file:

```
.prd-os/receipts.jsonl            legacy history, read-only from the switch-over
.prd-os/receipts.d/<ts>-<issue>-<rand>.jsonl   one line, one receipt
```

- `<ts>` is UTC `YYYYmmddTHHMMSSZ`, `<issue>` is the closed issue id, `<rand>` is 8
  hex chars, so two writers never pick the same name and a directory listing sorts
  by time.
- READ: one helper per language returns monolith lines then fragment lines
  (sorted by filename). Python: one function, imported by every Python reader in
  the plugin it lives in (plugins cannot import q-system scripts, so prd-os and
  kipi-dsse each get the helper; a test pins the two copies byte-identical, the
  way `export-fable-mirror.sh --check` pins mirrors). Shell (converge, the carry):
  the same union, built from `git ls-tree` / `git show` so it also works against
  `FETCH_HEAD`.
- WRITE: `issue_runner._append_receipt` writes a new fragment with an exclusive
  create (`open(..., "x")`), never appends to the monolith. converge's
  `receipt_append` writes and commits the fragment path.
- SINGLE WRITER, refuse rather than pick: if anything appends a NEW line to the
  monolith after the switch-over commit, `receipts-ledger-check.py` refuses
  (exit non-zero, naming the line), the same posture `capability_manifest.py`
  takes when both layouts exist.
- PATH RULES: converge's `receipt_only_ahead`, `receipt-carry-approval.sh`'s
  condition 2, lefthook's one-`.jsonl` exception and `.gitignore`'s un-ignore
  accept exactly `.prd-os/receipts.d/*.jsonl` (plus the monolith for the history
  already on branches), and nothing else.
- Dedup keeps its meaning: "this issue at this sha already has a receipt" is
  answered over monolith + fragments, so converge's exit 3 is unchanged.

Sites, each verified on origin/main `d0456aac` (2026-10-01):

| Site | Role |
|---|---|
| `plugins/kipi-dsse/scripts/issue_runner.py` `_append_receipt` (l.401), `DEFAULT_RECEIPTS_PATH` (l.75) | the Python writer |
| `plugins/prd-os/scripts/config.py` `receipts_path` (l.41, 169, 220) | config key; stays, names the monolith |
| `plugins/prd-os/scripts/prd_runner.py` `_load_receipt_issue_ids` (l.811), `_load_receipts_for_prd` (l.829) | readers (archive coverage) |
| `plugins/prd-os/scripts/judgment_compiler.py` l.1369 | reader (receipt lookup by issue) |
| `q-system/.q-system/scripts/accept-rate.py` l.103, 295 | reader |
| `q-system/.q-system/scripts/test/test-updater-issue-sequence.py` `read_receipts` (l.94) | reader; treats a non-JSON line as ledger damage |
| `q-system/.q-system/scripts/receipts-ledger-check.py` `LEDGER` (l.45) | content gate; becomes per-fragment, plus the single-writer refusal |
| `q-system/.q-system/scripts/converge.sh` `receipt_append` (l.276), `receipt_only_ahead` (l.381), `receipt_commit` (l.430), FETCH_HEAD confirm (l.688), `receipt_transaction` (l.778) | the shell writer, its dedup, recovery, rollback and origin confirm |
| `q-system/.q-system/scripts/receipt-carry-approval.sh` `RECEIPT_LEDGER` (l.70) | approval carry path rule |
| `lefthook.yml` l.64-75 | the one-`.jsonl` blocked-paths exception |
| `.gitignore` l.50 | `!.prd-os/receipts.jsonl` un-ignore |
| `.gitattributes` l.15 | `merge=union`; kept for the monolith, unneeded for fragments |
| `q-system/.q-system/scripts/test/fixtures/silent-success/GREEN-checked-swallow.converge.sh` | a converge copy used as a fixture; must not drift from the real one's path rules |

## Alternatives considered

- **Keep `merge=union`, do nothing.** Rejected: GitHub ignores merge drivers.
  Measured twice (capability_manifest's 37 PRs; 19 of 20 here).
- **Untrack the ledger.** Rejected: converge's receipt commit and the archive
  coverage read it from the tree, and a fresh clone (CI) would see no receipts.
- **Union-resolve before merging, in LGTM.** Rejected: LGTM's cloud path reaches
  GitHub only through MCP and calls the update-branch API, which merges without
  drivers. It has no git to run a union merge in. A Mac-side resolver would also
  create a new head whose approval cannot be carried (the merge brings main's
  diff, which no reviewer read).
- **Move receipts into commit statuses or check runs.** Rejected: rewrites what
  every reader trusts and what the archive gate counts, for the same outcome.
- **Migrate the monolith into fragments in the same change.** Rejected: rewrites
  history on 19 open branches at once and makes rollback a data operation.
  Leaving it read-only costs one extra read per consumer.

## Scenarios

- **Two PRs close two issues.** Session A closes ASK-1 on branch a, session B
  closes ASK-2 on branch b. Each writes one new fragment file. A merges. b is
  still MERGEABLE on GitHub (two different added files), merges next.
- **converge receipts a reviewed head.** converge appends the fragment for ISSUE
  at sha, commits only that path, pushes, then confirms on origin by reading
  monolith + fragments at FETCH_HEAD. `receipt_only_ahead` sees exactly one added
  fragment path and allows it.
- **converge re-runs after dying mid-transaction.** The fragment exists but is
  uncommitted. Dedup over monolith + fragments finds it, the recovery branch sees
  the uncommitted path and finishes the commit, as it does today for the line.
- **The receipt commit is refused.** converge rolls back by removing the one
  fragment it created, not by restoring a whole-file backup.
- **Approval carry.** The head differs from the reviewed sha only by one added
  fragment: the carry copies the approval. Any other path: refused, as today.
- **Someone appends to the monolith after the switch-over.** The ledger check
  refuses the commit and names the new line.
- **Archive coverage.** `_load_receipts_for_prd` resolves close/reopen by event
  timestamp over monolith + fragments, so ordering stays independent of storage.

## Resolved decisions

- **Fragment layout.** Decided: `.prd-os/receipts.d/<ts>-<issue>-<rand>.jsonl`,
  one line. Rationale: the repo's own proven shape (capability_manifest); a
  `.jsonl` suffix keeps lefthook's and the ledger check's content rule applicable.
- **History.** Decided: the monolith stays read-only, unmigrated. Rationale:
  no rewrite of open branches, trivial rollback.
- **Readers.** Decided: one helper per language, two byte-identical Python copies
  pinned by a test. Rationale: plugins cannot import q-system scripts, and one
  reader per site is how a site gets missed.

## Risks and rollback

- **Blast radius.** This is the merge-gate data path, and `plugins/` and
  `q-system/` sync to every instance through `kipi update`. A wrong path rule in
  converge or the carry either blocks every receipt (no merges) or lets a
  non-receipt path through the carry (unreviewed code merges). The second is the
  worse failure; the carry's refusal is the first test written.
- **The switch-over conflicts once.** Open PRs that already appended to the
  monolith will conflict once more against the switch-over commit if it touches
  the monolith. Mitigation: the switch-over does not edit the monolith at all.
- **Rollback.** Revert the PR. Fragments written in between remain on disk and
  are read by nothing; a follow-up can fold them back into the monolith with a
  plain append, because they are already JSONL lines.

## Open questions

- **Where does the PR receipt gate live now?** converge.sh l.379 and
  receipt-carry-approval.sh l.21 cite "PR #23's own LEDGER_PREFIX allowance" and
  prd_split.py l.632 cites `pr-receipt-gate.py`. On origin/main `d0456aac` no
  tracked file defines `LEDGER_PREFIX` or `pr-receipt-gate.py`, no workflow step
  in validate/verify/reviewer-floor mentions a receipt, and the only copies found
  are review scratch under `.pr42rev*/` in snapshot commit 95332027 (2026-08-03).
  The issue that touches the path rules must find it first (another repo, or
  removed). If it no longer exists, converge's comments are the thing to fix.

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

Write bypass_check as an INVARIANT, not a token count. Counting occurrences of
an identifier looks deterministic and is not: prose in a comment inflates it, a
refactor that renames or inlines deflates it, and neither fact says anything
about whether a bypass remains. Prefer "exactly one scan exists", "the byte
compare lives in one place", "the guard is still present" over
`grep -c <name> == N`. If a count really is the invariant, exclude comment lines
(`grep -v '^[[:space:]]*#' | grep -c`) and use `grep -F` for patterns holding
regex metacharacters such as `$`.

Scar 2026-07-26 (prd-updater-consolidation): three of five bypass_checks were
grep-count proxies and each needed a mid-issue amendment. One did real damage --
it demanded three calls to a function, so a redundant dead call was written
purely to satisfy the number, and adversarial review caught it. A check that
shapes the code to fit the check is worse than no check.

Optional keys:
  - priority (default p1)
  - disallowed_files, required_reviews, acceptance

Authoring a manifest with `id` but no `finding_id` (the pre-spine shape) is
rejected at approve. The template-vs-runner contract test enforces this list.
-->

```json
[]
```
