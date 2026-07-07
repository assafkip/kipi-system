# Ready-to-send: capability approval token for claude-guardrails

STATUS (2026-06-16):
- Built + verified. Committed test 12/12. Branch `chore/capability-approval` in
  /tmp/captoken-targets/claude-guardrails.
- Durable patch (survives /tmp wipe): `q-system/output/captoken-claude-guardrails.patch`
- NOT yet filed. Issue first, then PR. `gh` runs in the founder's terminal only.

Target: dwarvesf/claude-guardrails. Changeset: 5 files, +351 lines.

---

## STEP 1 — Issue (single-line command, run in your terminal)

```
gh issue create --repo dwarvesf/claude-guardrails --title "Add a safe approval path for blocked destructive commands (forgery-resistant token)" --body-file /Users/assafkipnis/projects/kipi-system/q-system/output/captoken-issue-body.md
```

Paste the issue URL it prints back into the session.

---

## STEP 2 — PR (after a maintainer thumbs-up)

**Title:** Add capability approval tokens: a safe, forgery-resistant approval path for destructive commands

**Body:**

### Problem
claude-guardrails blocks destructive commands but offers no safe way to approve
one. The only routes are editing settings or `--dangerously-skip-permissions`
(also blocked), and reflexive prompt-approval is unsafe.

### Change (5 files, bash, your conventions)
- `full/capability-token.sh` — mint/check/keygen/approve, openssl ECDSA P-256, fail-closed.
- `full/approve-gate.sh` — PreToolUse Bash hook: destructive command needs a valid
  one-time token, else `exit 2` with how-to-approve text. Mirrors `scan-commit.sh`.
- `bin/claude-guardrails approve "<cmd>"` and `keygen`.
- `full/CAPABILITY-APPROVAL.md` — docs + settings wiring snippet.
- `tests/test-capability-approval.sh` — 12 cases.

### Properties
Forgery-resistant (agent lacks the signing key; default key protected by your
`Read **/*.key` deny rule; optional Secure Enclave backend via `CAPABILITY_SIGNER`),
command-scoped, single-use, time-boxed, fails closed.

### Evidence
`bash tests/test-capability-approval.sh` -> 12 passed, 0 failed. openssl only,
no Secure Enclave needed.

### Notes
Kept opt-in (not auto-wired into `full/settings.json`) so default behavior is
unchanged. Happy to wire it into the `full` variant by default if you prefer.

---

## STEP 3 — PR commands (when the maintainer says go)

```
gh repo fork dwarvesf/claude-guardrails --clone=false
cd /tmp/captoken-targets/claude-guardrails && git remote add fork "https://github.com/$(gh api user -q .login)/claude-guardrails.git" && git push -u fork chore/capability-approval
gh pr create --repo dwarvesf/claude-guardrails --head "$(gh api user -q .login):chore/capability-approval" --title "Add capability approval tokens: a safe, forgery-resistant approval path for destructive commands" --body-file /Users/assafkipnis/projects/kipi-system/q-system/output/captoken-pr-body.md
```
(generate `captoken-pr-body.md` from STEP 2 when ready; if /tmp was wiped, re-clone and `git apply q-system/output/captoken-claude-guardrails.patch` first.)
