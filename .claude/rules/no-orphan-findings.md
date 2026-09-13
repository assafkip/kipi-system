# No Orphan Findings (ENFORCED)

Anything you find that is real but out of scope for the current work is CAPTURED,
never just mentioned. A mention in chat is a silent drop. The operator has ADHD
and will not revisit a backlog that lives only in a scrolled-past message.

## The rule

When you notice a real issue you are not fixing right now (adjacent bug, missing
filter, a `deferred` review finding, a "we should also..."), the next action is a
capture, not a sentence:

```bash
python3 plugins/prd-os/scripts/prd_runner.py spillover add \
  --source <prd-or-issue-id> --desc "<what it is, concretely>"
```

Capture = a ledger row in `.prd-os/spillover.jsonl` AND one Linear issue for Sana (filed via
`alert-to-linear.py`, id on the row). `gates run` stays RED until resolved. A mention is not capture.

## How items leave the ledger (only two ways)

- **Fixed:** build it through the normal reproducer-first issue flow, close that
  issue, then `spillover resolve <id> --resolution-ref <closed-issue-id>`. Resolve
  refuses unless the referenced issue is actually closed.
- **Voided:** if it turns out not to be a real item, `spillover resolve <id>
  --void "<reason>"`. The reason is recorded; the item is not deleted.

There is no third way. You cannot hand-clear the gate.

## Deterministic backstops

- A `deferred` disposition AUTO-creates an open spillover item (and its Linear
  issue) in BOTH findings systems (findings_writer + issue_findings, sp-5bcfbfe8).
- The fable-discipline lint blocks deferral language written into CODE without a
  capture (`# spillover-skip` acks an already-captured line). Only this blocks.
- `gates run` fails while any item is open (the enforcement of last resort).
- `spillover-linear-check.py` (daily launchd) retries failed Linear filings, alerts Sana once; never blocks.

## Reporting

At issue-closeout / prd-archive, report every spillover item the work touched:
the item, the issue that resolved it, the fix, and how it affected the system.
"Done" means the ledger is clean or every open item is named with its plan.

## Does NOT apply

- `rejected` findings (invalid / duplicate / won't-do): terminal with rationale,
  no spillover item. "Out of scope" means a real issue deferred, not a non-issue.
- Pure brainstorming / hypotheticals that are not a defect in real code or a real
  gap in shipped behavior.

<!-- enforcement -->
```json
[
  {
    "clause": "No Orphan Findings",
    "status": "ENFORCED",
    "exec": "plugins/prd-os/skills/fable-discipline/scripts/fable-discipline-lint.py",
    "config": "plugins/prd-os/hooks/hooks.json",
    "test": "plugins/prd-os/skills/fable-discipline/scripts/test_fable_discipline_lint.py",
    "note": "ENFORCED covers only the blocking slice: deferral language in code without a capture. Whether a finding is captured at all is a model decision no hook observes. DETECTED, not blocking: capture-time Linear filing in plugins/prd-os/scripts/prd_runner.py and the daily retry q-system/.q-system/scripts/spillover-linear-check.py, wired in automation/com.kipi.spillover-linear-check.plist, pinned by q-system/.q-system/tests/test_spillover_linear_check.py."
  }
]
```
