# Continuation prompt: the Linear agency — severity floor + convergence proof (ASK-113)

Written 2026-07-27 at the end of the session that built the autonomous loop.
Paste the whole thing into a fresh session.

---

You are continuing autonomous work in `/Users/assafkipnis/projects/kipi-system`.
Tracking epic: **ASK-113**. Read `q-system/memory/last-handoff.md` and
`~/.claude/.../memory/feedback_detect_act_learn.md` context first. The founder
authorized this end to end; ask nothing except the founder decisions marked below.

## What exists and RUNS (do not rebuild any of it)

| Piece | Command / schedule | State |
|---|---|---|
| Daily health check, 6 detectors, detect-act-learn enforced | `kipi health [--apply]` · launchd 08:15 | live |
| DoR drafter (8 issues/night, appends, Energy+Time line) | `kipi dor [--apply]` · launchd 03:00 | live |
| Direct Linear creation (dry-by-default, remote-guard refetch) | `kipi linear create/remote/plan/progress` | live, key at `~/.config/kipi/linear-api-key` |
| Claim lock, (agent, session) identity, fails closed | `kipi linear claim/release/claims` | live |
| Autonomous worker: worktree per issue, rework path; its 4 refusals are code paths in `linear-worker.sh` (the `ready()` picker skips no-DoR and `owner:assaf`; no merge/close verbs exist in the script) | `kipi work [--apply] [--issue ASK-n]` | manual only — DO NOT schedule yet |
| Adversarial PR reviewer (Netflix-staff persona, repro-or-drop) | `kipi review <PR#> [--post]` · auto after every worker PR | live |
| Job-migration issues, one per launchd job | `kipi jobs [--apply]` | ASK-151..186 filed |

Board: ~187 issues, all open ones labeled `owner:sana`, 54+ worker-ready
(DoR present, not `owner:assaf`). Sana = the kipi Systems Engineer persona
(cole-gtm `persona/ENGINEER.md`); ownership is a LABEL, Sana has no Linear seat.

## Where the last session stopped, mid-flight

- **PR #11 / ASK-150, round 3**: rework pushed (`ok ASK-150` 04:51), review
  round 3 was RUNNING at handoff. Verdict lands in
  `~/.config/kipi/pr-reviews/pr-11-20260726-215111.md` (or the run was killed at
  its 2400s wall clock). Rounds so far: R1 = 2 blockers/REQUEST CHANGES,
  R2 = 1 blocker/REQUEST CHANGES. Converging, not oscillating.
- The repo-root claim may still be held by the dead worker session
  (`worker-1785127223-35268` on ASK-150). If `kipi linear claims` shows it and no
  worker is running: `python3 q-system/.q-system/scripts/linear-claim.py claim
  ASK-150 --agent sana --session <new> --break-stale --holder worker-1785127223-35268`
  or just release-by-holder. Do NOT hand-delete the lock file.
- Round 3 ran the pre-counter script, so `~/.config/kipi/linear-worker-attempts.json`
  may be missing/stale. The rounds counter only records from the next run on.

## THE TWO FIXES THE FOUNDER APPROVED — this is the next work

The diagnosis, verified against the review files: findings converge (2→1
blockers) but **the reviewer has no severity floor** — REQUEST CHANGES fires the
same on 3 minors as on 1 blocker, and a Netflix-3am bar ALWAYS finds something,
so **nothing can ever reach APPROVE**. The gate is unsatisfiable by construction.

### Fix 1 — severity floor in `pr-review-agent.sh` + the worker

- Verdict rule for the reviewer prompt: **blockers or majors ⇒ REQUEST CHANGES;
  minors/nits alone ⇒ APPROVE WITH NITS.**
- On APPROVE WITH NITS, the loop CAPTURES each minor as a tracked follow-up
  (spillover via `prd_runner.py spillover add`, or a keyed Linear issue) instead
  of wedging the PR. That is `no-orphan-findings.md` applied to review findings —
  today minors are neither captured nor actionable, they just block.
- Deterministic slice: the worker parses the verdict; only REQUEST CHANGES/BLOCK
  triggers another rework round. Do not leave verdict-parsing to prose.

### Fix 2 — prove convergence on a BORING issue

ASK-150 was the worst possible first pick: an unattended detector writing
permanent, undeletable Linear objects. Pick an issue with **no permanent side
effects and no unattended path** (a doc fix, a pure-function refactor with an
existing test, one of the `kipi-system` CAP rule issues). Run
`kipi work --apply --issue <that>` and count rounds-to-APPROVE.

- Converges in 1–2 rounds ⇒ the loop is sound, ASK-150 was just hard.
  THEN scheduling the worker becomes a founder question — ask it with the data.
- Also takes 3+ ⇒ the problem is the worker, say so plainly and stop scheduling
  talk entirely.

## Founder rules established this session (binding, with receipts)

1. **Detect → Act → Learn.** Every detector needs a logged automated action AND
   a lessons-corpus link (or an explicit waiver). Enforced in code:
   `fleet-health-daily.py::validate_detectors` refuses alert-only checkers.
   One Slack summary line, never one ping per finding.
2. **False alarms are the enemy.** Three instances killed in one day, same shape:
   paused launchd jobs that could not be silenced (26 false pings), 5 inert
   `Write()` deny rules warning on every run fleet-wide, and the claim-lock test
   failing whenever the product was IN USE. If a check cries wolf, fixing the
   check is priority work, not hygiene.
3. **A fixture invented by the author tests nothing.** The claim-lock's remote
   half read `state`; Linear emits `status`+`statusType`. It never fired while
   its suite was green. Fixtures must be verbatim captured payloads.
4. **Check the layer above the fix.** Both review rounds found the same shape:
   the fix landed on the detector, not the report (R2: the update path rewrites
   a CLOSED issue and never reopens it — worse than the bug). Walk every changed
   value to its consumers. Encoded in the worker's rework prompt.
5. **The review is the spec for a rework pass.** Fix each finding with a test
   that fails without the fix, or answer it on the PR. Silence on a finding is
   not an option.

## Standing constraints (unchanged)

- **Subscription only.** No API-key model spend; Linear coding sessions (AI
  credits) and Triage Intelligence stay OUT. `claude -p` under **launchd only,
  never cron** — cron has no keychain (ASK-150, `keychain_read_rc=44`).
- **Linear objects are permanent.** Delete/archive hook-blocked. Every creator
  goes through the kipi-key dedup guard; refetch the remote guard before writing.
- **The worker's four refusals are load-bearing**: never merges, never closes an
  issue, never touches `owner:assaf`, never touches an issue without a DoR.
- **`validate` on main is still RED** on the 46 real containment findings
  (ASK-58/ASK-59; the ~11.7k `unclassified_populated_record` are warn-only,
  `sp-88d889b5`). Every merge is an admin bypass until fixed. This caps how much
  the worker's PRs are worth — flag it whenever merging comes up.
- Instruction budget FAILING 513/300: no new always-on rules; plan docs instead.

## Open, tracked, not urgent

- 26 paused com.cole.* jobs: coming back only via migrate-then-verify
  (ASK-151..186, memory `project_cole_pause_pending_linear`).
- 81 open spillover items: ASK-148.
- Open PRs besides #11: #4, #5 (pre-existing).
- Reviewer round-3 open question: does a fresh reviewer stay calibrated on
  familiar code? R2 held the bar; keep watching.

## Suggested order

1. Read the round-3 verdict file; post/record it if the run died before `--post`.
2. Fix 1 (severity floor + verdict parsing + minor-capture). Test: a synthetic
   review with only minors ⇒ worker does NOT re-run; with a blocker ⇒ it does.
3. Clear the stale ASK-150 claim if present.
4. Fix 2: pick the boring issue, run it, count rounds. Report the number.
5. If PR #11's round 3 came back REQUEST CHANGES again: one more rework pass
   under the new floor, then stop and summarize rather than looping further.
6. `kipi health` at start and end; leave `last-handoff.md` updated ONCE at close.
