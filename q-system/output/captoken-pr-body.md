### Problem
claude-guardrails blocks destructive commands but offers no safe way to approve
one. The only routes are editing settings or `--dangerously-skip-permissions`
(also blocked), and reflexive prompt-approval is unsafe.

### Change (5 files, bash, your conventions)
- `full/capability-token.sh`: mint/check/keygen/approve, openssl ECDSA P-256, fail-closed.
- `full/approve-gate.sh`: PreToolUse Bash hook. A destructive command needs a valid
  one-time token, else `exit 2` with how-to-approve text. Mirrors `scan-commit.sh`.
- `bin/claude-guardrails approve "<cmd>"` and `keygen`.
- `full/CAPABILITY-APPROVAL.md`: docs + settings wiring snippet.
- `tests/test-capability-approval.sh`: 12 cases.

### Properties
Forgery-resistant (agent lacks the signing key; default key protected by your
`Read **/*.key` deny rule; optional Secure Enclave backend via `CAPABILITY_SIGNER`),
command-scoped, single-use, time-boxed, fails closed.

### Evidence
`bash tests/test-capability-approval.sh` gives 12 passed, 0 failed, on top of main
at b3c3e15. openssl only, no Secure Enclave needed.

### Notes
Kept opt-in (not auto-wired into `full/settings.json`) so default behavior is
unchanged. Happy to wire it into the `full` variant by default if you prefer.

Closes #14.
