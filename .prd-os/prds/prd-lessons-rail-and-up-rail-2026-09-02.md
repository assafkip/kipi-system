---
id: prd-lessons-rail-and-up-rail-2026-09-02
title: Lessons rail and up-rail (Phases 3 and 4 of the morning-brief overhaul)
status: draft
created_at: 2026-09-02T00:11:10Z
updated_at: 2026-09-02T00:13:04Z
owner: assaf
reviewers: []
findings_path: .prd-os/findings/prd-lessons-rail-and-up-rail-2026-09-02-findings.jsonl
---

# Lessons rail and up-rail (Phases 3 and 4 of the morning-brief overhaul)

Source plan: `q-system/output/plans/morning-brief-overhaul-2026-08-30.md`, Phase 3
(the lessons rail is broken, three causes) and Phase 4 (kipi and consulting
update each other, founder-directed 2026-09-01, which resolves Phase 3's 3c in
favour of an explicit upward collect). Follows `prd-morning-brief-learns-2026-09-01`
(Phase 2), whose 15 issues shipped 2026-09-01 on branch `prd/morning-brief-learns`.

## Problem

Measured 2026-09-01, in this repo and in `~/projects/consulting`:

- **Fan-out has failed on every logged run for five weeks.** `lessons-daily.sh:55`
  propagates by shelling `kipi-update.sh`; `q-system/output/lessons-daily.log`
  records `propagate FAILED` on 2026-07-27, 08-03, 08-10, 08-17, 08-24 and 08-31.
  Latest abort: `the skeleton is not on main. HEAD is on sana/wip-rescue-2026-08-29`
  (`kipi-update.sh:623-637`). The 08-10 run failed differently (`Failed: 3`).
  Six correct alarms, filed to Sana's Linear queue via `slack-notify.sh`, no
  action: a detector with no logged automated action.
- **The alarm reads identically on night 1 and night 40.** Nothing counts the streak.
- **Eight lessons exist only in consulting** (`~/projects/consulting/q-system/lessons/`,
  dated 2026-08-10 to 08-21), hand-authored inside consulting feature PRs
  (commits `e9ebd7e4`, `84a83d5d`, `4eeaa049`), with no provenance frontmatter.
  Nothing moves a lesson from an instance up to the skeleton.
- **`kipi push` from consulting is blocked at its lessons guard.**
  `kipi-push-upstream.sh:38-84` compares every `lessons/*.md` blob against the
  skeleton and exits 1 on ANY difference, either direction. The eight divergent
  lessons trip it before any other content is reached.
- **Recall reads whatever copy the session sits on.** `lessons_recall.py:52-54`
  resolves the corpus from its own file location, no override, no statement of
  which copy answered. Counts on 2026-09-01: skeleton working tree 161, main
  153, consulting 154. Three wrong claims in one planning session came from
  checking one repo while the capability lived in the other (plan CAP-3).
- **A shared launchd label.** consulting's `install-lessons-daily.sh` hardcodes
  `com.kipi.lessons-daily`, the label kipi's installed weekly job uses; running
  it would silently rebind the label to a daily consulting run. The skeleton has
  no plist template for its own job (installed by hand, Weekday 1 06:00).
- **Three stages found built, correct, and never running** in one session
  (`route-overrides-to-learn.py`, the propagation call, the untriggered upstream
  push). Three is a class, not three bugs.
- **Repo-wide audits count dead copies.** 27 directories under `.claude/worktrees/`
  plus `.wt-*` at the repo root each hold a full tree; one script name returned
  184 hits outside the real file (plan CAP-2).

## Goals

- After N consecutive propagation failures the job emits a DIFFERENT line
  carrying the streak length, so a five-week streak reads differently from one
  bad night, and the escalation is logged as an action, not only Slacked.
- `lessons_recall.py` takes an explicit corpus (`--corpus`, `KIPI_LESSONS_DIR`),
  prints which corpus it read on every search, and `--both` runs the kipi and
  consulting corpora when both exist. The same query from two branches yields
  identical results or an explicit corpus line. `improve_ground.py` already
  reads `KIPI_LESSONS_CORPORA`; this is the same seam.
- The two lessons-daily installers use two labels; the skeleton gains a plist
  template for its job and a test that the two labels differ.
- `trigger-inventory.py` lists every registered trigger (launchd plists, hooks,
  settings entries, CI) and every stage that claims to run, diffs them, prints
  the scope it excluded (`.claude/worktrees/`, `.wt-*`, with counts), and
  surfaces the three known dead stages; a planted dead stage inside a worktree
  copy is NOT counted.
- A promotion from consulting to the skeleton leaves a receipt (what moved, who
  decided, the scrub result); the hub-bar scrub refuses a planted client name;
  the lessons guard in `kipi-push-upstream.sh` becomes conditional on a promotion
  receipt instead of absolute, and stays fail-closed for any file without one.
- A scheduled drift reporter says what consulting has that the skeleton lacks,
  delivered via `slack_founder.deliver`, and stops arriving when its trigger is
  removed.
- The eight consulting-only lessons are accounted for: promoted through the
  receipt path or voided with a reason, never left where they are.
- `feedback_fleet_homogeneity` survives: a promoted capability exists in ONE
  canonical place and fans out.

## Non-goals

- Any git or branch operation from an issue in this PRD. The skeleton's branch
  state (the fan-out's immediate blocker) and the eventual merge are Sana's call
  (plan Phase 3 routing note). 3a is a dispatch to Sana carrying the two abort
  reasons and the six dated failures; it is filed as a spillover item owned by
  sana at PRD approval, never executed here.
- Changing what the down-rail fans down. Moving client content anywhere.
- Two canonical sources. Bidirectional means two authoring sites with one
  canonical destination; a capability is PROMOTED, it never lives in two places.
- Cleaning up the worktrees. An audit that only works on a tidy repo is not an
  audit (plan CAP-2); the inventory defines and prints its own scope instead.
- Running `kipi push` live inside an issue. The live proof waits on Sana's
  branch decision (plan CAP-1) and is recorded as pending evidence, not faked.
- Editing anything under `~/projects/consulting`. The consulting installer's
  label collision is fixed on the skeleton side (the template and the test);
  the consulting-side rename is a captured item for that lane.

## Proposed approach

One issue per accepted finding, in this order: streak escalation (3b), recall
names its corpus (3d), label collision, trigger inventory (4d), promotion
receipt (4a/4b, option (ii) explicit promotion, decided by the founder), drift
reporter (4c). Each issue is red-first, mutation-proven, Codex-reviewed, the
same discipline Phase 2 ran.

**Streak escalation.** `lessons-daily.sh` keeps a counter in
`q-system/output/lessons-propagation-streak.json`; on failure it increments,
on success it resets; at `STREAK_ESCALATE` (3) and above the Slack line and the
log line carry `streak N`, and the run appends one row to
`q-system/output/lessons-propagation-escalations.jsonl` (the logged action).

**Recall names its corpus.** `lessons_recall.py` gains `--corpus PATH` and the
`KIPI_LESSONS_DIR` env, prints `corpus: <path> (<n> lessons)` before hits, and
`--both` searches this corpus plus `KIPI_LESSONS_CORPORA` entries when they
exist, tagging every hit with its corpus.

**Label collision.** `q-system/.q-system/scripts/com.kipi.lessons-daily.plist`
template (Weekday 1 06:00, `__KIPI_REPO__` shape) and a test asserting no other
template or installer in the skeleton claims the same label; the consulting
installer's rename is captured for that lane.

**Trigger inventory.** `trigger-inventory.py` reads plist templates and
installed plists, `.claude/settings.json` hooks, plugin `hooks.json` files and
`.github/workflows/`; lists stages from a declared registry
(`q-system/.q-system/stages.json`, seeded with the scripts every trigger names
plus the three known dead stages); diffs; prints excluded-scope counts.

**Promotion receipt.** `kipi promote <path>` (a new `kipi-promote.sh` at repo
root per the instance-automation rule): scrub (refuse on a client name from
the consulting registry and on the tripwire terms), copy into the skeleton,
append `q-system/output/promotions.jsonl` {path, from, decided_by, scrub}. The
lessons guard in `kipi-push-upstream.sh` consults that receipt file: a
divergent lesson WITH a receipt passes, one without refuses.

**Drift reporter.** `lessons-drift-report.py` + `com.kipi.lessons-drift.plist`
(Monday 06:45): lists lessons and scripts present in a registered hub instance
and absent from the skeleton, delivers via `slack_founder.deliver`.

## Alternatives considered

- **Skeleton-only lesson authoring (3c option i).** Rejected by founder direction
  2026-09-01: consulting authors general capabilities because that is where the
  work happens; the up-rail is the fix, not a ban.
- **Path convention as the definition of "general" (4b option i).** Rejected as
  the decision procedure, kept as the default for anything already under
  `q-system/`: it fails whenever a general capability is built inside
  `q-consult/`.
- **Usage-derived generality (4b option iii).** Correct in principle,
  unmeasurable today.
- **A louder alarm for the propagation failure.** Rejected: six correct alarms
  produced no action; the fix is a logged automated action and a distinct
  streak line, not volume.

## Scenarios

- **Monday 06:00, fan-out fails again.** The streak file reads 6; the job logs
  `propagate FAILED (streak 7)`, Slacks that line, and appends one escalation
  row, not the same line a seventh time.
- **Recall from a feature branch.** `lessons_recall.py search "x" --both` prints
  `corpus: /path/kipi (161) + /path/consulting (154)` above the hits.
- **Promotion.** `kipi promote q-consult/pipeline/foo.py` scrubs (refuses on a
  client name), copies into the skeleton, writes a receipt row, and the next
  `kipi update` fans it to 25 instances.
- **Drift report.** Monday 06:45 the reporter posts "consulting has 8 lessons
  the skeleton lacks: ..." via `slack_founder.deliver`; remove the plist and the
  message stops.

## Resolved decisions

- **3c is option (ii), explicit upward collect.** Founder-directed 2026-09-01.
- **4b is option (ii), explicit promotion with a receipt**, with (i) as the
  default for anything already under `q-system/`. Decided in the plan.
- **3a is a Sana dispatch, not an issue.** Git is Sana's.
- **This PRD runs on the same worktree and branch as Phase 2**
  (`~/projects/kipi-wt-prd-mbl`, `prd/morning-brief-learns`).

## Risks and rollback

- The lessons guard becoming conditional is the one change that weakens a
  fail-closed check; it stays fail-closed on any file without a promotion
  receipt, and a test plants a divergent lesson with no receipt and asserts
  refusal.
- The drift reporter and the trigger inventory are read-only; rollback is
  removing the plist.
- The promotion path writes into the skeleton tree; every promotion is a
  receipt row plus a commit on a branch Sana owns.
- Both new plists are templates; installing them from this worktree would bake
  the worktree path in (the Phase 2 lesson), so installation is a landing step.

## Open questions

- Whether the eight consulting-only lessons are all general. The promotion
  receipt path answers it one file at a time; the first pass is Sana's.

## Persona Review

### Skeptic

Q1: What is the strongest argument against doing this?
A1: That the fan-out's real blocker is a branch decision no script can make.
True, and named as a non-goal: every issue here works on the rails around that
decision (the streak, the corpus, the receipts, the inventory) so that when
Sana makes it, the next failure is visible and the next promotion is recorded.

Q2: What is the smallest experiment that would disprove the thesis?
A2: Run `trigger-inventory.py` once. If it does not surface the three known
dead stages, the class fix is not reading what it claims to and the PRD's
Phase 4 premise falls.

Q3: What is the cheapest non-build alternative?
A3: Check out main and let the fan-out run. That fixes one night and records
nothing; the streak counter and the promotion receipt are what turn the next
five-week silence into a line someone reads.

## Issues

```json
[
  {
    "id": "lr-propagation-streak-escalation",
    "title": "lessons-daily.sh counts consecutive propagation failures and escalates on the Nth with the streak length",
    "finding_id": "TBD-after-review",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/lessons-daily.sh",
      "q-system/.q-system/tests/test_lessons_daily_streak.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_lessons_daily_streak.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "kipi-update.sh"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_lessons_daily_streak.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_lessons_daily_streak.py -k streak",
    "acceptance": "RED first: the propagation step is injectable (KIPI_PROPAGATE_CMD) so a test forces N failures without kipi-update.sh; a streak file under KIPI_STREAK_FILE increments on failure and resets on success; at streak 3 the log and notify lines differ from the streak-1 line and carry the number; one escalation row is appended per escalating run to an escalations ledger (KIPI_ESCALATIONS_FILE), none below the threshold. slack-notify.sh remains the alert sink for this job (it files Sana's ticket) and is invoked with the streak line; slack_founder is not used here."
  },
  {
    "id": "lr-recall-names-its-corpus",
    "title": "lessons_recall.py takes an explicit corpus, prints which it read, and --both spans kipi and consulting",
    "finding_id": "TBD-after-review",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/lessons_recall.py",
      "q-system/.q-system/tests/test_lessons_recall_corpus.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_lessons_recall_corpus.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_lessons_recall_corpus.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_lessons_recall_corpus.py -k 'names or both'",
    "acceptance": "RED first: search prints 'corpus: <path> (<n>)' before its hits; --corpus and KIPI_LESSONS_DIR override the default; --both adds every KIPI_LESSONS_CORPORA entry that exists, reports one that is missing, and tags each hit with its corpus; the same query against two tmp corpora with different contents yields different hits AND the corpus line says which. Existing search/similar/duplicates/stats behaviour and exit codes unchanged (their existing callers keep working: a test greps the tree for callers and runs one)."
  },
  {
    "id": "lr-lessons-label-collision",
    "title": "The skeleton's lessons-daily job gets a plist template and a test that no other template or installer claims its label",
    "finding_id": "TBD-after-review",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/com.kipi.lessons-daily.plist",
      "q-system/.q-system/tests/test_lessons_daily_label.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_lessons_daily_label.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_lessons_daily_label.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_lessons_daily_label.py -k unique",
    "acceptance": "RED first: a com.kipi.lessons-daily.plist template exists with __KIPI_REPO__/__HOME__/__USER__, Weekday 1 06:00, no /Users/ literal; a test derives every Label from every com.kipi.*.plist template and every install-*.sh in the skeleton and asserts each label is claimed exactly once. The consulting installer's rename is captured as a spillover item for that lane, not edited here."
  },
  {
    "id": "lr-trigger-inventory",
    "title": "trigger-inventory.py diffs registered triggers against declared stages with an explicit, printed scope",
    "finding_id": "TBD-after-review",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/trigger-inventory.py",
      "q-system/.q-system/stages.json",
      "q-system/.q-system/tests/test_trigger_inventory.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_trigger_inventory.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_trigger_inventory.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_trigger_inventory.py -k 'known_dead or worktree_copy'",
    "acceptance": "RED first: against a tmp repo fixture the inventory lists triggers from plist templates, installed plists (a directory the test provides), settings.json hooks, plugin hooks.json and workflow files; lists stages from stages.json; prints the diff and the excluded-scope counts (.claude/worktrees/, .wt-*). It surfaces the three known dead stages when run on this repo with KIPI_INSTALLED_PLISTS pointed at an empty dir (route-overrides-to-learn.py is now triggered by weekly-improve.sh, so the test plants the pre-fix state); a fake dead stage planted inside a worktree copy is NOT counted. Live run on this repo recorded at closeout."
  },
  {
    "id": "lr-promotion-receipt",
    "title": "kipi promote: scrub, copy into the skeleton, write a receipt; the lessons guard honours receipts and stays fail-closed without one",
    "finding_id": "TBD-after-review",
    "priority": "p1",
    "allowed_files": [
      "kipi-promote.sh",
      "kipi-push-upstream.sh",
      "kipi",
      "q-system/.q-system/tests/test_promotion_receipt.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_promotion_receipt.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "kipi-update.sh"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py -k 'client_name_refused or no_receipt_refused'",
    "acceptance": "RED first against tmp copies of an instance and a skeleton (never the live trees): kipi-promote.sh refuses a file containing a planted client name (read from a scrub list the test provides via KIPI_SCRUB_TERMS) or a tripwire term; on success it copies the file into the skeleton path and appends one receipt row {path, from_instance, decided_by, scrub, at}; the lessons guard in kipi-push-upstream.sh, given KIPI_PROMOTIONS_FILE, passes a divergent lesson WITH a receipt and refuses one WITHOUT (fail-closed unchanged for everything else); `kipi promote` is registered in the CLI. The eight consulting-only lessons are the first candidates and are listed in the closeout as promoted or voided-with-reason; the live promotion waits on Sana's branch decision and is recorded as pending, not faked."
  },
  {
    "id": "lr-drift-reporter",
    "title": "A scheduled drift reporter says what a hub instance has that the skeleton lacks, and stops when its trigger is removed",
    "finding_id": "TBD-after-review",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/lessons-drift-report.py",
      "q-system/.q-system/scripts/com.kipi.lessons-drift.plist",
      "q-system/.q-system/tests/test_lessons_drift_report.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_lessons_drift_report.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "q-system/.q-system/scripts/slack-notify.sh"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_lessons_drift_report.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_lessons_drift_report.py -k 'drift or no_trigger'",
    "acceptance": "RED first against two tmp trees: the report lists lessons (and scripts under q-system/.q-system/scripts/) present in the hub and absent from the skeleton, says 'no drift' when equal, says COULD NOT READ when a tree is unreadable, delivers via slack_founder.deliver (refused under pytest, asserted), and never references slack-notify.sh (source test). The plist template runs it Monday 06:45 with the placeholder shape. The 'stops when the trigger is removed' half is a launchd fact proven at landing (install, kickstart, bootout, observe silence); a test proves the script writes nothing and sends nothing when invoked with --dry-run."
  }
]
```
