# Adversarial review: ask-975-bypass-check-runs-at-close

VERDICT: APPROVE

Mutation pass 2026-08-23: replaced this branch's issue_runner.py with
origin/main's copy inside an isolated temp clone of plugins/kipi-dsse +
plugins/prd-os/scripts, then ran test_bypass_check_runs_at_close.py.

Result on pre-fix code (the guard deleted):

```
AssertionError: close succeeded while its bypass_check exited 3 — a gate was
registered for a command that never ran green
{"closed": "bypass-red", ...}
```

The suite dies for exactly the property the fix restores, so the tests are not
decoration: remove the fix and they fail loudly.

Residual risk noted, not blocking: shell=True on spec-authored commands was
already the trust model for required_checks; this change executes at close
what the spec author already controlled at verify time. No new privilege.
