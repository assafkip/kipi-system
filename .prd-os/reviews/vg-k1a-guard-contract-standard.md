Reviewer: Claude senior-staff subagent (claude-review), one round.
VERDICT: APPROVE
nit | kipi-settings-merge.py | Comment-only: docstring lines inside hook_key; return unchanged. Accurate.
nit | test-settings-merge.sh | Mutation check: hook_key collapsing exit 2 commands to one key turned the negative self-test red. Both new test files pass: apply 158/0, merge PASS.
nit | test-settings-merge.sh | SETTINGS_MERGE env hatch is an extra, harmless, falls back to repo script.
nit | test-apply-claude-changes.sh | "ratchet growth only" shown only by "OK applied"; no assertion that no exemption was used.
nit | test-apply-claude-changes.sh | Comment about the first design (harden op) is history, not verifiable from the diff.
nit | lesson | New paragraph accurate.
