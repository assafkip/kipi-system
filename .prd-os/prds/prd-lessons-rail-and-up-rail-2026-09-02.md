---
id: prd-lessons-rail-and-up-rail-2026-09-02
title: Lessons rail and up-rail (Phases 3 and 4 of the morning-brief overhaul)
status: approved
created_at: 2026-09-02T00:11:10Z
updated_at: 2026-09-02T00:25:25Z
owner: assaf
reviewers: []
findings_path: .prd-os/findings/prd-lessons-rail-and-up-rail-2026-09-02-findings.jsonl
codex_reviewed_at: 2026-09-02T00:15:42Z
reviewed_by: codex-adversarial
---

# Lessons rail and up-rail (Phases 3 and 4 of the morning-brief overhaul)

Source plan: `q-system/output/plans/morning-brief-overhaul-2026-08-30.md`, Phase 3
(the lessons rail is broken, three causes) and Phase 4 (kipi and consulting
update each other, founder-directed 2026-09-01, which resolves Phase 3's 3c in
favour of an explicit upward collect). Follows `prd-morning-brief-learns-2026-09-01`
(Phase 2), whose 15 issues shipped 2026-09-01 on branch `prd/morning-brief-learns`.

Revised 2026-09-02 after the Codex adversarial review (14 findings, all
accepted): the manifest went from six issues to fourteen, one per finding, and
two facts found while triaging changed two goals (see "Corrections" below).

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
- **A shared launchd label, shipped by the skeleton itself.**
  `q-system/.q-system/scripts/install-lessons-daily.sh` hardcodes
  `com.kipi.lessons-daily` and lives under the fan-out path, so every one of the
  25 instances carries an installer that, if run, rebinds the skeleton's job to
  that instance (`lessons-daily.sh` then shells `kipi-update.sh`, which only
  works in the skeleton). The consulting copy is this file. The skeleton has no
  plist template for its own job (installed by hand, Weekday 1 06:00).
- **Three stages found built, correct, and never running** in one session
  (`route-overrides-to-learn.py`, the propagation call, the untriggered upstream
  push). Three is a class, not three bugs.
- **Repo-wide audits count dead copies.** 27 directories under `.claude/worktrees/`
  plus `.wt-*` at the repo root each hold a full tree; one script name returned
  184 hits outside the real file (plan CAP-2).

## Goals

- After N consecutive propagation failures the job emits a DIFFERENT line
  carrying the streak length, the escalation is logged as an action, and the
  streak survives concurrent runs (atomic replace under one lock). A run that
  publishes nothing leaves the streak untouched: neither a reset nor a failure.
- The escalations ledger has a reader and a bound: `lessons_streak.py summary`
  is read by the escalated log line and by the drift reporter; the ledger keeps
  its last 200 rows.
- `lessons_recall.py` takes an explicit corpus (`--corpus` over
  `KIPI_LESSONS_DIR` over its file-relative default, in that precedence), prints
  which corpus it read on every search, and `--both` adds every existing
  `KIPI_LESSONS_CORPORA` entry, deduplicated by real path so a symlinked
  duplicate is searched once. `improve_ground.py` already reads
  `KIPI_LESSONS_CORPORA`; this is the same seam.
- The label collision is closed on the skeleton side, completely: the fanned-out
  installer refuses to run anywhere but the skeleton (registry self-detect, the
  method `instance-automation-guard` already uses), the skeleton gains a plist
  template for its job, and a test derives every label from every template and
  installer and asserts each is claimed once. No consulting-side change exists,
  because the consulting file IS the skeleton file.
- `trigger-inventory.py` derives its stage list from the system (every script
  under `q-system/.q-system/scripts/` and every repo-root `*.sh`), not from a
  hand list; an exemptions file names helpers that are libraries by design and a
  stale exemption is RED. A new, unregistered script is visible by construction.
  It prints the scope it excluded (`.claude/worktrees/`, `.wt-*`, with counts),
  surfaces the three known dead stages, and does not count a planted dead stage
  inside a worktree copy.
- A promotion from an instance to the skeleton is path-contained (real path
  inside `q-system/`, no symlink, no `..`, regular file), scrubbed against a
  production term source (registry codenames, the instance's `clients.json`
  names and slugs, the push tripwire terms), and leaves a two-phase receipt
  bound to the content hash. The lessons guard in `kipi-push-upstream.sh` passes
  a divergent lesson only when the skeleton's receipt file (read at
  `FETCH_HEAD`, never the instance working tree) carries a `done` row whose hash
  matches that blob; everything else stays fail-closed.
- The eight consulting-only lessons are LISTED with a status each (no receipt,
  pending, done, voided) by `kipi promote --candidates`, and the closeout
  records the exact command per file. The live promotion is Sana's (branch
  decision, plan CAP-1) and is recorded as pending, not faked.
- A scheduled drift reporter says what a declared hub instance has that the
  skeleton lacks, resolves both paths from `instance-registry.json` (the
  registry's `skeleton` entry must be the reporter's own root, else COULD NOT
  READ), delivers via `slack_founder.deliver` only when launched by its plist
  (an environment marker the plist sets), and has exactly one caller in the
  tree: that plist template.
- `feedback_fleet_homogeneity` survives: a promoted capability exists in ONE
  canonical place and fans out.

## Corrections found during triage (2026-09-02)

- The "consulting installer" in the original Problem was the skeleton's own
  `install-lessons-daily.sh`, fanned out to every instance. The fix is therefore
  whole on the skeleton side; the earlier "captured for the consulting lane"
  clause is withdrawn.
- `lessons_scrub.py` already exposes `codenames_from_registry(path)` (the
  distinctive instance names from `instance-registry.json`). The promotion scrub
  extends that roster instead of inventing a second term source.

## Non-goals

- Any git or branch operation from an issue in this PRD. The skeleton's branch
  state (the fan-out's immediate blocker) and the eventual merge are Sana's call
  (plan Phase 3 routing note). 3a is a dispatch to Sana carrying the two abort
  reasons and the six dated failures; it is filed as spillover item
  `sp-f09ac9e1` owned by sana, never executed here.
- Changing what the down-rail fans down. Moving client content anywhere.
- Two canonical sources. Bidirectional means two authoring sites with one
  canonical destination; a capability is PROMOTED, it never lives in two places.
- Cleaning up the worktrees. An audit that only works on a tidy repo is not an
  audit (plan CAP-2); the inventory defines and prints its own scope instead.
- Running `kipi push` or a live `kipi promote` inside an issue. The live proof
  waits on Sana's branch decision (plan CAP-1) and is recorded as pending
  evidence, not faked. Every promotion test runs against two tmp git trees.
- Editing anything under `~/projects/consulting`. Reading it (read-only, for the
  candidates list and the drift report) is in scope.

## Proposed approach

One issue per accepted finding, fourteen, in the order of the manifest. Each
issue is red-first, mutation-proven, Codex-reviewed, the same discipline Phase 2
ran. The order puts the streak first (the live defect), then recall and the
label, then the inventory, then the six promotion slices, then the reporter.

**Streak (issues 1 to 3).** A single-writer helper `lessons_streak.py` owns the
streak file and the escalations ledger: `bump --outcome fail|ok` reads,
changes and replaces the file atomically (write to a sibling temp file, rename)
under one `fcntl` lock file, `append-escalation` writes one row and truncates
the ledger to its last 200 rows, `summary` prints the current streak and the
escalation rows of the last 30 days. `lessons-daily.sh` calls `bump` only after
a real propagation attempt; the "nothing new" exit and the "nothing published"
branch touch neither file. At `STREAK_ESCALATE` (3) and above the notify and log
lines carry `streak N` and the count from `summary`.

**Recall names its corpus (issue 4).** `lessons_recall.py` gains `--corpus PATH`
and `KIPI_LESSONS_DIR`, prints `corpus: <path> (<n> lessons)` before hits, and
`--both` searches the primary corpus plus each existing `KIPI_LESSONS_CORPORA`
entry after resolving every path with `realpath` and dropping duplicates, tagging
each hit with its corpus. A missing entry is reported by name.

**Label collision (issue 5).** `install-lessons-daily.sh` reads
`instance-registry.json` beside its own repo root and refuses (exit 2, no plist
written) unless that root equals the registry's `skeleton` path;
`com.kipi.lessons-daily.plist` template (Weekday 1 06:00, `__KIPI_REPO__`
shape); a test derives every Label from every `com.kipi.*.plist` template and
every `install-*.sh` and asserts uniqueness, and runs the installer in a tmp
"instance" tree with a tmp HOME and asserts refusal.

**Trigger inventory (issue 6).** Candidates are derived, not listed: every
`*.py` and `*.sh` under `q-system/.q-system/scripts/` plus every repo-root
`*.sh`. Triggers are read from plist templates, an installed-plists directory,
`.claude/settings.json` hooks, plugin `hooks.json` files and
`.github/workflows/`; a candidate named in the text of a triggered script is
triggered transitively (closure). `q-system/.q-system/stages-exempt.json` names
library modules with a reason; an exemption whose file does not exist fails
the run. Dead = candidate outside the closure and not exempt.

**Promotion (issues 7 to 12).** `kipi-promote.sh` at repo root (instance
automation rule), registered as `kipi promote`, built in six slices:
containment first (issue 7: `realpath`, inside `q-system/`, no symlink in the
path, regular file, no `..`, no absolute input; destination is the same relative
path in the skeleton), then the scrub source (issue 8:
`lessons_scrub.is_clean` with `codenames_from_registry` plus `name` and `slug`
from the instance's `my-project/clients.json` located through the registry's
`instance_q_dir`, plus the tripwire terms single-sourced in
`q-system/.q-system/scripts/tripwire-terms.txt` which `kipi-push-upstream.sh`
also reads; a missing clients file refuses), then the receipt bound to the git
blob hash of the promoted content and the guard comparing that hash (issue 9),
then two-phase writing (issue 10: a `pending` row before the copy, a `done` row
after the copy re-hashes equal, both appended under the same lock; the guard
honours `done` only), then the receipt's home (issue 11:
`q-system/.q-system/promotions.jsonl` in the skeleton, tracked, fanned out
read-only; the guard reads it from `FETCH_HEAD` and ignores the instance
working tree; `KIPI_PROMOTIONS_FILE` is honoured only under pytest), then the
candidates listing (issue 12: `kipi promote --candidates [--instance NAME]`
prints every lesson present in the hub and divergent from the skeleton with its
receipt status; `--void PATH --reason` records a `voided` row, which the guard
still refuses to push, so the listed action for a voided file is a move to the
instance's own lessons dir).

**Drift reporter (issues 13 and 14).** `lessons-drift-report.py` resolves the
skeleton path from the registry's `skeleton` entry (must equal its own root) and
hubs from `q-system/.q-system/drift-hubs.json` (registry names; a name absent
from the registry renders COULD NOT READ), diffs lessons and scripts, appends
the streak `summary`, and delivers via `slack_founder.deliver` only when
`KIPI_TRIGGER=launchd` is present, which only the plist sets; without it the
script prints and sends nothing. A source test enumerates every caller of the
script in the tree and asserts the plist template is the only one.

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
- **Receipts in the instance working tree.** Rejected (finding-12): the guard
  runs in the instance, so an instance-local file would let the instance
  authorise its own push. The skeleton's tracked copy at `FETCH_HEAD` is the
  only source the guard reads.
- **A hand-maintained stage registry.** Rejected (finding-6): a stage nobody
  registered is exactly the stage the inventory exists to find.

## Scenarios

- **Monday 06:00, fan-out fails again.** The streak file reads 6; the job logs
  `propagate FAILED (streak 7, 5 escalations in 30d)`, Slacks that line, and
  appends one escalation row, not the same line a seventh time.
- **Two runs overlap.** A manual `kipi lessons-run` and the scheduled run both
  bump; the file reads 2 higher, not 1, and is never half-written.
- **Recall from a feature branch.** `lessons_recall.py search "x" --both` prints
  `corpus: /path/kipi (161) + /path/consulting (154)` above the hits; with
  `KIPI_LESSONS_CORPORA` naming the kipi corpus through a symlink it still reads
  each once.
- **Someone runs the installer in an instance.** It prints that the job is
  skeleton-only and exits 2; `~/Library/LaunchAgents` is unchanged.
- **Promotion.** `kipi promote q-system/lessons/foo.md` in consulting refuses on
  a client name from `clients.json`, else writes a `pending` row, copies, re-hashes,
  writes `done`; after Sana commits and the receipt fans out, `kipi push` passes
  that one lesson and still refuses any other divergence.
- **Drift report.** Monday 06:45 the reporter posts "consulting has 8 lessons
  the skeleton lacks: ..." plus the streak summary; run by hand it prints the
  same and sends nothing; remove the plist and nothing is sent at all.

## Resolved decisions

- **3c is option (ii), explicit upward collect.** Founder-directed 2026-09-01.
- **4b is option (ii), explicit promotion with a receipt**, with (i) as the
  default for anything already under `q-system/`. Decided in the plan.
- **3a is a Sana dispatch, not an issue.** Git is Sana's. Filed as `sp-f09ac9e1`.
- **This PRD runs on the same worktree and branch as Phase 2**
  (`~/projects/kipi-wt-prd-mbl`, `prd/morning-brief-learns`).
- **Receipts bind to the git blob hash** (`git hash-object`), the same value the
  guard already reads from `ls-tree`, so no second hashing scheme exists.

## Risks and rollback

- The lessons guard becoming conditional is the one change that weakens a
  fail-closed check; it stays fail-closed on any file without a `done` receipt
  whose hash matches, reads receipts only from the skeleton at `FETCH_HEAD`, and
  a test plants a divergent lesson with a stale receipt and asserts refusal.
- The drift reporter and the trigger inventory are read-only; rollback is
  removing the plist.
- The promotion path writes into the skeleton tree; every promotion is a
  receipt row plus a commit on a branch Sana owns.
- All three new plists (lessons-daily template, lessons-drift, and the existing
  weekly-improve from Phase 2) are templates; installing them from this
  worktree would bake the worktree path in (the Phase 2 lesson), so
  installation is a landing step.
- The installer refusal could lock the skeleton out if the registry's
  `skeleton` path drifts; the test runs the installer in the real skeleton root
  with a tmp HOME and asserts it writes the plist there.

## Open questions

- Whether the eight consulting-only lessons are all general. `kipi promote
  --candidates` lists them with a status; the decision per file is Sana's, and
  the closeout records the command per file, not the outcome.

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
    "title": "lessons_streak.py owns the streak file atomically under one lock; lessons-daily.sh escalates on the Nth failure with the streak length",
    "finding_id": "finding-9",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/lessons_streak.py",
      "q-system/.q-system/scripts/lessons-daily.sh",
      "q-system/.q-system/tests/test_lessons_daily_streak.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_lessons_daily_streak.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "kipi-update.sh"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_lessons_daily_streak.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_lessons_daily_streak.py -k 'streak or concurrent'",
    "acceptance": "RED first: the propagation step is injectable (KIPI_PROPAGATE_CMD) so a test forces N failures without kipi-update.sh; lessons_streak.py bump reads, changes and replaces the streak file by temp-file rename under an fcntl lock (a sibling .lock file), so 20 concurrent bumps yield exactly 20 and a reader never sees a partial file; a corrupt or missing file counts from zero; at streak 3 the log and notify lines differ from the streak-1 line and carry the number; one escalation row is appended per escalating run, none below the threshold; success resets to 0 with a logged 'streak reset after N'. A source test proves lessons-daily.sh writes the streak file only through lessons_streak.py. slack-notify.sh remains the alert sink for this job."
  },
  {
    "id": "lr-streak-noop-semantics",
    "title": "A run that publishes nothing leaves the streak untouched; only a real propagation attempt bumps it",
    "finding_id": "finding-10",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/lessons_streak.py",
      "q-system/.q-system/scripts/lessons-daily.sh",
      "q-system/.q-system/tests/test_lessons_daily_streak.py"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "kipi-update.sh"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_lessons_daily_streak.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_lessons_daily_streak.py -k noop",
    "acceptance": "RED first: the sequence fail, fail, nothing-new, nothing-new, held-only, fail leaves the streak at 3 (the three quiet runs neither reset nor increment and write nothing); the 'nothing new' early exit and the 'no propagation (nothing published)' branch touch neither the streak file nor the ledger (asserted by mtime and absence); the script header states the rule in one sentence and a source test pins that sentence next to the branch."
  },
  {
    "id": "lr-escalations-ledger-reader",
    "title": "The escalations ledger gets a reader (summary) and a bound (last 200 rows)",
    "finding_id": "finding-8",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/lessons_streak.py",
      "q-system/.q-system/scripts/lessons-daily.sh",
      "q-system/.q-system/tests/test_lessons_daily_streak.py"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "kipi-update.sh"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_lessons_daily_streak.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_lessons_daily_streak.py -k 'summary or retention'",
    "acceptance": "RED first: lessons_streak.py summary prints the current streak and the escalation rows of the last 30 days as one line and as JSON; append-escalation truncates the ledger to its last 200 rows (250 appended, 200 remain, the newest kept); the escalated notify line includes 'N escalations in 30d' read from summary; a ledger with one malformed row still summarises the rest and names the bad line count. The drift reporter (issue 13) is the second reader."
  },
  {
    "id": "lr-recall-names-its-corpus",
    "title": "lessons_recall.py takes an explicit corpus with stated precedence, prints which it read, and --both dedups by real path",
    "finding_id": "finding-14",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/lessons_recall.py",
      "q-system/.q-system/tests/test_lessons_recall_corpus.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_lessons_recall_corpus.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_lessons_recall_corpus.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_lessons_recall_corpus.py -k 'names or both or dedup'",
    "acceptance": "RED first: precedence is --corpus, then KIPI_LESSONS_DIR, then the file-relative default, pinned by a test that sets all three and asserts the corpus line; search prints 'corpus: <path> (<n>)' before its hits; --both adds every KIPI_LESSONS_CORPORA entry that exists after realpath resolution, drops duplicates (a symlink to the primary corpus is searched once, counts and ranking unchanged), reports a missing entry by name, and tags each hit with its corpus; the same query against two tmp corpora with different contents yields different hits AND the corpus line says which. Existing search/similar/duplicates/stats behaviour and exit codes unchanged (a test greps the tree for callers and runs one)."
  },
  {
    "id": "lr-lessons-label-collision",
    "title": "The fanned-out lessons-daily installer refuses outside the skeleton; the skeleton gets its plist template and a label-uniqueness test",
    "finding_id": "finding-5",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/install-lessons-daily.sh",
      "q-system/.q-system/scripts/com.kipi.lessons-daily.plist",
      "q-system/.q-system/tests/test_lessons_daily_label.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_lessons_daily_label.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_lessons_daily_label.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_lessons_daily_label.py -k 'unique or refuses'",
    "acceptance": "RED first: install-lessons-daily.sh resolves its repo root, reads instance-registry.json there (or under the subtree prefix), and exits 2 without writing a plist unless the root equals the registry's skeleton path; run in a tmp tree with a fixture registry naming another skeleton and a tmp HOME, it refuses and HOME/Library/LaunchAgents stays empty; run in a tmp tree whose fixture registry names that tree as skeleton, it writes the plist under the tmp HOME. A com.kipi.lessons-daily.plist template exists with __KIPI_REPO__/__HOME__/__USER__, Weekday 1 06:00, no /Users/ literal. A test derives every Label from every com.kipi.*.plist template and every install-*.sh in the skeleton and asserts each label is claimed exactly once."
  },
  {
    "id": "lr-trigger-inventory",
    "title": "trigger-inventory.py derives stages from the tree, diffs them against registered triggers, and prints its excluded scope",
    "finding_id": "finding-6",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/trigger-inventory.py",
      "q-system/.q-system/stages-exempt.json",
      "q-system/.q-system/tests/test_trigger_inventory.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_trigger_inventory.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_trigger_inventory.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_trigger_inventory.py -k 'known_dead or worktree_copy or unregistered'",
    "acceptance": "RED first against a tmp repo fixture: candidates are every *.py and *.sh under q-system/.q-system/scripts/ plus repo-root *.sh, never a hand list; triggers come from plist templates, an installed-plists directory the test provides, settings.json hooks, plugin hooks.json and workflow files, closed transitively over scripts named inside triggered scripts; stages-exempt.json entries need a reason and an existing file (a stale exemption exits 2); a brand-new script dropped into the fixture with no trigger is surfaced without any registration; the diff and the excluded-scope counts (.claude/worktrees/, .wt-*) are printed; run on this repo with the installed-plists dir empty it surfaces the three known dead stages (the test plants the pre-fix state for route-overrides-to-learn.py); a fake dead stage planted inside a worktree copy is NOT counted. Live run on this repo recorded at closeout."
  },
  {
    "id": "lr-promote-path-containment",
    "title": "kipi promote exists, is registered in the CLI, and refuses any path that is not a regular file on a symlink-free real path inside q-system/",
    "finding_id": "finding-2",
    "priority": "p1",
    "allowed_files": [
      "kipi-promote.sh",
      "kipi",
      "q-system/.q-system/tests/test_promotion_receipt.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_promotion_receipt.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "kipi-update.sh"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py -k containment",
    "acceptance": "RED first against tmp copies of an instance and a skeleton (never the live trees; KIPI_PROMOTE_SKELETON and KIPI_PROMOTE_INSTANCE point at them): an absolute input, a path with '..', a symlink (the file or any parent), a directory, a device or fifo, and a path outside q-system/ (including one under the instance_q_dir) each exit 2 with no copy and no receipt; a plain relative q-system/ path copies to the same relative path in the skeleton, creating parents; the CLI registers `kipi promote` and `kipi help` names it. The scrub and the receipt are the next two slices; this slice copies only when KIPI_PROMOTE_UNSCRUBBED=1 under pytest, and refuses otherwise, so the containment slice can never ship as a working promoter without the scrub."
  },
  {
    "id": "lr-promote-scrub-source",
    "title": "The promotion scrub reads production term sources: registry codenames, the instance's clients.json names and slugs, and the single-sourced tripwire terms",
    "finding_id": "finding-3",
    "priority": "p1",
    "allowed_files": [
      "kipi-promote.sh",
      "kipi-push-upstream.sh",
      "q-system/.q-system/scripts/tripwire-terms.txt",
      "q-system/.q-system/scripts/lessons_scrub.py",
      "q-system/.q-system/tests/test_promotion_receipt.py"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "kipi-update.sh"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py -k 'client_name_refused or clients_file_missing'",
    "acceptance": "RED first: the scrub roster is lessons_scrub.codenames_from_registry(instance-registry.json) plus the name and slug of every record in the instance's my-project/clients.json (located through the registry's instance_q_dir for the instance being promoted from; a fixture clients.json with the producer's keys is used in tests) plus every line of q-system/.q-system/scripts/tripwire-terms.txt, which kipi-push-upstream.sh now reads for its pre-push grep instead of its inline list (a test asserts the inline list is gone and the file holds the same seven terms); a file carrying a planted client name or slug or tripwire term exits 2 with no copy and no receipt; a missing clients.json refuses (fail-closed) and says which path it looked for; KIPI_SCRUB_TERMS is removed from the design."
  },
  {
    "id": "lr-promote-receipt-hash-binding",
    "title": "A promotion receipt binds path, git blob hash, source instance and decider; the lessons guard passes a divergent lesson only on a matching done receipt",
    "finding_id": "finding-1",
    "priority": "p1",
    "allowed_files": [
      "kipi-promote.sh",
      "kipi-push-upstream.sh",
      "q-system/.q-system/tests/test_promotion_receipt.py"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "kipi-update.sh"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py -k 'stale_receipt_refused or no_receipt_refused'",
    "acceptance": "RED first against two tmp git repos (instance and skeleton, the skeleton reachable as FETCH_HEAD): a receipt row is {path, blob, from_instance, decided_by, scrub, status, at} where blob is git hash-object of the promoted content; the guard passes a divergent lesson whose instance blob equals a done receipt's blob for that path, refuses one whose content changed after the receipt (stale receipt), refuses one with no receipt, and is unchanged for deletions and for uncommitted lessons; decided_by defaults to the invoking user and can be set with --decided-by."
  },
  {
    "id": "lr-promote-two-phase-receipt",
    "title": "The receipt is written in two phases around the copy, under one lock, so a crash leaves a pending row and never a silent copy",
    "finding_id": "finding-11",
    "priority": "p1",
    "allowed_files": [
      "kipi-promote.sh",
      "kipi-push-upstream.sh",
      "q-system/.q-system/tests/test_promotion_receipt.py"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "kipi-update.sh"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py -k 'pending or crash or concurrent_promotions'",
    "acceptance": "RED first: a pending row is appended before the copy and a done row after the copied file re-hashes equal to the source, both under one flock on a sibling .lock of the receipt file; a copy that fails (destination made unwritable by the test) leaves exactly one pending row and no done row; the guard ignores pending rows; ten concurrent promotions of ten files leave twenty well-formed rows and ten copies."
  },
  {
    "id": "lr-promote-receipt-location",
    "title": "Receipts live in the skeleton at q-system/.q-system/promotions.jsonl and the guard reads them from FETCH_HEAD, never from the instance working tree",
    "finding_id": "finding-12",
    "priority": "p1",
    "allowed_files": [
      "kipi-promote.sh",
      "kipi-push-upstream.sh",
      "q-system/.q-system/promotions.jsonl",
      "q-system/.q-system/tests/test_promotion_receipt.py"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "kipi-update.sh"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py -k 'fetch_head or local_receipt_ignored'",
    "acceptance": "RED first: kipi-promote.sh appends to <skeleton>/q-system/.q-system/promotions.jsonl (an empty tracked file ships in this issue so the fan-out carries it); the guard reads the receipts with git show FETCH_HEAD:q-system/.q-system/promotions.jsonl and a receipt row present only in the instance's working tree or HEAD does not pass a divergent lesson; KIPI_PROMOTIONS_FILE is honoured only when PYTEST_CURRENT_TEST is set and refused with a message otherwise; kipi update's fan-out list is confirmed to carry the file (a test greps kipi-update.sh's include rules, no live update)."
  },
  {
    "id": "lr-promotion-candidates-status",
    "title": "kipi promote --candidates lists every divergent lesson in a hub instance with its receipt status; --void records a voided row",
    "finding_id": "finding-4",
    "priority": "p1",
    "allowed_files": [
      "kipi-promote.sh",
      "kipi-push-upstream.sh",
      "q-system/.q-system/tests/test_promotion_receipt.py"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "kipi-update.sh"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py -k 'candidates or voided'",
    "acceptance": "RED first: --candidates [--instance NAME] resolves the instance through the registry, lists each lessons/*.md present there and absent-or-divergent in the skeleton with status none, pending, done or voided and the exact next command per file; --void PATH --reason TEXT appends a voided row, and the guard still refuses to push a voided divergent lesson (the listed action is a move to the instance's own lessons dir); run read-only against the live consulting checkout at closeout, the eight lessons appear with status none and that output is the closeout evidence. No live promotion."
  },
  {
    "id": "lr-drift-reporter",
    "title": "A scheduled drift reporter resolves skeleton and hubs from the registry, says what a hub has that the skeleton lacks, and appends the streak summary",
    "finding_id": "finding-13",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/lessons-drift-report.py",
      "q-system/.q-system/scripts/com.kipi.lessons-drift.plist",
      "q-system/.q-system/drift-hubs.json",
      "q-system/.q-system/tests/test_lessons_drift_report.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_lessons_drift_report.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "q-system/.q-system/scripts/slack-notify.sh"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_lessons_drift_report.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_lessons_drift_report.py -k 'drift or could_not_read'",
    "acceptance": "RED first against two tmp trees and a fixture registry: the skeleton path is the registry's skeleton entry and must equal the reporter's own repo root, else COULD NOT READ (a worktree never reports as the skeleton); hubs are the registry names in drift-hubs.json, a name absent from the registry renders COULD NOT READ for that hub; the report lists lessons and scripts under q-system/.q-system/scripts/ present in the hub and absent from the skeleton, says 'no drift' when equal, appends lessons_streak.py summary, never references slack-notify.sh (source test), and delivers via slack_founder.deliver (refused under pytest, asserted). The plist template runs it Monday 06:45 with the placeholder shape and sets KIPI_TRIGGER=launchd in EnvironmentVariables."
  },
  {
    "id": "lr-drift-trigger-proof",
    "title": "Removing the trigger provably stops delivery: the reporter sends only under the plist's environment marker and has exactly one caller in the tree",
    "finding_id": "finding-7",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/lessons-drift-report.py",
      "q-system/.q-system/scripts/com.kipi.lessons-drift.plist",
      "q-system/.q-system/tests/test_lessons_drift_report.py"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "q-system/.q-system/scripts/slack-notify.sh"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_lessons_drift_report.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_lessons_drift_report.py -k 'no_trigger or single_caller'",
    "acceptance": "RED first: without KIPI_TRIGGER=launchd the reporter prints the report and calls deliver zero times (a fake deliver injected by the test counts calls); with it, deliver is called once; a source test enumerates every file in the tree (excluding .claude/worktrees/ and .wt-*) that names lessons-drift-report.py and asserts the set is exactly the plist template and the test itself, so a second caller or a removed template is RED; the 'stops when removed' launchd fact is still recorded at landing (install, kickstart, bootout, observe silence) as evidence, not as the proof."
  }
]
```
