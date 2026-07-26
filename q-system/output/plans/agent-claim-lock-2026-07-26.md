# Agent claim-lock (ASK-113, slice B)

## What/why

Two agent sessions sharing one checkout overwrite each other's working tree
(`feedback_parallel_sessions_one_checkout.md`). It happened again on 2026-07-26:
commit `53f2eeb` came from a different session in this same checkout and the
collision was only noticed afterwards, by hand. Nothing in the fleet claims or
locks an issue today (verified by grep: no `claimed:` marker, no lock, no mutex).

## The constraint that shapes the design

**A shell or Python script cannot reach the Linear MCP server.** That is the whole
reason `linear-queue.py` (queue-and-drain) exists. So "set the issue In Progress
AND attach `claimed:<agent>`, as one operation" cannot be one script call.

The claim therefore has two halves:

| Half | Who performs the write | What actually blocks a collision |
|------|----------------------|--------------------------------|
| **Local lock** — one working tree, N sessions | `linear-claim.py` | `linear-claim.py` exit 3, covered by `test-linear-claim.sh` |
| **Linear claim** — status + `claimed:<agent>` label | the agent, via MCP | still `linear-claim.py` exit 3: the agent must pass what it read from Linear as `--remote-state`, and the script refuses on it |

The right-hand column is the point: **the MCP call is an action, not a gate.** No
prompt instructs an agent to behave; the script refuses and returns exit 3, and
`test-linear-claim.sh` pins that refusal. An agent that skips the script gets no
claim recorded, which `linear-claim.py status` then shows as unheld.

This is not a compromise, it is the correct split: **the Linear label cannot see
two sessions in one working tree at all** (same MCP user, same labels), so the
same-checkout case the prompt calls out is *only* coverable locally. And a remote
claim is the only thing that can stop an agent on a DIFFERENT checkout. Each half
covers what the other structurally cannot.

The script owns the refusal decision for both halves: it takes a `--remote-state`
snapshot (what the agent read from Linear) and refuses on it, so the collision
logic is one tested code path, not judgment split across a prompt.

## Approach

`q-system/.q-system/scripts/linear-claim.py`, following the conventions already
proven in `linear-sync.py` / `linear-queue.py`:

- Exit codes: `EXIT_OK=0`, `EXIT_USAGE=1`, **`EXIT_COLLISION=3`** — a refusal must
  be distinguishable from a crash, so a test can tell them apart.
- Env override for the lock path (`KIPI_LINEAR_CLAIMS`), exactly like
  `KIPI_LINEAR_LEDGER` and `KIPI_LINEAR_QUEUE`, so the suite never touches the
  live lock.
- Single-writer, append-only, `O_EXCL` acquisition — the same shape as the queue.

Commands:

- `claim <issue-id> --agent <name> [--remote-state <json>]` — refuses (exit 3) if
  the local lock is held by a different agent, OR if the remote snapshot shows the
  issue already `In Progress` / already carrying a `claimed:*` label held by
  someone else. Re-claiming as the SAME agent is idempotent, not a collision: a
  resumed session must not be locked out by its own earlier claim.
- `release <issue-id> --agent <name>` — drops the local lock. Released when the PR
  opens, not when the work closes, so a reviewer can pick it up.
- `status [<issue-id>]` — who holds what, for `kipi linear status` and for a human.

**Refusing is the whole point.** A mutex that grants under doubt is worse than no
mutex, because it is trusted.

## Files to touch

- `q-system/.q-system/scripts/linear-claim.py` (new)
- `q-system/.q-system/scripts/test/test-linear-claim.sh` (new, reproducer)
- `q-system/.q-system/capability-manifest.json` (register, or `capability-gate.py`
  correctly reports the new engine as inert)
- `kipi` (dispatch `claim` / `release`)

## Acceptance criteria (the reproducer IS the criterion)

- [ ] Claim as agent A succeeds
- [ ] Same claim as agent B is **refused with exit 3**, distinct from a crash
- [ ] Release as A, re-claim as B succeeds
- [ ] Same-checkout: two claims in one working tree, second refused
- [ ] Re-claim as the SAME agent is idempotent (exit 0), not a false collision
- [ ] Remote snapshot showing `In Progress` under another user is refused
- [ ] Remote snapshot showing `claimed:other` is refused
- [ ] A stale claim whose session died can be broken, and ONLY deliberately
- [ ] Suite never touches live Linear or the live lock (env override + fixture)
- [ ] Registered in the capability manifest; `capability-gate.py` green
- [ ] Observed RED before green

## Adversarial cases to cover (a mutex is judged by what it refuses)

Two claimants racing; a stale claim whose session died; a claim held across a
crash; a released claim re-taken mid-review; the same-checkout case the Linear
label cannot see; a corrupt lock file (must refuse, never silently grant).

## Patterns followed

- `linear-sync.py`'s exit-code vocabulary and `KIPI_LINEAR_*` env-override shape.
- `linear-queue.py`'s append-only single-writer file discipline.
- Reproducer-first, observed red (`verification-loops`).
- `no-orphan-findings` for anything real found and not fixed.

## Design note: do NOT copy the GitHub-label design

The source doc this came from puts the claim in a **GitHub label**, because a
headless agent in a GitHub Action has `gh` but no Linear MCP, and a GitHub label
round-trips to Linear via two-way Issues Sync. **That constraint does not apply
here.** Verified 2026-07-26: this repo has only the 9 default GitHub labels, no
`claimed:*`, and no Linear sync app installed; every agent here has Linear MCP.
Copying it would mean building a sync to solve a problem the fleet does not have.
Claim in Linear directly.
