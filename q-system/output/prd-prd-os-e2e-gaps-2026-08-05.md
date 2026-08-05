---
status: draft
---

# PRD: prd-os end-to-end gaps found by adversarial execution

**Date:** 2026-08-05
**Author:** Claude (Opus 5), from the founder's standing adversarial-tester prompt
**Status:** draft
**Priority:** P1 (high)
**Linear:** TBD

---

## 1. Problem

prd-os reviews PRDs and reviews diffs. Nothing in it ever **executes the shipped
system as a new user in a clean repo**. Five defects were found in under an hour
by doing exactly that, against `origin/main` at plugin version `0.16.6` — after
thirteen merged PRs, six Codex review rounds, a 17-finding adversarial pass, and
a 17-mutation harness.

Four of the five are the same shape: **a promise recorded in prose with no code
behind it.** That shape is structurally invisible to every gate prd-os owns,
because every gate reads a diff or a spec, and a missing implementation appears
in neither.

- **Evidence:** reproducer at `scratchpad/adv1/{run.sh,run2.sh}`, transcripts at
  `result.txt` / `result2.txt`. Method: `git archive origin/main plugins/prd-os`
  into a tmpdir, `git init` a throwaway repo, drive the documented lifecycle,
  record exit codes. Zero trust: each step assumed broken until a command proved
  otherwise.
- **Impact:** the system's own documentation is the least trustworthy artifact in
  it, and two stated non-negotiables have no enforcement at all.
- **Root cause:** prd-os has no execution-level verification layer. `kipi check`
  and `pytest plugins/prd-os/tests/` both run against the repo's own tree with
  its own fixtures; neither installs the plugin into a virgin repo and drives it.

## 2. Scope

### In Scope

Five confirmed defects (Section 3) plus the missing verification layer that
would have caught four of them.

### Out of Scope

- Redesigning the review process. The finder here is a new check, not a
  replacement for Codex review.
- The judgment compiler's calibration loop (ASK-363 owns it; zero prospective
  cases is expected, not a defect).
- Automated mutation testing and cross-model refutation. Both are real gaps
  named in the external research read, and both are their own PRD.

### Non-Goals

- Claiming the five below are the complete set. One hour of probing is not an
  audit; the point of Change 6 is that the check recurs.

## 3. Changes

### Change 1 (major): `/prd-os-init` does not do two of the three things it claims

- **Promised, three places:**
  `skills/prd-os/SKILL.md:26` — "scaffold `.prd-os/` and register hooks".
  `skills/prd-os/SKILL.md:36` — "The bootstrap command adds the state directory
  to `.gitignore`."
  `README.md:94` — "adds the runtime state dir to `.gitignore`, and registers
  hooks in `.claude/settings.json` idempotently with a backup".
- **Actual:** `scripts/prd_os_init.py` writes `.prd-os/config.json` and nothing
  else. `grep -rn gitignore` over the plugin returns only prose and one test
  regex; no writer exists. No hook registration exists.
- **Executed proof:** after `prd_os_init.py` in a fresh repo,
  `git check-ignore -v .claude/state/active-prd.json` returns nothing (not
  ignored) and `git status --short` lists `?? .claude/`.
- **Consequence:** the SKILL.md non-negotiable "Runtime state is never
  committed" has no blocker. Any repo bootstrapped by prd-os can commit
  `active-prd.json`, which carries in-progress session state.
- **Fix:** make `prd_os_init.py` write the `.gitignore` entry idempotently, or
  delete both claims. Whichever is chosen, `commands/prd-os-init.md` is already
  honest (it claims only `config.json`) and becomes the reference wording.

### Change 2 (major): archive succeeds while the standing gate is RED

- **Promised:** `.claude/rules/no-orphan-findings.md` — "`gates run` fails while
  any item is open (the enforcement of last resort)" and the ledger "cannot be
  forgotten".
- **Actual:** `cmd_archive` runs `_archive_coverage_gate` (accepted-finding
  receipt coverage) and `_manifest_status_gate`. It does not consult spillover.
- **Executed proof:** with `sp-0b8645ad` open, `prd_runner.py gates run` exits 1
  `GATE RED: spillover`; `prd_runner.py archive` exits 0 and stamps
  `status: archived` in the same repo, same moment.
- **What actually holds the line today:** two lines of prose in
  `commands/prd-archive.md` telling the model to run `spillover list` and
  `gates run` before declaring done. That is prompt-only enforcement, which
  `q-system/CLAUDE.md` core rule 3 forbids and the
  `prompt-only-enforcement-guard.py` hook blocks when written as a claim.
- **Fix:** call the spillover gate inside `cmd_archive` as a blocking check,
  matching how `_archive_coverage_gate` already blocks. A `--force` escape needs
  a recorded reason if one is wanted at all.

### Change 3 (major): the "portable core" writes a kipi-specific tree into any repo

- **Promised:** `skills/prd-os/SKILL.md` "Portable core vs repo-local split" —
  plugin is portable, repo-local state is confined to `.prd-os/` and
  `.claude/state/`.
- **Actual:** `_propose_skeptic_antipatterns_best_effort` (called on every
  successful archive) writes to `q-system/output/skeptic-proposals/`.
- **Executed proof:** a throwaway repo containing only `README.md` ended the run
  with `q-system/output/skeptic-proposals/` created on disk.
- **Consequence:** prd-os is not portable as documented. Any non-kipi repo that
  archives a PRD grows a `q-system/` tree it never asked for.
- **Fix:** route the proposal under `.prd-os/`, or resolve the path from config
  with a default inside `.prd-os/` and no creation outside it.

### Change 4 (minor): unconditional `prd-` prefix double-prefixes

- **Executed proof:** `prd_runner.py new prd-advtest` created
  `prd-prd-advtest-2026-08-05`.
- **Consequence:** cosmetic, plus an id-contract trap — the id that
  `findings_writer.py` requires is not the slug the author typed, so a new agent
  that reuses its own slug gets "PRD spec not found". Observed in this run.
- **Fix:** skip the prefix when the slug already carries it.

### Change 5 (major): the skill tells every model the plugin does not exist

- **Actual, on `origin/main` at 0.16.6:** `skills/prd-os/SKILL.md` still reads
  "Scaffold only at plugin version `0.1.0`", "The plugin is not yet wired", and
  instructs the model to tell the founder that `/prd-start` and every `/prd-*`
  command "does not exist yet". It lists `/prd-revise` (never shipped), omits
  four commands that did, teaches a disposition enum (`must-fix | optional |
  deferred | rejected-with-reason`) that `findings_writer.DISPOSITIONS` rejects,
  and points issue execution at `.claude/commands/issue-*.md`, a deleted
  directory.
- **Status:** fixed on branch `worktree-judgment-compiler` (commit `b3a0b7e9`,
  bumps 0.12.0 -> 0.12.1). **That branch is 13 commits behind main and main is
  at 0.16.6, so the fix must be re-applied on top of current main.** Until then
  the defect is live across 22 governed instances.

### Change 6: the check that would have caught Changes 1-4

- **What:** a test that installs the plugin into a fresh `git init` repo from a
  clean export, drives the documented lifecycle end to end, and asserts on exit
  codes and on-disk effects.
- **Why:** every existing check reads the repo's own tree. Four of five defects
  above are absences, and an absence is invisible to a diff reviewer, to
  `pytest` fixtures that presume the repo layout, and to mutation testing (which
  can only break checks that exist — the lesson already recorded on ASK-363).
- **Assertions it must carry, each derived from a defect above:** after init, no
  file exists outside `.prd-os/` unless config says so (catches 1 and 3); with
  an open spillover item, `archive` exits non-zero (catches 2); `new <slug>` and
  the id every other script accepts are the same string (catches 4).
- **Where:** `plugins/prd-os/tests/test_virgin_repo_lifecycle.py`, registered in
  `q-system/.q-system/capability-manifest.json`.

## 4. Files Modified

| File | Change Type |
|------|------------|
| `plugins/prd-os/scripts/prd_os_init.py` | Edit (Change 1) |
| `plugins/prd-os/scripts/prd_runner.py` | Edit (Changes 2, 3, 4) |
| `plugins/prd-os/skills/prd-os/SKILL.md` | Edit (Changes 1, 5) |
| `plugins/prd-os/README.md` | Edit (Change 1) |
| `plugins/prd-os/tests/test_virgin_repo_lifecycle.py` | Add (Change 6) |
| `q-system/.q-system/capability-manifest.json` | Edit (Change 6) |

## 5. Test Cases

Test-first. Each row was already observed RED by execution against 0.16.6; the
transcripts in `scratchpad/adv1/result2.txt` are the red run.

| # | Scenario | Pass criteria |
|---|----------|---------------|
| T-1 | init in a fresh repo, then `git check-ignore .claude/state/active-prd.json` | ignored, or the claim is deleted from SKILL.md + README |
| T-2 | archive with one open spillover item | exits non-zero, names the item |
| T-3 | full lifecycle in a repo containing only `README.md` | no directory created outside `.prd-os/`, `.claude/state/` |
| T-4 | `new prd-foo` | id is `prd-foo-<date>`, and that id is accepted by `findings_writer.py add` |
| T-5 | grep SKILL.md for "not yet wired" / "Scaffold only" / `prd-revise` / `must-fix` | no match |

Negative-fire checks (must NOT fire): archive with zero spillover items still
succeeds; init on an already-initialized repo stays idempotent and non-destructive.

## 6. Rollback Plan

| Change | Rollback |
|--------|----------|
| 1, 3, 4 | revert the script edit; behavior returns to current main |
| 2 | revert; archive stops consulting spillover (current behavior) |
| 5 | revert the doc edit |
| 6 | delete the test file and its manifest row |

## 7. Open Questions

| Question | Owner | Resolution |
|----------|-------|------------|
| Change 2: should archive hard-block on open spillover, or block with a recorded `--force` reason? Hard-block is stricter but archive is load-bearing. | Assaf | open; recommendation is hard-block, since `gates run` is already the documented last resort |
| Change 1: implement the `.gitignore` write, or delete the claim? | Assaf | open; recommendation is implement, because the non-negotiable it backs is real |
| Does Change 5's fix get re-applied on main as its own PR, or folded into this PRD's work? | Assaf | open |

## 8. Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Defects found by virgin-repo execution | 5 (manual, one hour) | 0 on a repeat run, with the check automated |
| Promised behaviors with no implementation | 2 confirmed (gitignore, hook registration) | 0 |
| Enforcement claims backed only by command prose | 1 confirmed (spillover at archive) | 0 |
| Directories created outside the documented split | 1 (`q-system/`) | 0 |
