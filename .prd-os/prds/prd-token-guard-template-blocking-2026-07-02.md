---
id: prd-token-guard-template-blocking-2026-07-02
title: Token Guard Template Blocking
status: archived
created_at: 2026-07-02T00:34:16Z
updated_at: 2026-07-02T00:41:44Z
owner: assafkipnis
reviewers: []
findings_path: .prd-os/findings/prd-token-guard-template-blocking-2026-07-02-findings.jsonl
codex_reviewed_at: 2026-07-02T00:35:34Z
---

# Token Guard Template Blocking

## Problem

`settings-template.json` wired token-guard on UserPromptSubmit and PreToolUse as
`test -f X && python3 X || true`. The `|| true` swallows exit code 2, the only
signal the hook contract uses to BLOCK. Observed 2026-07-01: the skeleton's own
`.claude/settings.json` (bare `python3 X`) blocked live, while every instance
built from the template had a circuit breaker that could print warnings but
never actually stop a runaway loop. All 19 fleet instances were affected.
Recorded as spillover sp-dd731488 (source huntkit-parity-sync-2026-07-01).

## Goals

- Template token-guard wiring propagates exit code 2 (blocks work in instances
  exactly as in the skeleton).
- Missing `token-guard.py` (fresh instance before first `kipi update`) stays a
  silent no-op — the original reason the `test -f` guard existed.
- A regression test extracts the REAL command strings from the template
  (json-aware, not grep-a-pattern) and proves both behaviors, so the swallow
  form cannot return unnoticed.

## Non-goals

- Changing token-guard.py's own detection logic or limits.
- Touching the skeleton's `.claude/settings.json` (already correct).
- Re-syncing the fleet's already-generated instance settings (next
  `kipi update` regenerates them from the template; no per-instance patching).
- Auditing other `|| true` hooks in the template (informational SessionStart
  hooks legitimately swallow exit codes).

## Proposed approach

Both wirings become `if [ -f X ]; then python3 X; fi`:
present script → its exit code propagates (2 blocks); missing script → exit 0.
Regression test `q-system/.q-system/scripts/test/test-token-guard-template-wiring.sh`:
parses the template's hooks JSON, collects every command containing
`token-guard.py`, asserts >=2 wirings, statically rejects `|| true`, then runs
each real command string against a tempdir fixture whose token-guard exits 2
(expect 2) and with the script removed (expect 0).

Status note: the fix is implemented and committed at skeleton `ef37dcd`
(reproducer-first: the test was shown FAILING against the old form on a copied
tree, then passing). This PRD exists to gate-verify it and close sp-dd731488
against a closed issue, per the spillover ledger contract.

## Risks and rollback

- Blast radius: one file consumed only by `kipi-new-instance.sh` and
  `kipi update`'s settings regeneration. Instances pick the change up on their
  next update; no live process is disturbed.
- Behavior change is strictly intended: instances gain blocking they were
  documented as already having (token-discipline.md assumes blocks work).
- Rollback: revert the two command strings in `settings-template.json`; the
  regression test will go red, which is the alarm working.

## Open questions

- None. The one judgment call (keep missing-script no-op vs fail loudly) is
  settled by the fresh-instance bootstrap sequence: settings arrive before
  q-system scripts, so no-op is required.

## Issues

<!--
After review and approval, populate the fenced JSON block below with one
entry per atomic issue. `prd_split.py` reads this block verbatim and writes
one issue spec per entry.

Required keys per entry:
  - id (kebab-case, unique across the repo)
  - title (non-empty string)
  - allowed_files (non-empty list of glob patterns)
  - required_checks (non-empty list, e.g. ["pytest -q"]). The runner's
    stop-gate checks that three receipts are marked (verified, reviewed,
    findings_triaged). Those receipts are meaningless unless the spec
    documents what must be verified, so an empty list is rejected.

Optional keys:
  - priority (default p1)
  - disallowed_files, required_reviews, acceptance

IDs must match the repo's issue naming convention and must not collide with
existing issue specs.
-->

```json
[
  {
    "id": "token-guard-template-blocking",
    "finding_id": "finding-1",
    "title": "settings-template.json token-guard wiring must propagate exit 2 while no-opping when the script is missing (sp-dd731488)",
    "allowed_files": [
      "settings-template.json",
      "q-system/.q-system/scripts/test/test-token-guard-template-wiring.sh"
    ],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-token-guard-template-wiring.sh"
    ],
    "bypass_check": "bash q-system/.q-system/scripts/test/test-token-guard-template-wiring.sh",
    "priority": "p2",
    "acceptance": "Both template token-guard wirings use the if-then form (no `|| true` on a blocking hook command). The regression test extracts the real command strings from the template JSON, proves exit-2 propagation with a fixture guard and exit-0 with the script absent, and was shown failing against the old `test -f X && python3 X || true` form (negative self-test)."
  }
]
```
