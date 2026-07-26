# Continuation prompt: agent claim-lock + close-discipline, via prd-os (ASK-113)

Written 2026-07-26 at the end of the Linear-rollout session. Paste the whole thing
into a fresh session.

---

You are continuing autonomous work in `/Users/assafkipnis/projects/kipi-system`.
Tracking epic: **ASK-113**. Run this through **prd-os**, with a Claude senior staff
engineer subagent as the reviewer instead of Codex.

## Precondition — check first, STOP if it fails

Confirm the Linear MCP tools respond (`mcp__linear__list_teams`; they may be
deferred, load via ToolSearch). If Linear is unreachable, STOP and say so. Do not
build a local substitute for it.

---

## What to build (two things, one PRD)

### Deliverable A — close-discipline sentence (small, do it first)

Fold one rule into `q-system/output/plans/linear-sdlc-standard-2026-07-26.md` §3
(States) and §5 (Definition of Done):

> Close an issue only when the slice is actually complete. Do NOT close at session
> end "for hygiene" while anything is still in progress. Never end a session with
> an issue left `In Progress` under your name and no live branch: either release it
> or record the blocker on the issue.

That file is a plan doc, not always-on context, so it costs nothing against the
instruction budget. This is a ~10 minute change and needs no PRD ceremony of its
own; fold it in as the PRD's first slice.

### Deliverable B — the agent claim-lock (the real work)

**Problem, with a real scar.** Two agent sessions sharing one checkout overwrite
each other's working tree (`feedback_parallel_sessions_one_checkout.md`). It
happened again during the 2026-07-26 session: commit `53f2eeb` came from a
different session in this same checkout, and the collision was only noticed
afterwards by hand.

**Nothing in the fleet claims or locks an issue today.** Verified by grep: no
`claimed:` marker, no lock, no mutex, anywhere.

**What to build:**

- `kipi linear claim <ASK-nnn>` sets the issue to `In Progress` AND attaches a
  `claimed:<agent>` label, as one operation, BEFORE any branch or worktree is
  created.
- It **refuses** an issue that is already `In Progress` or already carries a
  `claimed:*` label held by someone else. Refusing is the whole point.
- `kipi linear release <ASK-nnn>` drops the claim label. The claim is released
  when the PR opens, not when the work closes, so a reviewer can pick it up.
- A same-checkout guard: the Linear label cannot see two sessions in one working
  tree. Cover that case too (a lock file at the repo root next to
  `.linear-queue.jsonl` is the obvious shape, and matches the queue's
  append-only, single-writer pattern).

**Design note, do not skip.** The friend's doc this came from puts the claim in a
**GitHub label**, because a headless agent in a GitHub Action has `gh` but no
Linear MCP, and a GitHub label round-trips to Linear via two-way Issues Sync.
**That constraint does not apply here and that design should not be copied.**
Verified 2026-07-26: this repo has only the 9 default GitHub labels, no
`claimed:*`, and no Linear sync app installed. Every agent here has Linear MCP.
Building the GitHub round-trip would mean building a sync to solve a problem the
fleet does not have. Claim in Linear directly.

**Reproducer first, and it is the acceptance criterion.** A mutex with no test is
worse than no mutex, because it is trusted. The test must:

1. Claim an issue as agent A. Assert success.
2. Attempt the same claim as agent B. **Assert it is refused**, with a non-zero
   exit distinct from a crash (follow `linear-sync.py`'s `EXIT_COLLISION = 3`
   convention so a test can tell refusal from failure).
3. Release as A, re-claim as B. Assert success.
4. Same-checkout case: two claims in one working tree, second refused.
5. Isolation: the suite must never touch live Linear or the live lock. Use an env
   override for the lock path exactly like `KIPI_LINEAR_LEDGER` and
   `KIPI_LINEAR_QUEUE` already do, and a fixture for the Linear side.

Register the test in `q-system/.q-system/capability-manifest.json` or
`capability-gate.py` will (correctly) report the new engine as inert.

---

## Slice 0 — a blocker you will hit immediately, so handle it first

`/prd-review` normally runs Codex. **Codex is out of credits until 2026-08-24**
and Gemini needs auth, so the reviewer is a Claude senior-staff-engineer subagent.

The plumbing is model-agnostic (the command normalizes findings into
`{severity, body}` and appends via `findings_writer.py`), **but the source token is
not**. Verified 2026-07-26 in `plugins/prd-os/scripts/findings_writer.py`:

```
SOURCES        = ("codex-review", "codex-adversarial", "manual", "plan")
CODEX_SOURCES  = ("codex-review", "codex-adversarial")
```

`record-review` — the stamp that lets `/prd-approve` advance the PRD — **requires
a CODEX_SOURCE**. So a Claude reviewer has only bad options today: stamp
`codex-adversarial` and put a false provenance record in the findings ledger, or
skip the stamp and be unable to approve.

**Do not fake the stamp.** A provenance ledger that lies is worse than no ledger,
and this repo's whole thesis is receipts.

Slice 0 is therefore: add `claude-review` and `claude-adversarial` to `SOURCES`
and to the set `record-review` accepts, with a test asserting (a) the new sources
are accepted, (b) an unknown source is still rejected, and (c) the stamp is
written. Then the reviewer stamps the truth.

If you find a cleaner fix (for example renaming the concept to
`REVIEWER_SOURCES`), take it, and say what you changed and why.

---

## The reviewer

A Claude subagent acting as a **senior staff engineer**, adversarial by default.
Standing rule while Codex is down: **every finding must ship a runnable
reproducer.** A finding with no repro is an opinion and gets rejected at triage.
That substitute has already earned its keep: on 2026-07-25 it caught two real
blockers in the updater work.

Point it at the diff, the PRD body, `plugins/prd-os/templates/review-rubric.md`,
and `plugins/prd-os/templates/gap-classes.md`.

For a mutex specifically, tell it to attack: two claimants racing, a stale claim
whose session died, a claim held across a crash, a released claim re-taken mid
review, and the same-checkout case the Linear label cannot see.

---

## State as of 2026-07-26 (verified this session, do not re-derive)

### Linear

- One team: `ASK_Consulting`, key `ASK`, id `a75b9b87-bfdf-4fb7-bff3-a5a1a2a6946f`.
- **25 of 25 fleet repos now have a Linear project** (24 instances + the skeleton).
  Goal 1 of the rollout is complete. A fleet-wide re-plan creates zero projects.
- Issues filed this session: **ASK-114**, **ASK-115** (4_points_consulting),
  **ASK-116** (evidence-capture-protocol divergence), **ASK-117**
  (reddit-build-radar receives zero skeleton propagation).
- Labels that exist: `kind:capability`, `needs-evidence`, `unwired`,
  `fleet-shared`. **Linear does not auto-create labels**; an unknown label name is
  rejected outright. Create `claimed:claude` and any siblings before first use.
- Session report is a comment on ASK-113.

### Tooling built this session (all committed and pushed)

| Path | What it does |
|------|--------------|
| `q-system/.q-system/scripts/linear-sync.py` | Idempotent planner. `plan` / `record` / `key` / `status`. |
| `q-system/.q-system/scripts/linear-queue.py` | Offline capture half of queue-and-drain. |
| `q-system/.q-system/scripts/capability-map-gen.py` | Structural recon per repo. |
| `q-system/.q-system/scripts/capability-overlap.py` | Cross-repo divergence + collision join. |
| `plugins/kipi-core/commands/linear-drain.md` | `/linear-drain`, agent-side creation. |
| `kipi linear …` | `issue` `pending` `status` `map` `overlap` `plan` `record` `key`. |

Tests, all green: `test-linear-sync-idempotent.sh` 14, `test-linear-queue.sh` 13,
`test-linear-wiring.sh` 13, `test-linear-issue-ref-check.sh` 17.
`capability-gate.py` GREEN, 59 tests.

### The dedup key (reuse it, do not reinvent)

`<repo-slug>/<capability-slug>`, written into each Linear description as
`<!-- kipi-key: ... -->`. Two guards: a local ledger
(`q-system/output/linear-ledger.jsonl`, gitignored) and the remote markers, which
are authoritative. Proven against live Linear: wipe the ledger entirely, re-plan,
0 creates, 3 objects rehydrated from the markers. **Never drop that marker.**

---

## Open questions from the end of the last session — DO NOT let these disappear

These were asked after the push and never answered.

### Q1. CI is RED on `main`, and it was already RED before this work

Five failures, byte-for-byte identical before (`842c7fd`) and after (`4ad1cc1`):

```
test-kipi-update-build-artifacts.sh
test-kipi-update-dry-final-state.sh
test-kipi-update-hook-contract.sh
test-kipi-update-safety.sh
test-updater-issue-sequence.py
```

All five are updater tests. None came from the Linear work, and the 3 new Linear
suites pass in CI (`ran=59`). They pass LOCALLY on the same commit, so this is a
local/CI environment divergence, not logic. Already captured as `sp-3cb2e575`;
`sp-d29346e9` notes that `q-system/.q-system/` is a hidden directory that pytest
skips, which is the likely cause.

**Question for the founder: fix these next, or keep going on Linear work?**

### Q2. Branch protection is being bypassed on every push

The 2026-07-26 push printed:

```
remote: Bypassed rule violations for refs/heads/main:
remote: - Required status check "validate" is expected.
```

`validate` has not been green for at least 4 pushes, so commits land on `main` by
admin bypass. **The required-check rule is currently decorative**: configured, and
gating nothing. That is the fleet's own "no prompt-only enforcement" principle
being violated by its own main branch.

**Question for the founder: fix the 5 tests so the gate is real, or accept the
bypass and say so explicitly?** This is a founder decision, not an agent one.

### Q3. 29 of 31 planned Linear issues are still uncreated

Resumable and deterministic. `kipi linear status` says which repos are done
without querying Linear. To get exactly the gap for any repo:

```bash
kipi linear map
python3 q-system/.q-system/scripts/linear-sync.py plan \
  --map q-system/output/capability-maps/<repo>.json \
  --remote <snapshot.json> --out /tmp/plan.json --filter actionable --rollup
```

Fetch `<snapshot.json>` from Linear first (`list_issues` for the project; keep
`id`, `identifier`, `title`, `description`).

### Q4. Goal 4 of the original directive was never started

"Go through every issue in every project and mark it accurately: done / needs work
/ recorded, with evidence." That covers the 61 pre-existing `kipi-system` issues
and the 45 in `cole-GTM`. Untouched.

### Q5. Open spillover, none resolved

- `sp-7b123c14` — `kipi-new-instance.sh` hardcodes `REGISTRY`, so its test pins
  the invocation contract rather than a real run.
- `sp-cfc861f1` — kipi-investigations wires `run-lint.sh` **four times** under one
  event and matcher. Four linter runs on every Edit.
- `sp-333f81b4` — overlap `ORPHAN=1246` / `DUPLICATE=359` are too coarse to act on.
- Pre-existing: `sp-3cb2e575`, `sp-d29346e9`, `sp-2ae4df51`.

---

## Hard constraints

1. **Linear objects are permanent.** `mcp__linear__*delete*` and archive are
   blocked by `~/.claude/hooks/destructive-op-deny.sh` and an agent cannot set
   `ALLOW_DESTRUCTIVE=1` for itself. Reuse the proven dedup key before creating
   anything.
2. **Instruction budget is FAILING: 513 / 300.** `instruction-budget-audit.py
   --ratchet` is a lefthook pre-commit command and exits 1 on any regression. A new
   always-on rule requires trimming an existing one, which is a **founder
   decision**. Path-scope new rules the way `folder-structure.md` does, or put the
   text in a plan doc as Deliverable A does.
3. **Prompt-only enforcement is blocked.** `prompt-only-enforcement-guard.py`
   exits 2 on any doc claiming enforcement without naming a hook, script, test, or
   validator. Name the executable inline.
4. **Every commit needs a Linear issue id.** `linear-issue-ref-check.py` runs at
   `commit-msg` and exits 1 otherwise. Use ASK-113 or a more specific issue.
5. **Propagation.** Root `CLAUDE.md` does not reach instances; `.claude/rules/`,
   `.claude/agents/`, `q-system/CLAUDE.md`, `plugins/*/` do. A new fleet hook must
   be in BOTH `.claude/settings.json` and `settings-template.json` or
   `settings-template-sync-check.py` blocks it. `kipi update` runs
   `rsync --delete`, so instance-local automation lives at repo root.
6. **Capture, never mention.** Anything real you find and are not fixing:
   `python3 plugins/prd-os/scripts/prd_runner.py spillover add --source ASK-113
   --desc "..."`.

---

## Suggested order

0. Preconditions. Read this file and `q-system/memory/last-handoff.md`.
1. **Answer Q1 and Q2 to the founder before building** — they are one-line
   decisions that change what is worth doing next, and they have already survived
   one session without an answer.
2. `/prd-os:prd-start` for "agent claim-lock + reviewer provenance".
3. **Slice 0**: truthful reviewer sources in `findings_writer.py` + test.
4. **Slice A**: the close-discipline sentence into the standard.
5. **Slice B**: the claim lock, reproducer first, observed red, then green.
6. `/prd-review` with the Claude senior-staff-engineer subagent, stamping the
   honest source from slice 0. Triage every finding.
7. `/prd-archive` only when every accepted finding has a receipt.
8. Update `last-handoff.md` ONCE, at the end.

## Autonomy

The founder authorized this end to end. Do not ask permission to continue between
slices, and do not use handoff-doc updates as a stopping ritual. Q1 and Q2 are the
exception: they are genuine founder decisions, so ask them once, early, and keep
building everything that does not depend on the answer.

Still needs explicit founder OK: force-push, branch deletion, destructive resets,
anything the destructive-op hook blocks (including Linear deletes), and trimming an
always-on rule to make budget room.

Report honestly. If a slice is blocked, finish everything that is not, then say
exactly what you left and why.
