# Design: who holds merge authority when the founder is not in the loop

**Problem 6 of `autonomous-board-prompt-2026-07-27.md`.** Design-first item.
Written 2026-07-27 22:10Z by Sana. Nothing built yet; this is the thing to argue
with before code exists.

## The hole, stated exactly

`converge.sh:159` — the success path:

```
say "DONE exit-1: PR #$PR verdict '$VERDICT' after $ROUND round(s). Waiting on founder merge only."
```

`linear-worker.sh:14,342` — the refusals:

```
1. It will not MERGE. It opens a PR and stops. Merging is the founder's.
2. It will not CLOSE an issue. Closing runs through /issue-verify and /issue-closeout.
```

Both are correct. The thing that writes code must not certify it. But
`/issue-verify` and `/issue-closeout` are slash commands, and **nothing invokes
them** — grep says zero callers outside their own docs. The founder does not
review code. So the loop's terminal state is owned by nobody, and on 2026-07-27
seven PRs merged with zero receipts because a human did it by hand.

Deleting the separation would "fix" this. That is the wrong fix. The right fix
is a third role.

## The design: three roles, three processes, no shared capability

| Role | Process | Writes code | Judges code | Merges |
|---|---|---|---|---|
| Author | `claude -p` in the worktree | yes | no | no |
| Reviewer | `pr-review-agent.sh`, fresh session | no | yes | no |
| **Integrator** | **`pr-integrate.sh` (new, deterministic)** | **no** | **no** | **yes** |

The integrator is **not an LLM**. That is the whole design. If merge authority
is a judgment call, the unowned step has only moved to a new owner who can be
argued into anything. A script that merges only when N objective conditions hold
is auditable, testable, and cannot be persuaded.

Separation is enforced by capability, not by instruction: the integrator never
enters a worktree and its every input is a file some other process wrote. It has
no ability to author, so "do not merge your own work" is true by construction
rather than by a line in a prompt.

## The six preconditions, each machine-checkable

All must hold. Any one false = refuse, and the refusal is routed as work.

1. **Verdict is APPROVE or APPROVE WITH NITS**, read from
   `pr-<n>.verdict.json` via `verdict_from_record` — the existing shared
   extractor, written by a different process than the author.
2. **The verdict is bound to the exact sha being merged.** See below; this does
   not exist today and is the load-bearing gap.
3. **Every required check is SUCCESS on that same sha.** `validate` today, plus
   the receipt gate once PR #23 lands. Never `--admin`. Never `--auto` without
   the check set resolved.
4. **`mergeStateStatus == CLEAN`** — not BEHIND, not DIRTY, not BLOCKED.
5. **A closeout receipt exists for the issue** in `.prd-os/receipts.jsonl`.
6. **Zero open BLOCKER or MAJOR findings** for that PR.

### Precondition 2 is the one that does not exist, and it is the real hole

`pr-review-agent.sh:256` writes:

```json
{"pr": 23, "issue": "ASK-210", "verdict": "REQUEST CHANGES", "stated": ..., "derived": ..., "round": 1, "review": ..., "ts": ...}
```

**No head sha.** The verdict record says *this PR* was approved, never *this
code* was approved. Any push after approval inherits the approval silently.

That is the "author merges its own work" hole wearing a different coat: an
author that can push after the verdict and before the merge has, in effect,
merged unreviewed code of its own writing. The adversarial reviewer, the
severity floor, and the round cap all become decorative on that path.

`converge.sh` already reads `head_sha "$PR"` at line 152 for its no-progress
check and throws it away. The fix is small and must land **before** any
integrator exists: record the sha in the verdict record, and have the integrator
refuse when `verdict.head_sha != pr.headRefOid`.

Building the integrator first would ship an auto-merger with a bypass in it.

## Where the receipt comes from — the second half of the hole

Receipts key on a prd-os `issue_id` (`.prd-os/issues/<slug>.md`). Linear-flow
work creates no such spec, so `.prd-os/issues/` has no entry for any `ASK-*`
worked on 2026-07-27. The receipt machinery is not broken; it was never handed
anything to receipt.

Two ways to close it:

- **(i) Generate a prd-os issue spec from the DoR at dispatch.** The DoR already
  carries the fields the spec needs:

  | DoR field | prd-os spec field |
  |---|---|
  | Files | `allowed_files` |
  | Not doing | `disallowed_files` |
  | Check | `required_checks` |
  | Outcome | `## Acceptance` |

- (ii) Invent a second receipt kind keyed on the Linear identifier.

**Pick (i).** It reuses the existing writer (`issue_runner.py mark` / `close`)
instead of adding a second one, and it makes `issue_runner.py scope <path>` —
which already exits 2 on an out-of-scope path — apply to Linear work for free.

That is also the answer to problem 4's open question ("is a run touching a file
outside its declared set a hard failure, a warning, or a re-declaration?").
**Hard failure, enforced by a mechanism that already exists and is already
tested.** One spec generator closes half of problem 4 and all of problem 6's
receipt half. Option (ii) buys neither.

## What a refusal does

A refusal that only logs is problem 3 again. Each precondition maps to an action:

| Fails | Action |
|---|---|
| 1 verdict not approving | nothing; the rework loop already owns this |
| 2 sha drift | re-review at the new sha. Never merge, never auto-approve |
| 3 check red | dispatch the failure as rework on the same issue |
| 4 not CLEAN | the file-disjoint refusal of problem 4; needs a rebase dispatch |
| 5 no receipt | run closeout; if closeout refuses, that reason is the work |
| 6 open blocker/major | rework |

Every refusal is a Linear progress note plus one Slack line. Silence is never a
refusal outcome — that is the same silent-success class as the fetch fix exiting
0 (see below).

## Scope of authority: start narrow, widen on evidence

`main` of kipi-system fans out to the whole fleet through `kipi update`, so
unattended merge authority here has fleet blast radius. The integrator is
therefore scoped, not general:

- Only `sana/ask-*` branches. Never a founder branch, never `main` directly.
- Only PRs whose declared files sit inside a configured path allowlist, starting
  with `q-system/.q-system/scripts/**` and `.github/workflows/**` — the loop's
  own machinery, where the loop is its own blast radius.
- Everything else converges to APPROVE and waits, exactly as today.

This is the bounded pilot the build brief asks for, expressed as configuration
rather than as a promise to be careful. Widening the allowlist is a one-line
change with a measured accept-rate behind it.

## Build order

```
6a. head sha in the verdict record + integrator refuses on drift   small, blocking
6b. DoR -> prd-os issue spec at dispatch                           medium
6c. pr-integrate.sh, the six preconditions, refuse-by-default      medium
6d. wire it: converge exit-1 calls it; a launchd sweep catches
    PRs that converged in an earlier session                       small
```

6a ships alone and first. It is a real defect on its own merits — it does not
need the integrator to be worth fixing, and the integrator is unsafe without it.

Depends on ASK-210 (PR #23, mid-rework) landing precondition 5's gate.

## The one thing that is genuinely the founder's

Not the mechanism. The risk appetite: an unattended process merging to a repo
that fans out fleet-wide.

The narrow allowlist above is my answer, and it does not need a decision to
start — the loop's own scripts are the safest possible first blast radius, and
the accept-rate from the pilot is better evidence than either of us guessing
now. Flagging it as a known fork, not as a blocker.

## Cross-cutting: the silent-success gate

Three separate silent-success defects appeared on 2026-07-27, each introduced by
a fix for something unrelated (fetch failure exiting 0; the `errors` bucket
never read; `--reset-rounds` writing a phantom ledger key). No gate in this repo
catches "a failure path that exits 0 and tells nobody."

Precondition-refusal routing above is this design's local answer. The repo-wide
check is a separate item and is probably worth more than any single problem on
the list.
