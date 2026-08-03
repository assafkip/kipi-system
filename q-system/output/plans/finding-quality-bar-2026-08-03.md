# Plan: put a bar on findings, then drain what is already behind it

**Date:** 2026-08-03
**Trigger:** founder, 2026-08-03 — *"what does it mean 'stop the 50'? We need to ensure that things dont get half written to start with. We also need to look at the linear queue right now and if we cant validate an issue should be worked and we cant fill in the info from the correct place, that issue should be closed right away."*
**Status:** draft, nothing built

---

## What "stop the 50" means, concretely

Nothing validates a finding at write time. `cmd_spillover` in `plugins/prd-os/scripts/prd_runner.py`:

```python
if sub == "add":
    sid = args.id or f"sp-{hashlib.sha256(...).hexdigest()[:8]}"
    _spillover_append(cfg, {
        "id": sid, "source": args.source, "description": args.desc,
        "severity": args.severity, "status": "open", "created_at": _now_iso(),
    })
```

`args.desc` is any string. "We should also look at X" is accepted and recorded forever, identical in weight to a finding with a file, a line, and a failing command.

**Stopping the 50 = refusing a capture that carries no verifiable anchor.** It is the same fix as "don't let things get half written to start with." One chokepoint, both problems.

## Measured state (2026-08-03)

Two different problems that were being discussed as one.

**Spillover ledger** — has a real quality problem.

| | |
|---|---|
| open | 476 |
| names no file, no test, no command | **82** |
| names a file, but no named path resolves | 209 (candidate pool, single-root check) |
| near-duplicates | 1 pair |
| captured in Aug 1-3 | 151 |

**Linear board** — does NOT have a quality problem.

| | |
|---|---|
| active issues | 204 |
| lacking a `## Definition of Ready` | 137 |
| of those, description under 120 chars | **0** |
| median description length | 1,341 chars (min 529) |

**This corrects the founder's premise for step 3.** The board is not full of half issues. Applying "close what we cannot validate" to it today would close almost nothing. The bottleneck is `linear-dor-drafter.py`, not the issues: `--limit 8` nightly, and per `sp-e7f907a4` the batch is unsorted, carries no cursor, and a failed draft leaves the issue in `todo`, so a persistently-failing head is retried every night while the tail starves. The no-DoR count went 80 → 87 → 93 → 137.

## Approach

Three options considered.

**A. Drain first, bar later.** Triage 476, then add validation. Rejected: 50/day keeps arriving during the drain, so the drain never finishes.

**B. Bar first, drain second. ← PICK** Stop inflow, then work the backlog against a stable number. The bar is small and deterministic; the drain is large and needs judgment. Doing the small deterministic thing first makes the large one measurable.

**C. Bar + auto-file to Linear together.** Rejected for now: ASK-321 must wait until the ledger is one ledger (88 worktrees, 26 with their own copies) and the DoR drafter can keep up. Filing into a starved queue moves the pile.

### The bar (what a capture must carry)

At least ONE of:
- a file path that resolves under a known fleet root
- a command plus its actual output (the reproducer)
- a named test

Plus a `severity`. Refuse otherwise, with the refusal text naming which anchor is missing. `--force` exists but writes `anchor: none` on the row so unbarred captures stay countable, the same shape as the `[no-issue: reason]` hatch in `linear-issue-ref-check.py`.

### The close-on-sight rule (founder's step 3)

Applied at the DoR drafter, not as a separate sweep. When the drafter cannot write a DoR from real sources, today it silently leaves the issue in `todo` forever. It should instead **close the issue with the reason**. A DoR invented without sources is worse than no issue: it sends the autonomous worker at made-up requirements.

## Files to touch

| File | Change |
|---|---|
| `plugins/prd-os/scripts/prd_runner.py` | `cmd_spillover` add: anchor validation + `--force` hatch |
| `plugins/prd-os/scripts/prd_runner.py` | `_spillover_append`: persist `anchor` field |
| `q-system/.q-system/scripts/linear-dor-drafter.py` | cursor + failure-aware skip; close-with-reason when unspeccable |
| `q-system/.q-system/scripts/fleet-health-daily.py` | `detect_open_spillover`: read every repo, not `REPO_ROOT`; drop the `sp-` regex, read the JSONL |
| `.gitignore` (kipi-system) | un-ignore `.prd-os/spillover.jsonl` so worktrees share one ledger |
| new: `q-system/.q-system/scripts/spillover-validate.py` | multi-root path resolution + symbol grep; proposes voids, never auto-voids |

## Acceptance criteria

- [ ] `spillover add --desc "we should also look at this"` **exits non-zero** and names the missing anchor
- [ ] `spillover add` with a real file path succeeds and the row carries `anchor`
- [ ] `--force` succeeds and writes `anchor: none`; a count of forced rows is printable
- [ ] Negative self-test: a capture naming a file that does NOT exist is refused (proves the check reads the filesystem, not just the string shape)
- [ ] `spillover-validate.py` run over 476 prints a proposed-void list with a reason per row; **zero writes**
- [ ] The 82 anchorless rows are voided in one reviewed batch, reason recorded per row
- [ ] `detect_open_spillover` reports the consulting ledger's items, proven by the count matching `spillover list --open` run there
- [ ] `defer-*` ids appear in that output (the regex-class bug)
- [ ] `linear-dor-drafter` run twice does NOT re-attempt the same failing head, proven by a fixture with a poisoned first item
- [ ] An issue the drafter cannot spec is CLOSED with the reason, not left in `todo`
- [ ] One ledger across worktrees: capture in a worktree, read it from the main checkout

## Patterns to follow (from this repo)

- **Refuse, do not guess.** `pipeline/proposal.py` raises rather than inventing a price; `sizer` refuses a client nobody researched. The bar is the same shape.
- **Countable hatch.** `linear-issue-ref-check.py` allows `[no-issue: reason]` and appends to `linear-bypass.jsonl`. Copy that, not a silent skip.
- **Single writer.** `_spillover_append` is already the only writer. Put the bar there, not in callers.
- **Absent is not failing.** `sp-5b736e86` / ASK-327: a timeout printed as RED cost real hunting time. `spillover-validate.py` must label unresolvable-path separately from confirmed-gone.
- **Prove the negative.** `fable-discipline`: every check needs a test that fails when the check is removed.

## Order

1. The bar (`spillover add`) — small, deterministic, stops inflow
2. Void the 82 anchorless
3. `spillover-validate.py`, proposals only, then one reviewed batch void
4. DoR drafter: cursor + close-on-unspeccable
5. One ledger across worktrees
6. Fix `detect_open_spillover`
7. Only then ASK-321 (auto-file to Linear)

## Open question for the founder

Steps 2 and 3 delete recorded findings in bulk. Voids are recorded and reversible in principle, but nobody re-reads a void. Does a batch void need founder sign-off on the proposal list, or is a recorded reason per row enough?
