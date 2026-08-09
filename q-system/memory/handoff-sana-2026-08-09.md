# Sana handoff — 2026-08-09

State at stop. Written to be readable without the chat thread.

## Single next action

`sp-1c959431` — the comment-blindness enumeration. Start by reading that ledger
item; it carries the full framing and the fix shape.

```bash
python3 plugins/prd-os/scripts/prd_runner.py spillover list | grep sp-1c959431
```

## Where the PRs are

| PR | Issue | State |
|----|-------|-------|
| #126 | ASK-471/426/503/504/505/507 | MERGED `84b5ba27` |
| #127 | ASK-508 | MERGED `71912fac` |
| #128 | ASK-512 | MERGED `85eb96cf` |
| #130 | ASK-517 | MERGED `aa3a99bd` |
| #129 | ASK-514 | see below |
| #125 | — | CLOSED, unmergeable by construction; branch `sana/bake-in-and-cleanup` kept at `464be47a` |

**#129** (`sana/version-bump-merge-base`, head `e9f2c057`): reviewer APPROVE
(clean, round 4), `validate` was the last gate. If it merged, close ASK-514 and
resolve `sp-05762519`, `sp-a8bbaae7`, `sp-00370692`, `sp-10729c93` against it.
If it did not, the branch is fully tested locally — re-run `validate`, nothing
in the tree needs changing.

## Open ledger items, with the read on each

Collapse by id, last-write-wins, before trusting any listing — the file is
append-only and a naive `status=open` filter reports superseded rows as open.

```python
last = {}
for line in open(".prd-os/spillover.jsonl"):
    r = json.loads(line); last[r["id"]] = r
open_items = [r for r in last.values() if r["status"] == "open"]
```

- **`sp-1c959431`** — comment-blindness CLASS. A text-matching check that does
  not strip comments reads commented-out code as live. Two confirmed instances:
  `capability-gate.py` `references_engine()` (**still unfixed**) and a workflow
  regression test (fixed in `e9f2c057`). Wants ONE executable enumeration over
  every text-matching check, not a third one-off patch. **Picked as next.**
- **`sp-883d5b0e`** — `METRICS_VERSION` is a hand-bumped constant guarding a
  blocking unattended gate, and was missed twice in one session by someone who
  knew the rule. Proposed fix is a golden-vector test so the bump gets a receipt
  instead of a promise.
- **`sp-ef66e61c`** — Fable escalation timeout is a BUDGET defect, measured, one
  line. 133 of 266 real calls time out at 45s; successes run median 32.9s / p90
  42.0s against a 45s cap. The docstring's "5.35s" is 6x stale. True tail is
  unknown (censored at the cap), so pick a value clear of p90 and re-measure.
- **`sp-572921ae`** — 5 red tests in `tests/separation/`, cause pinned to
  `347bf674` (ASK-117). They are STALE TESTS asserting a pre-ASK-117 contract,
  not a broken updater. `kipi check` never runs that suite, so its green is
  silence. Fix the fixtures, THEN wire the suite in — wiring it red turns the
  fleet harness red.
- **`sp-0775ad28`** — token-guard's stall detector cannot see a file written via
  Bash; `update_counters` only resets on the Edit/Write tools. Fires constantly
  through productive sessions. Do NOT just add `Bash` to the tuple — every `ls`
  would then count as progress.
- Resolving with ASK-514: `sp-05762519`, `sp-a8bbaae7`, `sp-00370692`,
  `sp-10729c93`.

## Two things that will bite whoever picks this up

**The version-bump gate depends on the base it is handed.** With a stale base a
diff cannot separate the PR's changes from main's history, and no gate-side work
fixes that. CI now passes `github.event.pull_request.base.sha`; `fetch-depth: 0`
is load-bearing for it. Do not reintroduce a fetched ref.

**Do not launch the PR reviewer in the same shell call as a push.** It reads the
head twice and refuses when it moves, so it will race your own push and post
nothing. Push, confirm the branch settled, then launch.

## The pattern from this session, recorded because it recurred

Five checks were fixed that could not fail for the reason they existed:
`METRICS_VERSION - 1` (follows the constant), a property table asserting only
"must not survive as usable" (`0.0` satisfies it), case D exiting 2 for the
wrong plugin, `capability-gate`'s matcher missing an import, and a workflow test
satisfied by its own comment. Four were mine.

Four claims I recorded were later overturned by measurement: the dirty-registry
hypothesis, "the two blockers are independent", the comment-presence proxy that
read 7-of-7 ABSENT when main had reimplemented every fix, and "ASK-514 already
defanged the `|| true`". In every case reasoning about a guard was less reliable
than running it. Run the guard.
