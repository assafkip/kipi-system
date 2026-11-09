# RCA: a founder ask outlived its ticket in three review rounds of PR #687 (2026-11-09)

Founder rulings that set the bar:
- 2026-11-07: spend, access and outside reach are "parked with its reason and listed in the morning status file. It is not a page."
- 2026-11-06 (iteration-speed rule 6): "if 3 runs failed, you should switch to a new sana agent, do an rca of why this failed and then continue".

Acceptance bar: an ask in the morning status file never outlives the ticket it asks about, whatever path closed the ticket.

**Date:** 2026-11-09
**Trigger:** PR #687 review round 3 (REQUEST CHANGES at a2824f78). It is the third round whose major is the same defect class.
**Author:** Sana (caps lane). Worktree `~/.config/kipi/worktrees/ask-4069-on-main`.

## What happened

| Round | Head | Verdict | Major found | Door |
|---|---|---|---|---|
| 1 | f5e58a54 | REQUEST CHANGES | a held ticket closed in Linear keeps its ask | the two `state.pop` sites |
| 2 | fcb93497 | APPROVE WITH NITS | a hold released by event (b), (c) or (d), then closed, keeps its ask (nonblocking) | the held loop skipped released rows |
| 3 | a2824f78 | REQUEST CHANGES | a released row that re-caps and gets SPLIT or CLOSE keeps its ask | `climb()` replaces `row["decision"]`, so its `ask_id` is gone |

## Surface symptom

`/q-morning` lists "Decisions only you can make: ASK-1: spend: approve the 900 dollar seat" for a ticket that is Completed and split into ASK-9001. The only exit is a hand-run `cap-ladder.py --resolve`.

## Surface root cause

`climb()` stores the new rung's `decision={...}`, which drops the earlier founder decision's `ask_id` from the ladder row. The ladder then closes the ticket itself (SPLIT sets Completed, CLOSE sets Canceled). The next run finds no `ask_id` on the row and never resolves the ask.

## Structural root cause

type: implicit-contract

The ask lives in one file (the status file). Whether it is still real was computed from a second file (the ladder's state rows), through every code path that edits those rows. Each path that drops, releases or replaces a row is a door, and any new path is a new door. Three rounds pinned three doors because each fix asked "where does this row go away?" instead of "is the ticket still open?". This is the shape PR #662 already named in its lifecycle test: "each round pinned only the scenario the reviewer named".

## Contributing factors

- The lifecycle test walked one ask through the CLI (`--apply`, `--founder-ask`, `--resolve`). It never walked the ladder's own SPLIT and CLOSE paths after a release.
- Asks from other jobs (`--founder-ask`, used by PRs #668 and #670) have no ladder row at all, so no row-keyed fix could ever end them.
- `test_off_switches.py` was red at f5e58a54, fcb93497 and bec6b382, and review found it, not a run. The capability gate CI runs takes about 30 minutes, and this lane pushed without running the suites under `q-system/.q-system/tests/` that read a changed file.

## Fixes shipped

- `sweep_dead_asks()` in `cap-ladder.py`, called once per run after the caps and held loops. For every issue with an open ask it reads the ticket. If the ticket is completed, canceled or duplicate, each open ask on it is resolved as moot (`resolved_by` the ladder), under `--apply` only. An unreadable ticket is read again at the next run.
- `drop_dead()` is gone. Both pop sites drop the ladder row only, and the held loop reads held rows only. One place owns an ask's end.
- `founder_asks.collect()` returns None when no ask is open (round 3 minor), and the kind refusal names the form (round 3 nit).

## Verification

Ran `python3 q-system/.q-system/scripts/test/test_cap_ladder.py` in the worktree:

```
  ok   687 major 2 (held loop): a canceled held ticket's ask is resolved as moot ...
  ok   687 major 2 (caps loop): a canceled held ticket's ask is resolved as moot ...
  ok   687 round 2 major: a released founder hold keeps its ask while the ticket lives ...
  ok   687 round 3 major: an ask dies with its ticket on every path: SPLIT after a release, and an ask the ladder never made
PASS: 0 failed   (107 ok)
```

The round 3 check failed before the fix (`FAILS 1`). Mutant: a copy of `cap-ladder.py` that never calls `sweep_dead_asks` turned all four door checks red (`FAILS 4`). `pytest q-system/.q-system/tests/test_off_switches.py`: 8 passed.

## Action items

- [x] One reconcile keyed on open asks (`sweep_dead_asks`), red-first — owner: Sana caps lane — type: code
- [x] One check per door, all through the one sweep, plus a mutant that removes it — owner: Sana caps lane — type: test
- [x] Before each push in this lane, run every suite under `q-system/.q-system/tests/` that names a changed file — owner: Sana caps lane — type: process
- [ ] Round 4 is a `--delta` review with `KIPI_REVIEW_MAX_ROUNDS=4`, posted on PR #687 with this RCA's path. If it is not approved, a fresh Sana agent takes #687 from this RCA (iteration-speed rule 6) — owner: Sana caps lane — type: process

## Lessons

- When review finds the same consequence twice through different paths, the next fix is keyed on the thing the consequence is about (here, the ticket), not on the path.
- A state that lives in one file must be judged from its own truth source. Judging it from a second file's code paths makes every path a door.
