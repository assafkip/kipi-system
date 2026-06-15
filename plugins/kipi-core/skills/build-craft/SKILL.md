---
name: build-craft
description: "Engineering discipline distilled from a forensic read of one model's work. Use when building a feature, fixing a bug, writing tests, hardening a data path, or running any task that spans multiple files, sources, or sessions. Two layers: how to RUN the task (stage it, verify each stage with a check that can fail, write done-criteria) and how to WRITE the code (recon before edit, verify against a copy with a negative self-test, single-writer chokepoints, scar-anchored why-comments). Ships a paired hook that deterministically blocks a test from touching live data, the one habit a machine can enforce."
---

# Build-Craft

Coding and task discipline, distilled from reading thousands of edits by one
capable model and grading them against an independent review. It is additive: it
does not replace what your model already does well, it adds the habits that strong
engineers have and most code generation skips.

Most of it is judgment the skill teaches. One slice is enforced by a hook, because
a rule a model can talk itself out of is a suggestion, not a gate. The skill
teaches; the hook makes the one checkable habit non-optional.

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
   that executes it. Someone reading only your intent lines should be able to
   reconstruct the plan. It keeps you from drifting mid-burst.

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
   session. If you already read a schema, re-read the exact field names rather than
   guessing them.

2. **Verify against a copy, with a negative self-test.** A passing gate is not
   trusted until it has been seen to fail. Run the reproducer against a copy of the
   live resource, never the live one. Then corrupt a valid input and prove the
   check FAILS on the violation, so a green result is not a rubber stamp.

3. **Single-writer chokepoint, guarded by a grep-the-tree test.** Route every
   mutation of a shared resource through one helper, and write a test that greps
   the tree to prove no caller bypasses it. Migrate existing call-sites one small,
   independently revertible edit at a time, not one bulk rewrite.

4. **Why-comments anchored to a named scar.** Comments encode the constraint and
   the specific past bug that motivates it, not a restatement of the code. These
   survive refactors because they encode an invariant.

---

## Consistency rules

Habits that are easy to do somewhere and forget elsewhere. Make them non-optional:

- **Test isolation.** A test uses a temp copy, a tempfile, or `:memory:`, never a
  real data path. (This is the slice the paired hook enforces.)
- **Declare and pin every new dependency** the moment you import it, and keep a
  test that proves the manifest covers every third-party import.
- **Specify degenerate cases before implementing**: empty, single-element,
  disconnected, non-converging. Each gets defined behavior, not an implicit crash.
- **Validate persisted external input.** Never store arbitrary user or model JSON
  that, if malformed, can permanently break a render or load path.
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
`scripts/build-craft-lint.py`, wired in `hooks/hooks.json` as a PostToolUse hook.
Everything else is judgment and lives here. See `EXAMPLE.md` for a worked
before/after, and `references/checklist.md` for the copy-paste pre-done gate.
