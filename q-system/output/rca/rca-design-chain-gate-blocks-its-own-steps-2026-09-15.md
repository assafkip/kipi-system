# RCA: the design-chain gate blocked every step of the command it enforces

**Date:** 2026-09-15
**Trigger:** first end-to-end run of `/design-chain askconsulting`. Before writing any page, the hook was exercised against a synthetic payload in a temp state dir; `seal`, `design-standard-check.py` and the measurement serve all came back exit 2.
**Surface-fix commit:** pending
**Structural-fix commit:** pending

## What happened

`design-chain-gate.py` is wired PostToolUse/PreToolUse/Stop in `.claude/settings.json` and `settings-template.json`. Once a page file enters its session ledger, its `PreToolUse:Bash` branch blocked any command matching `BASH_SHOW_RE`, or any command merely naming an open page. Those two conditions cover the chain's own steps: step 5 (`design-standard-check.py <page>.html`, which writes the required `standard.json`), step 5's serve (`python3 -m http.server`), step 9 (`shoot*.py`, `gate_icp.py`), and step 10 (`design-chain-gate.py seal <round>`). Expected: an agent writes pages, runs the steps, seals, shows the founder. Actual: the moment a page existed, every remaining step was unreachable, and the `Stop` hook also refused to let the turn end.

## Surface symptom

The block message named the command it was blocking. From `test_seal_is_reachable_end_to_end` before the patch, with a complete-but-unsealed chain:

```
DESIGN CHAIN GATE (blocked): a page was made this session and its design chain is not complete.
  .../site/design/r1/Pair-laptop.html: not sealed: run `design-chain-gate.py seal .../site/design/r1`
  Steps: ... -> `design-chain-gate.py seal <round>`.
```

`seal` was the only outstanding problem, and `seal` was the blocked command.

## Surface root cause

Two clauses in the `PreToolUse:Bash` branch of `design-chain-gate.py`:

1. `BASH_SHOW_RE = re.compile(r"(screenshot|playwright|http\.server|shoot\w*\.py|gate\w*\.py|comprehension|open\s+-a|vercel\s+deploy)")`. `gate\w*\.py` matches the substring `gate.py` inside `design-chain-gate.py`, so the gate matched its own name. `http.server`, `shoot*.py` and `comprehension` are steps 5 and 9.
2. `any(Path(p).name in cmd for p, _ in opens)` blocked any command naming an open page. Step 5's invocation is `design-standard-check.py <page>.html`, which names the page by contract.

## Structural root cause

### Root cause #1: two different acts were given one name

`type: implicit-contract`

The regex is named `BASH_SHOW_RE` and its comment read "commands that show, serve or test a page". Showing a page to the founder and rendering a page to measure it are opposite acts under this gate: one is what the chain forbids before the seal, the other is how the chain reaches the seal. Folding "serve" and "test" into "show" made the forbidden set a superset of the required set. Once those are one category, no amount of tuning the pattern helps; the category itself is wrong.

### Root cause #2: the passing test hand-wrote the receipts instead of running the steps

`type: missing-test`

`test_full_chain_passes_send_and_stop` proved the chain's END state is accepted: it calls `complete_chain()`, which writes `brief.md`, `directions.md`, `critique.md`, `proof.md`, `standard.json`, `checks/` and `gate/` directly with `Path.write_text`, then invokes `seal` as a CLI subprocess rather than through the `PreToolUse:Bash` hook. So the suite verified that a finished chain unblocks, and never that a chain can be finished. Every step between "page written" and "receipts exist" was outside the test's reach, which is exactly where the defect lived.

### Root cause #3: the gate shipped without its own command ever being run

`type: process`

The gate, its config, the standard checker and the `/design-chain` command all landed in the same change (branch `fix/candidate-draft-one-definition`, staged). The test suite was green and the pieces were reviewed as files. Nobody executed `/design-chain` end to end against a real instance, so the deadlock waited for the first real run. This is the "reading is not testing" class: only executing in a real session finds absence.

## Verification

- Ran `python3 -m unittest test_design_chain_gate -v` with the two new tests added and no patch applied: `FAILED (failures=2)`. `test_chain_steps_run_while_chain_is_open` failed on `design-standard-check.py`; `test_seal_is_reachable_end_to_end` failed on `seal`, printing the self-referential block message quoted above. The reproducer was seen red before the fix.
- Applied the patch, re-ran the same command: `Ran 14 tests in 1.118s / OK`. All 12 pre-existing tests still pass, including `test_playwright_tool_blocked_while_open`, `test_written_page_blocks_stop_until_chain`, `test_stale_receipt_after_edit` and `test_standard_fail_blocks`, so the gate's teeth are intact.
- Confirmed the narrowed block still fires: `test_bash_that_shows_a_page_is_blocked` now asserts exit 2 for `open -a Preview Pair-laptop.png`, `vercel deploy --prod` and `open Pair-laptop.html`, and exit 0 for `git status`. Observed all four.

## Contributing factors

- The regex matched the gate's own filename through `gate\w*\.py`, which is only visible if you read the pattern against the script's own name. A pattern that can match the file it lives in is easy to write and hard to see.
- The block message is well written and names the remedy, which made the deadlock read like a normal, actionable block rather than a defect. A gate whose block text names a command it also blocks is indistinguishable from a gate working correctly until you try the command.
- The gate was built the same day as the scar it answers (two rounds of first screens ignoring the canon), under time pressure to close the hole rather than to run the loop.

## Fixes shipped

- `q-system/.q-system/scripts/design-chain-gate.py`: `BASH_SHOW_RE` narrowed to the two Bash paths that actually put a page in front of a human, `open -a ...` / `open <file>.html|png|jpg|pdf` and `vercel deploy`. The page-name-in-command clause was removed from the Bash branch, because the chain's own steps name the page by contract. A header note and an inline comment record why the list is short, so the next reader does not re-add the render verbs.
- `q-system/.q-system/scripts/test_design_chain_gate.py`: new `TestChainStepsRun` with `test_chain_steps_run_while_chain_is_open` (all five chain steps must return exit 0 while the chain is open) and `test_seal_is_reachable_end_to_end` (complete-but-unsealed chain, seal survives its own hook, then seals, then Stop passes). `test_bash_that_shows_a_page_is_blocked` rewritten against the new boundary.

Unchanged and still blocking before the seal: `SendUserFile`, `Artifact`, every `mcp__playwright__*` / `mcp__claude-in-chrome__*` / chrome-devtools tool, and the `Stop` hook. None of those is how a chain step runs; all of them are how a page reaches the founder.

## Action items

- [x] Narrow `BASH_SHOW_RE` to human-facing Bash paths only. Owner: this session. Evidence: 14/14 tests green.
- [x] Add a test that runs each chain step through the `PreToolUse:Bash` hook while the chain is open. Owner: this session. Evidence: `TestChainStepsRun`, seen red then green.
- [ ] Run `/design-chain askconsulting` to `seal` at least once before the gate's wiring is treated as proven. Owner: this session, in progress. Evidence: `site/design/2026-09-15/receipts.json` exists.
- [ ] Re-check the other gates added in the same change (`design-standard-check.py`, the `/design-chain` command registration) for the same shape: a gate whose remedy is a command the gate blocks. Owner: Sana. Evidence: a named command per gate that is verified runnable while the gate is red.
- [ ] Propagate to the fleet: the gate ships via `settings-template.json`, so every instance carries the deadlocked version until `kipi update` runs. Owner: Sana. Evidence: `kipi update --dry` shows the script diff.

## Lessons

**A gate must be able to name the command that clears it, and that command must run.** The remedy named in a block message is part of the gate's contract. If the gate also blocks the remedy, the gate is not strict, it is broken, and it looks identical to a strict gate from the outside. Every blocking gate deserves one test that executes its own stated remedy while the gate is red.

**"Show" and "render" are different acts and must not share a pattern.** A receipt-based chain has to render its artifact to measure it. Any gate that forbids rendering before the receipts exist forbids the receipts. Separate the surfaces that reach a human (publish tools, the Stop hook, `open`, a deploy) from the machinery that produces evidence, and only guard the first set.

**A test that builds the end state by hand proves the end state, not the path.** `complete_chain()` wrote every receipt with `write_text`, so the suite could be green while the path to those receipts was impassable. When a system's value is a sequence, at least one test has to walk the sequence through the same interface a caller uses.
