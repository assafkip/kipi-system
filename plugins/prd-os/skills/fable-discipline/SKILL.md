---
name: fable-discipline
description: "Engineering discipline distilled from a forensic read of one model's work. Use when building a feature, fixing a bug, writing tests, hardening a data path, or running any task that spans multiple files, sources, or sessions. Two layers: how to RUN the task (stage it, verify each stage with a check that can fail, write done-criteria) and how to WRITE the code (recon before edit, verify against a copy with a negative self-test, single-writer chokepoints, scar-anchored why-comments). Ships a paired hook that deterministically blocks a test from touching live data, the one habit a machine can enforce."
---

# Fable-Discipline

Coding and task discipline, distilled from reading thousands of edits by one
capable model and grading them against an independent review. It is additive: it
does not replace what your model already does well, it adds the habits that strong
engineers have and most code generation skips.

Most of it is judgment the skill teaches. One slice is enforced by a hook, because
a rule a model can talk itself out of is a suggestion, not a gate. The skill
teaches; the hook makes the one checkable habit non-optional.

<!-- kipi-only:start -->
## Position: the execution-discipline layer of prd-os

This skill is not a sibling system to prd-os; it is prd-os's execution-discipline
layer (merged 2026-07-04, see the plugin CHANGELOG). Two load paths, one skill:

- **PRD work:** `/issue-start` loads this skill before the first edit of every
  DSSE issue. The issue's receipts (verified, reviewed, findings_triaged) are the
  task-level half of the same contract this skill states per-edit.
- **Non-PRD work:** the quick-plan fast path and the fable-discipline auto-invoke
  rule load it for any coding task bigger than a one-line change.

The public standalone export (github.com/assafkip/fable-discipline) mirrors this
copy; `scripts/export-fable-mirror.sh --check` is the drift blocker.
<!-- kipi-only:end -->

## When NOT to use this

One-line changes, typo fixes, a task with one obvious approach that fits in a
single pass. Staging a trivial task buries the answer under ceremony. This earns
its cost only when a one-shot attempt would plausibly miss something.

---

## Layer 1: running the task

How to move through complex work without shipping a confident wrong answer.

1. **Stage before you act.** Write the stage plan first. Number the stages, name
   the one checkable artifact each produces. If a stage produces nothing
   checkable, merge it into the next. The map is living, not a contract; update it
   when what you learn invalidates it.

2. **Verify each stage with a check that can fail.** A test that runs, a file that
   provably exists in the right shape, a source actually read, an output diffed
   against the spec. "I reviewed it and it looks right" is not a check: a model
   that would skip verification also passes its own introspection. If a stage has
   no failable check, say so and mark its output unverified so the gap is visible.

3. **Say, then batch.** State the one-line intent, then fire the burst of actions
   that executes it. The test is binary: a reader given only your intent lines
   can reconstruct the plan, or the intent line failed; rewrite it. It keeps
   you from drifting mid-burst.

4. **Done is written, not felt.** Define done-criteria up front. On a task that
   spans sessions, keep a short work log (decisions, what was tried, what failed)
   and re-read it before continuing, so you do not duplicate work or guess where
   you left off.

5. **Ground before you diagnose.** Confirm a perceived error actually reproduces
   before you act on it. Read where the data comes from before you trust what it
   represents. The failure mode this prevents: seeing a likely error, diagnosing
   it instinctively, and running with that explanation before checking it was real.

---

## Layer 2: writing the code

1. **Recon before edit. Read reality, do not assume it.** Grep the real schema and
   call-sites before changing anything. Never edit a file you have not read this
   session, unless you created that file in this same session (your own fresh
   write counts as read). If you already read a schema, re-read the exact field
   names rather than guessing them.

2. **Verify against a copy, with a negative self-test.** A passing gate is not
   trusted until it has been seen to fail. Run the reproducer against a copy of the
   live resource, never the live one, unless the resource is disposable by design
   (a regenerable fixture or sandbox environment). Then corrupt a valid input and
   prove the check FAILS on the violation, so a green result is not a rubber stamp.

   **A mutation result is THREE claims, and usually only one gets checked.** "The
   mutant was KILLED" is meaningless until "the mutant was APPLIED" and "the check
   was GREEN first" are both proven. An unapplied mutant and a well-defended one
   are identical bytes on the terminal, and so are a killed mutant and a command
   that was already red. Every mutation run therefore:
   - matches its anchor **exactly once** before writing, and proves the bytes on
     disk moved (digest, not length: a length-preserving mutant is legitimate);
   - exits non-zero as a **FAILED EXPERIMENT** on an anchor miss or an ambiguous
     anchor, and never falls through to the run. Override: re-derive the anchor
     from the file as it is now and re-run once it matches exactly one site.
     Loosening the anchor to make it match is not the hatch, it is the scar;
   - pins `PYTHONDONTWRITEBYTECODE=1` AND a bytecode-cache path outside the source
     tree. The first stops the run LEAVING a cache; only the second stops it
     READING a stale one, and the stale read is what measures the unmutated module;
   - starts from a **green baseline**, measured per experiment against the
     unmutated file rather than trusted once at the top of a table. A mutation run
     against an already-red check kills every mutant trivially and prints a
     perfect score;
   - holds the subject **one run at a time**. Two concurrent runs each read the
     other's mutant as "the original" and each restore it, so the mutant stays on
     disk while both report a clean tree.

   Scar 2026-09-20 (rca-injection-boundary, PR #386): five bad instruments across
   six review rounds by two independent sessions, every one failing in the
   reassuring direction. A stale `__pycache__` made mutants read KILLED; an anchor
   that no longer matched printed a clean 248 green, which is exactly what a
   defended site looks like. Both produced a wrong DIAGNOSIS, not a wrong number.
<!-- kipi-only:start -->
   In this fleet that protocol is a script, not a habit:
   `python3 plugins/prd-os/scripts/mutate.py --file F --anchor A --replacement R -- <check>`
   (exit 0 KILLED, 1 SURVIVED, 2 FAILED EXPERIMENT; always restores and verifies
   the restore). Its own decision points are mutation-proven by
   `plugins/prd-os/tests/mutants_of_mutate.py`.
<!-- kipi-only:end -->

3. **Single-writer chokepoint, guarded by a CENSUS TAKEN BY CODE.** Route every
   mutation of a shared resource through one helper, and make a gate enumerate the
   consumers from the source, never from your recollection of them. Migrate existing
   call-sites one small, independently revertible edit at a time, not one bulk
   rewrite. For a module that declares an exclusion predicate, that gate is
   `q-system/.q-system/scripts/consumer-parity-check.py`, a PostToolUse hook that
   walks the AST and reports every walker that skips the predicate. Retired 2026-08-03
   (ASK-315): this line used to say "write a test that greps the tree", which is
   prose naming no executable. Under it, a commit whose message read "one predicate
   for all three consumers" shipped with a fourth, and six instances of that shape
   landed in one file in one night. A habit is not a census.

4. **Why-comments anchored to a named scar.** Comments encode the constraint and
   the specific past bug that motivates it, not a restatement of the code. These
   survive refactors because they encode an invariant.

5. **Capture every out-of-scope finding; never just mention it.** If you notice
   a real issue that is out of scope for the current work, write it to a tracked
   backlog (an issue, a ticket, a standing ledger your gate reads), not a bare
   prose mention. A mention is a silent drop; a tracked item is one a gate can
   keep failing until it is resolved. The paired lint blocks deferral language
   written into code without such a capture. Override: capture first, then ack
   the captured line with `# spillover-skip`; there is no skip-first path.

6. **Build against the recurring gap classes.** If the change scales or touches
   sensitive data, walk the gap-class block in `references/checklist.md`: an
   in-memory cap is not a disk bound; a UI hide is not access control; a gate
   fails closed while a filter fails open; redact at the egress edge; a new flag
   must reach every reader; check-then-mutate needs one lock; single-source the
   version; a cross-cutting invariant needs a written scope + a self-enumerating
   guard. Check only the classes the change touches.

7. **Least-code bias.** Prefer the smallest change that solves it. Reach for
   delete-and-reuse before you write new code; the best fix is often a line
   removed, not a line added. When you catch yourself writing the third
   near-identical thing, stop and generalize the mechanism instead of adding a
   third copy.

---

## Consistency rules

Habits that are easy to do somewhere and forget elsewhere. Make them non-optional:

- **Test isolation.** A test uses a temp copy, a tempfile, or `:memory:`, never a
  real data path. (This is the slice the paired hook enforces.) Override: an
  audit test that must NAME a live path may assert on it (assertion lines are
  exempt); anything else carries `# fable-discipline-lint-skip` in that file
  with a one-line reason.
- **Declare and pin every new dependency** the moment you import it, and keep a
  test that proves the manifest covers every third-party import.
- **Specify degenerate cases before implementing**: empty, single-element,
  disconnected, non-converging. Each gets defined behavior, not an implicit crash.
- **Validate persisted external input.** Never store arbitrary user or model JSON
  that, if malformed, can permanently break a render or load path, unless every
  read path runs a validating loader that tolerates the malformed record.
- **Enumerate all call-sites when scoping a change.** Grep for every site the
  change must reach before declaring it done.

## Anti-patterns to drop

- Guessing a schema or API you already read. Re-read it.
- Acting on an unconfirmed diagnosis. Confirm the error is real first.
- Re-attempting the same failing command. Change the approach, do not retry it.
- Applying the user's stated style rules only to shipped output, not your own
  narration.

## Communication while building

Terse mid-task, then decompress at the seam into a short "ran, not assumed" block
listing what you ran and what passed. When a real choice exists, name the options,
mark your pick, give the tradeoff, end with one action.

## Enforcement

The deterministic slice (test isolation) is enforced by
`scripts/fable-discipline-lint.py`, wired in `hooks/hooks.json` as a PostToolUse hook.
Everything else is judgment and lives here. See `EXAMPLE.md` for a worked
before/after, and `references/checklist.md` for the copy-paste pre-done gate.
