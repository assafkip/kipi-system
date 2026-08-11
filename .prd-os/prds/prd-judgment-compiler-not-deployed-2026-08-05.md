---
id: prd-judgment-compiler-not-deployed-2026-08-05
title: The Judgment Compiler is merged but not deployed
status: idea
created_at: 2026-08-05T17:48:04Z
updated_at: 2026-08-05T17:48:04Z
owner: assafkipnis
reviewers: []
findings_path: .prd-os/findings/prd-judgment-compiler-not-deployed-2026-08-05-findings.jsonl
---

# The Judgment Compiler is merged but not deployed

## Problem

Every behaviour shipped by PRs #102 and #103 is absent from both paths that
actually execute in daily use. The code is correct and verified. It is not
reachable.

**Measured 2026-08-05, adversarially, assuming nothing worked:**

**Path 1 — slash commands (the marketplace clone).** Plugins execute from
`~/.claude/plugins/marketplaces/kipi`, not from a project's `plugins/` dir. That
clone sits at `7a68af2`, prd-os **0.12.0**, **5 commits behind main** (missing
#98, #99, #100, #102, #103). Concretely:

- `judge` subcommand registered: **0**
- `judge_view`: **0**
- `prd-triage.md` mentions of the judge: **0**
- `_judgment_receipt_gate` in `prd_runner.py`: **0**

So `/prd-triage` runs the pre-judge flow, and `/prd-approve` does **not** require
receipts. The gate the whole issue exists to install is off.

**Path 2 — the `kipi` CLI.** `which kipi` resolves to the repo's own script,
which dispatches to `$KIPI_HOME/plugins/...`. The main checkout is on
`sana/bake-in-and-cleanup` at `e48d951` with **55 dirty files**, a branch that
predates #103. `kipi judgment --help` lists
`assemble|capture|verify|evaluate|reanchor|sample-check|policy-candidates|selftest`
with **no `judge`**, and `kipi judgment judge` is rejected.

## What is NOT broken

Verified end-to-end against `main` in an isolated sandbox repo (own `git init`,
so the ledger could not resolve to the live one):

- `--selftest`: PASS.
- **The receipt gate blocks.** Dispositioned a finding with
  `KIPI_JUDGMENT_CAPTURE=0`, then `advance approved` → **real exit 2**, message
  naming the finding, and the PRD **did not advance** (stayed `in-review`).
- **It does not false-block.** Re-dispositioned with capture on → receipt minted
  → the receipt gate stopped complaining and a different, pre-existing coverage
  gate fired instead.
- **The judge runs for real.** 12s wall clock, valid schema, model
  `claude-opus-5`, prediction correctly **withheld from stdout**.
- **The judge is blind.** On a synthetic finding it returned
  `needs-human`/`insufficient-context` at 0.86 rather than guessing, and its
  `missing_context` names a prior receipt as "referenced but not included".
- **A judged receipt lands.** `judged_receipts` 0 → 1 via the production path.

The defect is deployment, not correctness.

## Goals

1. Both execution paths run the merged code, proven by running them, not by
   inspecting a file.
2. A deterministic check that fails when the runtime copy drifts behind `main`,
   so this cannot recur silently.

## Non-goals

Changing any judgment-compiler behaviour. Clearing the 520-item spillover
backlog. Fixing the 66s capability-gate timing (`sp-a7b9d9ea`).

## Scope

In scope: refreshing the marketplace clone; returning the main checkout to a
clean `main`; a drift check; the junk below.

Out of scope: everything in the non-goals, and the five unrelated open PRs
(#85, #86, #88, #95, #96).

## The junk, measured

- **165 registered git worktrees**, 2 already `prunable`.
- **19 stray `.prNNrev` directories** plus `.review-scratch` and `.fable-wt` in
  the repo root, totalling **367 MB**.
- **87 copies of `pr-review-agent.sh`** on disk. One canonical
  (`q-system/.q-system/scripts/`), 86 shadows. This is not cosmetic: on
  2026-08-04 a stale copy produced a review of `/Users/assafkipnis/projects`,
  which is not a git repository, so the reviewer had no diff and its verdict was
  formed from the prompt alone. It filed that output under a `codex/` path while
  running a different engine. Captured as `sp-5169a276` and `sp-b274084f`.

## Acceptance criteria

- [ ] `kipi judgment judge --help` succeeds (currently rejected).
- [ ] The marketplace clone reports prd-os ≥ 0.16.5 and `grep -c "def judge_view"` ≥ 1.
- [ ] The clone's `prd-triage.md` contains the judge invocation.
- [ ] The clone's `prd_runner.py` contains `_judgment_receipt_gate`.
- [ ] A real `/prd-triage` in a session produces a receipt carrying BOTH a judge
      block and a human block. Proven by reading the receipt, not by the command
      exiting 0.
- [ ] A deterministic check fails when the runtime copy is behind `main`, with a
      reproducer showing it red before the fix.
- [ ] `git worktree prune` run; prunable entries gone.
- [ ] Stray `.prNNrev` / `.review-scratch` / `.fable-wt` removed, 367 MB
      reclaimed, and the review runner reduced to one reachable copy or the
      shadows made non-executable.
- [ ] Main checkout on a clean `main`.

## Risks

The main checkout has **55 uncommitted files** on a branch that is already
merged. Those changes belong to another session. They must be inspected and
either committed, stashed by tag, or explicitly discarded by the founder before
the checkout moves. Do not switch branches under them.

Removing 367 MB of scratch directories is irreversible and some may be another
session's live work. Check for running processes and recent mtimes first; the
destructive-op hook will refuse `rm -rf` without explicit approval, which is
correct and should not be bypassed.

## Why this matters

The scar this repo already documents: "text-in-a-file is NOT wired... Plugins
run from the marketplace clone, NOT a project's `plugins/` dir. Grepping that
text exists in a repo file proves nothing." Ten adversarial review rounds
hardened code that no session can currently reach. The session's own published
lesson applies directly: a check must be able to fail for the reason you care
about, and "the tests pass on main" cannot fail for "the runtime is stale."
