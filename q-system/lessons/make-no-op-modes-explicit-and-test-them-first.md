---
id: make-no-op-modes-explicit-and-test-them-first
kind: pattern
title: Make No-Op Modes Explicit and Test Them First
date: 2026-10-31
---

## The pattern

A dry-run / verify-only / no-op mode is a safety feature, and it has to be built like one. Three rules make it hold.

### 1. Branch, don't parameterize to zero

Do not implement "do nothing" by setting a count, range, or list to empty and letting the loop body never execute. Loop and range constructs vary across shells, utility versions, and operating systems; some treat a degenerate range as a single iteration rather than none. Any mode whose safety depends on an empty collection staying empty is one platform difference away from doing real work.

Instead:

- Put an explicit early return or guarded branch at the top of the dangerous section, so a reader can point at the line that says "nothing happens here."
- Keep the no-op decision in one place, not spread across whatever the iteration happens to produce.
- Have the safe mode print what it *would* do, from the same data the real path consumes. Silence is indistinguishable from a skipped guard.

Rule of thumb: if you cannot grep for the condition that blocks the side effect, the side effect is not blocked.

### 2. Never let a script grant itself the privilege its guard withholds

When a system gates dangerous operations behind an environment variable, a confirmation flag, a role, or a token, the contract is that a *human-controlled* context supplies it. The moment a committed script sets that value in its own body, the gate is gone for every caller of that script — including automated agents, CI jobs, and scheduled runs that were never meant to clear it.

Practices that hold:

- Treat bypass credentials and override flags as inputs only. A script may read them and refuse to proceed; it must never assign them.
- If a script genuinely needs elevated behavior, make the caller pass it explicitly, so the privilege appears at the invocation site where a reviewer or a policy hook can see it.
- Assume any guard that works by pattern-matching command text is defeatable: by a wrapper script, a command prefix, an alias, an indirection through an interpreter. If you have been bitten by one evasion of a text-matching guard, inventory the other shapes of the same evasion rather than patching the single instance.
- Prefer guards that inspect the operation at the point of effect (the API call, the write, the push) over guards that inspect the string a human typed.

### 3. Prove the safe mode is safe before pointing it at anything shared

A new no-op mode is not shipped until someone has watched it fail to do the thing. Name the observable that would change if the mode were broken, then assert it is unchanged:

- Spin up a throwaway copy of the target — a scratch checkout, a disposable database, an isolated namespace.
- Capture state before (revision, row count, checksum, mtimes).
- Run the safe mode.
- Assert the state is byte-identical **and** that no marker of the real operation appears in the logs. Check both; a side effect can land without a log line, and a log line can appear without a side effect.
- Make this a committed negative test, not a one-time manual check, so later refactors of the loop or the guard trip it.

The failure mode to avoid: the first execution of a safety mode happening against live shared state, with other work in flight that the run can silently discard.

## Review checklist

For any flag that claims to suppress side effects:

- [ ] Is there an explicit branch, not an empty-collection accident?
- [ ] Does the behavior survive a different shell / OS / utility version?
- [ ] Does the script assign any override or bypass value it should only read?
- [ ] Can the dangerous path be reached by an automated caller that the guard was supposed to stop?
- [ ] Is there a negative test, run against disposable state, asserting nothing changed?
- [ ] Does the safe mode emit a preview, so an empty run is distinguishable from a skipped guard?
