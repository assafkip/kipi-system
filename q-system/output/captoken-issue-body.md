claude-guardrails blocks destructive commands well (deny rules + PreToolUse hooks, `exit 2`). What's missing is a **safe way to approve one** when you actually mean it. Today the only routes are editing settings or `--dangerously-skip-permissions` (which the guardrails also block), and a human running several sessions tends to reflex-approve prompts.

**Proposal:** a one-time, command-scoped, signed approval token.

- A human mints a token for an exact command: `claude-guardrails approve "git push --force origin main"`.
- A new `approve-gate` PreToolUse hook honors a destructive command only if a valid token for that exact command (and cwd) is present. The token is consumed on use: one approval, one execution.
- The agent **cannot forge** a token. By default the signing key is a `0600` file your own `Read **/*.key` deny rule already keeps the agent from reading. For hardware-rooted keys, `CAPABILITY_SIGNER` can point at a Secure Enclave / Touch ID signer.

**Why it fits:** it composes with what you already ship rather than replacing it. Same hook conventions (matcher `Bash`, `exit 2` to block, `jq`, fail-open on malformed JSON). Bash, no new runtime deps beyond `openssl` (already present on macOS/Linux).

**Scope:** 5 files, ~350 lines: `full/capability-token.sh` (mint/check/keygen, openssl ECDSA P-256), `full/approve-gate.sh` (the hook), a `claude-guardrails approve|keygen` CLI, a doc, and a test (12/12). Kept opt-in (not auto-wired into `full/settings.json`) so default behavior is unchanged; you could promote it to default if you like.

Does this fit the project? Any preference on naming or placement before I open the PR?
