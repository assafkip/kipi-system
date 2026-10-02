---
id: prd-model-gate-2026-10-02
title: Model Gate
status: approved
created_at: 2026-10-02T06:12:17Z
updated_at: 2026-10-02T06:19:37Z
owner: sana
reviewers: []
findings_path: .prd-os/findings/prd-model-gate-2026-10-02-findings.jsonl
codex_reviewed_at: 2026-10-02T06:19:36Z
reviewed_by: claude-review
---

# Model Gate

## Problem

One automation day (2026-10-01) spent most of a week's subscription usage. The usage
ledger (`~/.config/kipi/usage-ledger.jsonl`, 8 days measured 2026-09-23..10-01) shows
fleet spend of $0 to $18 a day, then $99.42 on 09-30 and $582.76 on 10-01, of which one
bot (voiceloop) was $572.95. PR reviews ran 4 to 7 rounds each. Every existing cap is local
to one path (converge MAX_ROUNDS, redrive per sha, dispatch per day); none sits at the
point every model call passes, and nothing refuses a call because a job or the fleet has
spent its day. The meter exists (`voiceloop/usage_ledger.py`); a limit does not.

## Goals

- One gate every headless model call goes through, with three limits read from one place:
  a daily budget per job, a fleet daily ceiling, and a round cap per work item keyed on the
  item (PR number, issue id), never the commit sha.
- Cost is measured, not guessed: spend is read from the usage ledger rows that
  `--output-format json` already produces.
- Over a limit the gate refuses, exits cleanly, and files ONE alert per job, limit and day
  through `slack-notify.sh` (Sana's queue). A gate error fails closed the same way.
- A daily scanner enumerates call sites from source in every local checkout and reports any
  site that does not pass through the gate.

## Non-goals

- Editing other repos. Chief's `run_claude` and the consulting pipeline helpers get
  follow-up tickets (below), not edits here.
- Routing every remaining direct `claude -p` site in this PR set. The scanner lists them;
  each is its own follow-up.
- Per-run caps (`--max-turns`, `--max-budget-usd`): open PR #469 owns that.

## Proposed approach

- `plugins/kipi-core/voiceloop/model_gate.py`, stdlib only, beside the meter it reads.
  `check(job, item=None)` takes an exclusive lock on the gate ledger
  (`model-gate.jsonl`, beside the usage ledger, `KIPI_MODEL_GATE_LEDGER` overrides), sums
  today's (UTC) `total_cost_usd` for `bot == job` and for the fleet from the usage ledger,
  counts prior admitted calls for `(job, item)` in the gate ledger, decides, appends one
  row, releases. It is the only writer of the gate ledger.
- `q-system/.q-system/scripts/model-gate.sh --job J [--item K] -- <cmd...>`: the shell
  door. Runs `check`; on admit it runs the command, and when the command printed
  `--output-format json` it appends the cost row to the usage ledger (via
  `usage_ledger.finish`) without changing the caller's stdout.
- Defaults, env-configurable: per-job $25/day (`KIPI_MODEL_GATE_JOB_USD`, per job
  `KIPI_MODEL_GATE_USD_<JOB>`), fleet $100/day (`KIPI_MODEL_GATE_FLEET_USD`), round cap 3
  (`KIPI_MODEL_GATE_ROUNDS`). Measured basis: the highest normal bot day was $14.11, the
  highest normal fleet day $17.99; the cap of 3 matches the reviewer cap in PR #501.
- **Report-only until 2026-10-09.** Mode `report` logs and alerts but admits. From
  2026-10-09 the default is `enforce`. `KIPI_MODEL_GATE_MODE=report|enforce` overrides.
  The flip is a date constant in code, so nobody has to remember it; the alerts of the
  report week are the evidence for tuning budgets before it.
- `run_model` calls `check` before its subprocess; a refusal returns None, the outcome its
  callers already handle. The brief's "skeleton claude_p" does not exist on main (grep of
  every repo under the projects root, 2026-10-02): the shell door above is that wrapper.
- `fleet-model-gate-scan.py` plus a daily plist, on the `fleet-full-suite-scan` pattern:
  same checkout population, the existing `call_sites` detector, alert on a state change.
  An ungated site is a detected site that is not the wrapper and not behind `model-gate.sh`.
  Known blind spots (cloud routines, non-claude binaries, shell strings assembled in Python)
  are printed as `unscanned`, never as clean (finding 6).

## Alternatives considered

- **A second spend ledger written by the gate.** Rejected: two writers of spend; the usage
  ledger is already the meter, the gate only reads it.
- **Round cap keyed per head sha.** Rejected: that is the redrive cap, and a fix commit
  resets it (RCA root cause #1).
- **Enforce from day one.** Rejected: a wrong budget would darken live bots.

## Scenarios

- **Review loop.** A reviewer is invoked a 4th time on PR 123 through
  `model-gate.sh --job pr-review --item pr-123`; the gate counts 3 prior rounds, refuses
  (enforce) or admits and alerts (report), and the model is not called in enforce mode.
- **Runaway bot.** voiceloop passes $25 today; its next `run_model` is refused in enforce
  mode and returns None; one alert lands in Sana's queue, not one per call.
- **New script.** Someone adds a direct `claude -p` call; the next daily scan lists it and
  alerts once.

## Resolved decisions

- **Day boundary.** Decided: UTC date of the row `ts`. Rationale: ledger rows are UTC.
- **Refusal exit.** Decided: the shell door exits 75 (EX_TEMPFAIL), command not run.
  Rationale: exit 0 with empty stdout reads as "no findings" to a reviewer caller (review finding 4).
- **Unsettled spend.** Decided: a call admitted with no usage row yet, and a usage row with no
  cost, are charged `KIPI_MODEL_GATE_UNSETTLED_USD` (default $1). Rationale: findings 1 and 3;
  a $0 reading admits every parallel call. Per-run caps (PR #469) bound the remaining overshoot.
- **Round key.** Decided: the caller names the item with its repo or tracker (`owner/repo#N`,
  `ASK-N`); rounds count only calls admitted in the current mode, so report-week history does
  not refuse busy items on flip day. Rationale: finding 5.
- **Job identity.** Decided: the gate's job key is the meter's `bot`, resolved by the same
  code in `run_model`, and the shell door writes `bot = --job`. Rationale: finding 2.

## Risks and rollback

- Blast radius: every `run_model` caller. One policy for a gate error: report mode admits,
  enforce mode refuses; both alert once a day. Rollback: `KIPI_MODEL_GATE_MODE=report`
  in the job env, or revert the PR.
- Lock contention: one `flock` per call held for one file read; calls are seconds apart.

## Open questions

- Follow-up tickets (other repos): route chief `talk.py run_claude` through the gate; route
  the consulting pipeline model helpers through the gate; then the remaining direct sites the
  scanner lists.

## Issues` below.
-->

## Issues

<!--
After review and approval, populate the fenced JSON block below. The manifest is
read by TWO consumers and every entry must satisfy both:
  - `prd_split.py` materializes one issue spec per entry (needs `id`).
  - the approval gate proves every ACCEPTED finding is covered by an entry (needs
    `finding_id` + a `bypass_check`). One entry per accepted finding.

Required keys per entry (spine-native -- both consumers):
  - id (kebab-case, unique across the repo)            -- prd_split.py
  - finding_id (the accepted finding it covers, e.g. "finding-1") -- approval gate
  - title (non-empty string)
  - allowed_files (non-empty list of glob patterns)
  - required_checks (non-empty list, e.g. ["pytest -q"]). The stop-gate checks
    three receipts (verified, reviewed, findings_triaged); they are meaningless
    unless the spec documents what must be verified, so an empty list is rejected.
  - bypass_check (a command proving no bypass remains) OR
    bypass_exempt: "<reason>"                          -- spine contract

Write bypass_check as an INVARIANT, not a token count. Counting occurrences of
an identifier looks deterministic and is not: prose in a comment inflates it, a
refactor that renames or inlines deflates it, and neither fact says anything
about whether a bypass remains. Prefer "exactly one scan exists", "the byte
compare lives in one place", "the guard is still present" over
`grep -c <name> == N`. If a count really is the invariant, exclude comment lines
(`grep -v '^[[:space:]]*#' | grep -c`) and use `grep -F` for patterns holding
regex metacharacters such as `$`.

Scar 2026-07-26 (prd-updater-consolidation): three of five bypass_checks were
grep-count proxies and each needed a mid-issue amendment. One did real damage --
it demanded three calls to a function, so a redundant dead call was written
purely to satisfy the number, and adversarial review caught it. A check that
shapes the code to fit the check is worse than no check.

Optional keys:
  - priority (default p1)
  - disallowed_files, required_reviews, acceptance

Authoring a manifest with `id` but no `finding_id` (the pre-spine shape) is
rejected at approve. The template-vs-runner contract test enforces this list.
-->

```json
[
  {"id": "mg-gate", "finding_id": "finding-1", "title": "model_gate module + model-gate.sh shell door (ASK-2393)",
   "allowed_files": ["plugins/kipi-core/voiceloop/model_gate.py", "plugins/kipi-core/voiceloop/tests/test_model_gate.py", "plugins/kipi-core/voiceloop/tests/test_engine_surface.py", "q-system/.q-system/scripts/model-gate.sh"],
   "required_checks": ["bash -c 'cd plugins/kipi-core && python3 -m pytest voiceloop/tests/test_model_gate.py -q'"],
   "bypass_check": "bash -c 'cd plugins/kipi-core && python3 -m pytest voiceloop/tests/test_model_gate.py -q -k round_cap_is_keyed'",
   "acceptance": "A 4th call on one item is refused in enforce mode whatever the sha; unsettled calls are charged; one alert per job, limit and day; the door exits 75 and never runs the command on refusal."},
  {"id": "mg-route-run-model", "finding_id": "finding-2", "title": "voiceloop run_model asks the gate before any provider branch (ASK-2394)",
   "allowed_files": ["plugins/kipi-core/voiceloop/prompt_render.py", "plugins/kipi-core/voiceloop/tests/test_model_gate_route.py"],
   "required_checks": ["bash -c 'cd plugins/kipi-core && python3 -m pytest voiceloop/tests/test_model_gate_route.py voiceloop/tests/test_usage_ledger.py -q'"],
   "bypass_check": "bash -c 'cd plugins/kipi-core && python3 -m pytest voiceloop/tests/test_model_gate_route.py -q'",
   "acceptance": "A refused run_model call never starts the binary and returns None; the gate's spend for the job rises by the row the meter wrote."},
  {"id": "mg-door-scan", "finding_id": "finding-6", "title": "Daily fleet scanner for model call sites not behind the gate (ASK-2395)",
   "allowed_files": ["q-system/.q-system/scripts/fleet-model-gate-scan.py", "q-system/.q-system/scripts/com.kipi.fleet-model-gate-scan.plist", "q-system/.q-system/tests/test_fleet_model_gate_scan.py", "AUTONOMOUS-SYSTEMS.md"],
   "required_checks": ["python3 -m pytest q-system/.q-system/tests/test_fleet_model_gate_scan.py -q"],
   "bypass_check": "python3 -m pytest q-system/.q-system/tests/test_fleet_model_gate_scan.py -q",
   "acceptance": "A checkout with a direct claude -p site is reported ungated and alerts once; the same site behind model-gate.sh is not; blind spots print as unscanned."},
  {"id": "mg-unload-pr86", "finding_id": "finding-7", "title": "Unload com.kipi.pr86-review and drop its exemption (ASK-2396)",
   "allowed_files": ["q-system/.q-system/scripts/test/test-loaded-label-has-template.py", "AUTONOMOUS-SYSTEMS.md"],
   "required_checks": ["python3 q-system/.q-system/scripts/test/test-loaded-label-has-template.py"],
   "bypass_check": "python3 q-system/.q-system/scripts/test/test-loaded-label-has-template.py",
   "acceptance": "With the allowlist entry removed the check is red while the job is loaded and green once it is unloaded."}
]
```
