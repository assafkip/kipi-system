# Wiring the prd-os / Linear seam — 3 steps, in order

**Written:** 2026-07-27 ~20:30Z. **Owner:** Sana (dispatch), operator (merge + verify).
**Resume rule:** read the STATUS table, find the first step not marked DONE, and
re-read that step's section. Do not re-derive the diagnosis.

## Why

The Linear loop and prd-os are complementary by design — Linear owns flow
(intake, DoR, dispatch, claims, rework rounds, PR), prd-os owns proof-of-done
(receipts, findings triage, spillover, gates). The design is explicit:
`linear-worker.sh:342` tells Sana *"DO NOT close the issue — closeout runs through
/issue-verify and /issue-closeout"*, and `pr-review-agent.sh:273` auto-captures every
MINOR into spillover because the rework loop stops at minors.

**The return path was never wired.** Nothing invokes closeout. On 2026-07-27, seven PRs
merged with zero receipts and no gate noticed. prd-os is capture-only for Linear work.

**Order is the whole point.** Arming a gate that cannot go green is how a gate becomes
noise — the same failure as a Slack ping that fires twice a day on an unchanged fleet.
Drain first, then the handoff, then the gate.

## STATUS

| # | Step | State | Evidence |
|---|------|-------|----------|
| 1 | Drain: `spillover resolve` verifies a Linear issue | **DONE** | ASK-209, PR #21, merged `531118e` |
| 2 | A Linear-flow PR cannot merge without a receipt | **RUNNING** | ASK-210, dispatched 21:28Z, converge 3 rounds |
| 3 | Arm `gates run` as a required check | **NOT STARTED** | precondition below |

### Step 1 — DONE, verified

The command that used to refuse now works, and the guard still holds:

```
BEFORE: cannot resolve sp-638006cc: issue 'ASK-204' is not closed.
AFTER:  {"id": "sp-638006cc", "status": "resolved"}

refuses an OPEN Linear issue   -> "not completed (state: In Progress)"   PASS
refuses a BOGUS identifier     -> "Entity not found: Issue"              PASS
```

Hand-clearing is still impossible. Verified against a scratch copy of `.prd-os/`
before merging, then for real on merged `main`.

### Step 2 — RUNNING as ASK-210 (dispatched 21:28Z)

The block cleared when ASK-208 capped out and PR #22 was closed, freeing
`linear-worker.sh`. ASK-210's spec forbids touching that file, with a
`git diff --name-only` acceptance check, so `sana/ask-208`'s re-filed pieces cannot
collide with it later.

**The spec (as dispatched):**

- A new gate script (suggest `q-system/.q-system/scripts/pr-receipt-gate.py`) takes a PR
  number, resolves its `ASK-n`, and looks for a receipt in `.prd-os/receipts.jsonl`
  carrying that issue id. Absent receipt = non-zero exit.
- Wire it as a PR-only step in `.github/workflows/` alongside the existing
  `Plugin version-bump guard (PR only)`.
- Something must WRITE the receipt. Prefer the existing `/issue-verify` +
  `/issue-closeout` path in kipi-dsse over inventing a second receipt writer — the
  whole point is that prd-os already owns proof-of-done. Decide where it is invoked
  from (converge after an APPROVE verdict is the natural seam) and say why in the PR.
- **Verification, must fail first:** open a PR with no receipt, confirm the gate
  refuses. Then produce the receipt, confirm it passes. Record both outputs.

### Step 3 — NOT STARTED, has a hard precondition

**Precondition: `gates run` must be able to reach exit 0 first.** As of 2026-07-27 the
ledger has **127 open items**. Arming a required check that is permanently red is worse
than no check.

Before arming, run `prd_runner.py spillover list` and report the real open count. If it
cannot reach zero, step 3 does not start — resolve or void the backlog first, or scope
the gate to items created after a cutoff and say so explicitly.

`gates run` currently appears **0 times** in `.github/workflows/`. `fleet-health-daily.py`
surfaces the open count as a Linear issue, which is a report, not a gate.

## In flight right now

- **ASK-210** — step 2, dispatched 21:28Z.

## ASK-208 — CLOSED UNMERGED, re-file one at a time

PR #22 closed at the 3-round cap. Branch `sana/ask-208` **kept**; the four fixes are
still needed and their spillover items are still open (`sp-28ced3d6`, `sp-71b63e62`,
`sp-fd76af2f`, `sp-1aae7516`).

**Do not re-dispatch it as one issue.** Findings went `5 -> 3 -> 3`: flat, and each
round's major was newly introduced by the previous round's fix. Round 3's major
(`mark_capped` rebuilding the attempts ledger from `{}` on any parse failure) would
have silently disarmed the very caps the PR added.

Root cause was scope, not capability. Same shape as PR #11 and ASK-204. Today's
correlation is the evidence:

| issue | scope | rounds |
|-------|-------|--------|
| ASK-209 | one focused change | **1** |
| ASK-204 | medium | 3 |
| ASK-208 | four fixes, one file | capped out |

**Re-file order, smallest first, one at a time (they all touch `linear-worker.sh`, so
never in parallel):**

1. `git fetch` before worktree creation (`sp-28ced3d6`) — a handful of lines, and the
   bug that cost two hours on 2026-07-27. **Its own review found that a fetch failure
   exited 0 silently — whatever re-files this must page on fetch failure, not go dark.**
2. rework gate considers mergeability (`sp-71b63e62`) — note round 3's finding that
   making APPROVE non-terminal needs a round cap, or rework is unbounded.
3. scratch guard (`sp-1aae7516`) — must run at **push**, not commit; `--no-verify`
   bypasses a commit hook and `kipi-update.sh` uses that flag routinely. Also: do not
   write `extensions.worktreeConfig` into the founder's shared `.git/config` without a
   cleanup path.
4. operator directive surviving a round (`sp-fd76af2f`) — largest and least urgent;
   the round-1 attempt shipped a reader with no producer and no CLI surface.

Read `sana/ask-208`'s diff and its three reviews (`~/.config/kipi/pr-reviews/pr-22-*.md`)
before re-filing any of these. The work is mostly right; the packaging was wrong.

## Open findings from 2026-07-27 not covered by steps 1-3

| id | what |
|----|------|
| `sp-3a0cac1c` | a crashed reviewer is never surfaced — log line only, PR becomes permanently un-dispatchable |
| `sp-2ea6e19c` | five scripts write Linear issues; only the pair that collided was fixed |
| `sp-7bdea5cb` | orphan scripts `init-bus-day.sh`, `instance-diet-fix.sh` — no caller anywhere, ship fleet-wide |
| `sp-dde4151f` | Linear reopens a completed issue when any new PR merely cites its identifier |
| `sp-24b5a7aa` | the architectural seam itself (this plan) |

## Audit coverage, so it is not re-done blind

**Checked 2026-07-27:** shell exit codes on failure paths, launchd plist wiring, orphan
scripts, multi-writer Linear paths, swallowed exceptions, hook scripts referenced in
`settings.json` (all present).

**NOT checked:** bus files for producer/consumer pairs, agent invocation, skill triggers.
