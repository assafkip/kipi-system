# PR design: capability approval token for claude-guardrails

Date: 2026-06-16
Mission: `oss-contribution-mission-2026-06-16.md` (PR into existing project)
Target: dwarvesf/claude-guardrails (bash, MIT, active 12 days ago)

## Thesis

claude-guardrails blocks destructive commands (settings.json deny rules +
inline PreToolUse hooks, `exit 2`) with NO safe approval path. To run a blocked
command you must edit settings or use `--dangerously-skip-permissions` (which it
also blocks). The capability token adds the missing tier: a human mints a
one-time, command-scoped, signed approval; the gate honors a destructive command
only if it carries a valid signature. An agent that writes a token file cannot
forge a valid signature.

Forgery resistance composes with what they already ship: their `Read **/*.key`
deny rule keeps the agent from reading the private key, so it cannot sign.
Default signer is openssl (portable, testable); Secure Enclave / Touch ID is an
optional documented backend (CAPABILITY_SIGNER), so the parked SE helper does
not block this PR.

## Files (their conventions)

1. `full/capability-token.sh` (new) — mint/check/hash/keygen/approve, openssl
   ECDSA P-256, fail-closed. Adapted from the kipi capability-token core,
   genericized to `CLAUDE_GUARDRAILS_*` env.
2. `full/approve-gate.sh` (new) — PreToolUse Bash hook. Destructive command
   (pattern list) needs a valid token via `capability-token.sh check`; else
   `exit 2` with how-to-approve text. Mirrors `scan-commit.sh`.
3. `bin/claude-guardrails approve "<cmd>"` — human mints a token for one command.
4. `full/SETUP.md` / docs — keygen + wiring note.
5. `tests/` — round-trip + gate test in their `ci-test.sh` style.

## Acceptance (done = green)

- [ ] keygen -> approve -> check round-trip passes (valid token allows once)
- [ ] check denies: no token, expired token, tampered command, wrong key
- [ ] single-use: a token is consumed on first check (second check denies)
- [ ] gate hook exits 2 for a destructive command with no token, 0 with a valid one
- [ ] runs with openssl only, no Secure Enclave
- [ ] no `$HOME/.claude` kipi-specific coupling in shipped files

## Landing

Issue first (propose), then PR. gh runs from the founder's terminal only.
