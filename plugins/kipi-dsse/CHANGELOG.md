# Changelog

Changes to the `kipi-dsse` plugin. Earlier versions were recorded only in commit
messages; this file starts at 0.16.0.

## [0.16.0] - 2026-11-06

### Added - closed means shipped, the close half (ASK-3830)

- **A checked "Live:" deliverable needs a live receipt.** `issue_runner.py close`
  refuses when a checked box under `## Deliverables` starts with `Live:` and the
  spec's `live_receipt:` field is empty. The field names a
  `runtime_receipt.py capture` of the running system's own record. The receipt
  is checked with the same loader #610 added for runtime-control fixes, in
  `live=True` mode: it must postdate the issue load, no other issue's close row
  may hold it, and it must read the record the checked Live line names (a path,
  a directory holding it, or a status command in backticks). A test run, a
  `--selftest` and the issue's own required check are refused. The close row
  carries it as `live_receipt`.
- **A checked Live box that says PENDING is refused**, with or without a receipt.
  Measured 2026-11-06: 15 of the 23 closed chief gp-* specs closed with exactly
  that, and none got its record afterwards.
- **`load` reads `blocked_by`.** An activation issue from prd-split loads only
  after every issue it names is `status: closed`.
- One receipt proves one item across both fields: a receipt filed as
  `runtime_receipt` on one issue cannot be the `live_receipt` of another.
- `_count_checked_deliverables` now reads `_deliverable_boxes`, the one parser
  the Live check also uses.

Not changed here (open follow-ups from #610): ASK-3844 and ASK-3845.
