# Standard review: ask-975-bypass-check-runs-at-close

VERDICT: APPROVE

Checked 2026-08-23:

- The run step sits in `_enforce_spine_contract` BEFORE `gate_register`, so a
  refusal appends nothing (single-writer chokepoint preserved).
- rc=5 is named distinctly from rc=1; timeout (900s) refuses without
  registering.
- Output tail quoted into the refusal so a red gate names its reason.
- No new writes to gates.jsonl on the refusal path (asserted by
  test_close_refuses_when_bypass_check_fails).
