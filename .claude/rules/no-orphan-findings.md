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

This writes it to `.prd-os/spillover.jsonl`. The standing gate
(`prd_runner.py gates run`) then stays RED until it is resolved, so it cannot be
forgotten. "I'll mention it to the founder" is not capture. The file is capture.

## How items leave the ledger (only two ways)

- **Fixed:** build it through the normal reproducer-first issue flow, close that
  issue, then `spillover resolve <id> --resolution-ref <closed-issue-id>`. Resolve
  refuses unless the referenced issue is actually closed.
- **Voided:** if it turns out not to be a real item, `spillover resolve <id>
  --void "<reason>"`. The reason is recorded; the item is not deleted.

There is no third way. You cannot hand-clear the gate.

## Deterministic backstops

- A `deferred` triage disposition AUTO-creates an open spillover item
  (findings_writer). Deferring is not a terminal state.
- The fable-discipline lint blocks deferral language written into CODE without a
  capture (`# spillover-skip` acks an already-captured line).
- `gates run` fails while any item is open (the enforcement of last resort).

## Reporting

At issue-closeout / prd-archive, report every spillover item the work touched:
the item, the issue that resolved it, the fix, and how it affected the system.
"Done" means the ledger is clean or every open item is named with its plan.

## Does NOT apply

- `rejected` findings (invalid / duplicate / won't-do): terminal with rationale,
  no spillover item. "Out of scope" means a real issue deferred, not a non-issue.
- Pure brainstorming / hypotheticals that are not a defect in real code or a real
  gap in shipped behavior.
