---
id: prd-capability-approval-token-2026-06-16
title: Capability Approval Token
status: approved
created_at: 2026-06-16T03:08:29Z
updated_at: 2026-06-16T03:29:17Z
owner: assafkipnis
reviewers: []
findings_path: .prd-os/findings/prd-capability-approval-token-2026-06-16-findings.jsonl
codex_reviewed_at: 2026-06-16T03:15:50Z
---

# Capability Approval Token

## Problem

`destructive-op-deny.sh` blocks destructive operations by default. The only bypass is `ALLOW_DESTRUCTIVE=1`, an environment variable set in the founder's shell. This is ambient authority. Once set, it allows every destructive operation for the remainder of the session, not the single operation the founder intended to approve.

Observed shape: the founder flips the switch to approve one `git push --force`, the switch stays on, and any `rm -rf` the agent runs before the switch is flipped back is also allowed, unseen. This is a confused-deputy exposure, the same shape as the PocketOS 2026-05-17 incident where an agent deleted a production volume while a broad approval was active.

Measurable today: one approval authorizes N destructive operations for an unbounded time window. Target: the default approval path authorizes exactly one specific command, time-boxed. Session-wide authorization stops being the implicit default and becomes a separate, explicit, consciously-set `ALLOW_DESTRUCTIVE` override (unchanged), never the path you land on by approving one thing.

Prior art: this is sudo-style per-command authorization moved to the hook layer. Signed askpass flows and OS keychain prompts are the stronger, key-backed version of the same idea; they are the phase-2 direction (Secure Enclave), not phase 1.

## Goals

- Approval scoped to one exact command (raw command string plus raw working directory), not a session-wide mode
- A single grant authorizes exactly one execution, then is consumed atomically
- Grants expire on a TTL (default 5 minutes)
- The founder mints a grant out-of-band in their own shell; an agent cannot mint its own through the supported path (best-effort in phase 1)
- Every grant and every consume is appended to the existing audit log
- The change fails closed: any error, missing dependency, or ambiguity denies

## Non-goals

- Forgery resistance against an adversarial agent that writes its own token file directly. Deferred to phase 2 (macOS Secure Enclave signing, separate PRD)
- Changing the destructive-pattern deny list
- Removing the `ALLOW_DESTRUCTIVE=1` fallback. It stays as the blunt, explicit batch-approval path
- Multi-user or remote control-plane approval
- Cross-machine portability. Phase 1 targets the founder's single workstation and the established `~/.claude/` layout

## Proposed approach

Single source of logic in a repo-managed script, installed to a stable global path, called by the global hook. The hook never recomputes anything the founder has to match by hand: it prints the hash it computed, and the founder approves that exact hash.

1. `capability-token.sh` (repo-managed) exposes three subcommands:
   - `hash <command> <cwd>` prints `sha256(command + LF + cwd)`, full 64 hex chars (no truncation, removes collision risk). The command and cwd are hashed verbatim, with no normalization. Any difference on retry produces a different hash and fails closed to deny.
   - `check <command> <cwd>` computes the hash, looks for `~/.claude/approvals/<hash>.token`. Consume is atomic: it attempts `mv <hash>.token <hash>.token.consuming.$$` (atomic rename); only the process that wins the rename reads the expiry. If the expiry epoch is in the future it exits 0 (allow) and deletes the consumed file; if expired, malformed, or unreadable it exits 1 (deny). A lost rename race also exits 1. Logs the consume outcome.
   - `mint <hash>` writes `~/.claude/approvals/<hash>.token` containing a single integer expiry epoch (`now + TTL`), and prunes any already-expired token files. Logs the grant.
2. `kipi-approve <hash>` is a thin wrapper that calls `capability-token.sh mint <hash>`. An install script copies `capability-token.sh` and `kipi-approve` to `~/.claude/bin/` idempotently, `chmod 0755`, and creates `~/.claude/approvals/` as `0700`.
3. `destructive-op-deny.sh` gains one branch. The `COMMAND` and `CWD` it uses come from the hook's own stdin JSON (`tool_input.command`, `cwd`), which is the actual pending tool call, so the agent cannot make the hook evaluate a different command than the one that will run. When a destructive pattern matches, before emitting deny, the hook runs `~/.claude/bin/capability-token.sh check "$COMMAND" "$CWD"`. Exit 0 means a valid token was present and consumed, so allow. Any non-zero exit, or a missing/non-executable script, denies (fail closed). The deny message is extended to print the command hash and `kipi-approve <hash>`.
4. `ALLOW_DESTRUCTIVE=1` remains the first check, ahead of all token logic, as the blunt batch fallback.

```
agent proposes destructive command (COMMAND, CWD from hook stdin)
        |
   ALLOW_DESTRUCTIVE=1 ? --yes--> allow (blunt, explicit fallback)
        | no
   capability-token.sh check (atomic consume) exit 0 ? --yes--> allow
        | no / missing script / any error
   deny, print hash + kipi-approve <hash>
```

Audit log: grant and consume events append one JSON line each to the existing `~/.claude/audit/destructive-op-deny.log` with fields `{ts, event: "grant"|"consume", hash, expiry}`. Append is best-effort and must never block or alter the security decision; a logging failure still denies or allows per the token check.

## Risks and rollback

- The agent has filesystem write access and could `touch ~/.claude/approvals/<hash>.token` to self-approve, bypassing `mint` entirely. Phase 1 does NOT close this against an adversarial agent. It closes the window against a confused or wrong agent, which is the threat the PocketOS incident represents. Forgery resistance (a token signed by a non-extractable key) is phase 2. (Tracked: finding-3, deferred.)
- Command or cwd differing by even one byte on retry fails closed to deny, never to allow. This can cause a false deny (annoying, re-approve), never a false approval. Logging the computed hash on both deny and grant makes mismatches debuggable.
- Stale tokens: deleted on consume, pruned on mint, and expired-on-read. Rollback also clears them.
- The hook depends on `~/.claude/bin/capability-token.sh`. A missing or failing script denies (fail closed), so a broken install never weakens enforcement.
- Rollback is additive and complete: remove the one branch from the hook, delete `~/.claude/bin/capability-token.sh` and `~/.claude/bin/kipi-approve`, and `rm -rf ~/.claude/approvals/`. `ALLOW_DESTRUCTIVE` behavior is untouched. Blast radius is one hook file plus the new scripts.

## Open questions

- Whether Claude Code sets an environment marker that reliably distinguishes agent-spawned bash from the founder's interactive shell. This bounds how strongly phase 1's `mint` can refuse agent invocation. Verified during the build; if no reliable marker exists, the residual gap is exactly finding-3 (deferred to phase 2).

## Issues

<!-- Populated post-review. Two atomic issues, no allowed_files overlap. -->

```json
[
  {
    "id": "capability-token-lib",
    "finding_id": "finding-4",
    "title": "capability-token.sh: hash, atomic check-and-consume, mint, audit logging",
    "allowed_files": [
      "plugins/kipi-core/scripts/capability-token.sh",
      "plugins/kipi-core/scripts/test/test-capability-token.sh"
    ],
    "required_checks": ["bash plugins/kipi-core/scripts/test/test-capability-token.sh"],
    "bypass_check": "bash plugins/kipi-core/scripts/test/test-capability-token.sh",
    "priority": "p1",
    "acceptance": "check denies with no token; mint then check allows exactly once; second check denied (consumed); expired token denied; malformed/unreadable expiry denied; full 64-hex hash is deterministic for identical command+cwd and differs for any change; concurrent double-consume is impossible (atomic rename); grant and consume each append one JSON line to the audit log."
  },
  {
    "id": "capability-token-wiring",
    "finding_id": "finding-14",
    "title": "kipi-approve wrapper, idempotent install, and hook integration verified against a copy",
    "allowed_files": [
      "plugins/kipi-core/scripts/kipi-approve",
      "plugins/kipi-core/scripts/install-capability-token.sh",
      "plugins/kipi-core/scripts/test/test-capability-token-wiring.sh"
    ],
    "required_checks": ["bash plugins/kipi-core/scripts/test/test-capability-token-wiring.sh"],
    "bypass_check": "bash plugins/kipi-core/scripts/test/test-capability-token-wiring.sh",
    "priority": "p1",
    "acceptance": "install is idempotent and sets 0755 on scripts and 0700 on the approvals dir; kipi-approve <hash> mints a valid token; the wiring test copies the real destructive-op-deny.sh into a temp HOME, applies the integration, and proves end-to-end: a destructive command is denied with no token, denied when the script is absent (fail closed), and allowed exactly once after kipi-approve, then denied again."
  }
]
```
