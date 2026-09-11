---
id: a-guard-that-reads-command-text-cannot-see-a-computed-path
kind: pattern
title: A guard that reads command text cannot see a computed path
date: 2026-08-29
---

## The failure shape

A PreToolUse guard protects a directory by parsing the command it is about to run
and refusing when a protected path appears in the text. It is cheap, it is
preventive, and it is blind in one specific direction: a path that does not exist
in the command text at parse time.

That direction is not exotic. It is the normal shape of a bulk edit:

```
for f in $(grep -rl PATTERN "$ROOT"); do <rewrite $f>; done
find . -name '*.py' -exec sed -i '' 's/a/b/' {} +
xargs < paths.txt
```

The paths live in a subshell's output, a variable, or a file. The parser sees
`$(grep ...)` and a loop body. It cannot know where either will point.

## What makes it worse than a plain gap

The blindness is asymmetric in exactly the wrong direction, and this is the part
worth remembering:

- The **careless wide rewrite** passes, because it computes its targets.
- The **targeted repair** is refused, because naming one file means writing the
  protected path literally.

Measured 2026-08-29 against `claude-path-write-guard` (ASK-282). A loop over
`grep -rl` output rewrote 198 files across 16 agent worktrees plus 11 more in a
parity tree, all inside the protected directory, with no block. The revert, which
named that directory as an argument, was refused. So was a later READ-ONLY status
sweep, because the pipeline fed such a path into `xargs`. The founder had to run
the repair by hand.

A guard whose easiest path to comply is "compute the path instead of writing it"
teaches the wrong habit, and the agent does not even have to be trying: writing
a codemod as a loop over search results is the obvious way to write one.

## How to build so this cannot hide

**1. Enforce at the write, not at the parse.** The only spelling-independent
answer is one that sees the actual filesystem operation: a PostToolUse check
reading the tool's real touched paths, or OS-level protection on the directory.
Text matching cannot resolve a subshell, and no amount of pattern work will
change that, because the information is not present yet.

**2. If it must stay preventive, say what it cannot see.** A guard that blocks
literal paths and silently permits computed ones should print that limit when it
fires, so the person it stops knows the coverage is partial rather than assuming
they hit the boundary of what is possible.

**3. Never treat "the guard did not fire" as "the write was safe."** Absence of a
block from a text-matching guard is evidence about the command's spelling and
nothing else.

## The general rule

**A preventive check can only see what is present at the moment it runs.** When
the thing you care about is produced later, the check is not weak, it is
structurally unable to see it, and the fix is a different layer rather than a
better pattern. This is the same family as the wider scar the autonomy rules
already record about hook patches: each round of patterns catches the shapes
already used and the next surface is found by accident.

## Cross-references

- `a-check-must-be-able-to-fail-for-the-reason-you-care-abou` — the mirror on
  the detection side.
- `a-gate-that-cannot-run-must-not-pass` — a guard that cannot observe the thing
  it guards is a special case of the same refusal.
- Full write-up with the reproducer and two candidate fix shapes:
  `q-system/output/finding-path-write-guard-runtime-paths-2026-08-29.md`,
  captured as spillover `sp-6694feba`.
