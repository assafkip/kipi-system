**Step 6 — Decision compliance check (SKIP if context is running low - Step 11 is more important):**
> **HARNESS:** Log as `6_decision_compliance`. If skipping due to context, log as skipped with reason "context budget".
- Read `canonical/decisions.md` → get all active RULE entries
- For each rule with a `Grep check`, run the grep across canonical files
- Flag any violations (a rule says "never say X" but file still says X)
