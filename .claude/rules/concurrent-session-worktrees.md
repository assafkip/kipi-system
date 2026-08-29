---
description: Two or more Claude Code sessions active in one repo each get their own git worktree, because sharing the default checkout lets one session move another's HEAD and sweep its files into the wrong commit.
paths:
  - "**/scripts/**"
  - "**/hooks/**"
  - "**/*.sh"
---

# Concurrent sessions each get their own worktree (ADVISORY, not enforced)

Read the heading exactly as written. **Nothing in this repo can enforce this**,
and the file says so up front rather than at the bottom, because this repo has
been burned by rules claiming ENFORCED while naming no executable.

Paths-scoped on purpose. An earlier draft of this file used `paths: "**/*"`,
which is always-on, and the `instruction-budget-audit.py` ratchet refused the
commit outright (512 -> 576 lines against a 300 target). A rule that does not
have to be always-on must not be. These globs are the surfaces where branch,
worktree and session work actually happens.

Session launching happens in the harness, outside this repo's code. No hook fires
before a session picks its working directory, so no script here can observe two
sessions sharing one checkout, let alone refuse it. Per `skill-hook-pairing.md`'s
decision rule this is the judgment half: it lives in the instruction, and if it
drifts, no gate will say so.

| Piece | Status |
|---|---|
| The convention below | ADVISORY. Read by a person or an agent, checked by nothing |
| A hook that detects two sessions in one checkout | DOES NOT EXIST and cannot, at this layer |
| `git worktree` itself | Real, and the only mechanical part here |

## The rule

When two or more Claude Code sessions are likely to be active in this repo at the
same time, each session works from its **own** `git worktree`, never the shared
default checkout.

```bash
# From the repo root, one per session:
git worktree add ../kipi-wt-<session-name> -b <branch-name> origin/main

# When the session's work is merged and the tree is clean:
git worktree remove ../kipi-wt-<session-name>
git worktree list          # confirm it is gone
```

Branch off the ref you actually mean. `origin/main` is the default; if the work
builds on another session's unmerged branch, name that branch instead and say so,
because a worktree cut from the wrong base is the first incident below.

## The two incidents this comes from (2026-08-16)

Both happened in one day, between this session and a concurrent `social-voice`
session sharing one working directory.

1. **A branch built on the wrong ancestor.** Two sessions took turns checking out
   branches in the same tree. A branch created while the other session's checkout
   was live inherited that state as its base, so it carried commits nobody
   intended it to carry, and the diff read as work it had not done.

2. **An unattended auto-commit landing a stale-state revert.** A Stop-hook
   auto-commit swept the working tree while the other session had it in an
   intermediate state. The commit captured the other session's half-applied
   files, which read afterward as a deliberate revert of work that was in fact
   still in progress.

Neither is a merge conflict, and that is the point: git never complained. Both
sessions were doing legal operations on one tree, and the damage was to history
rather than to files, which is where it is expensive to see and expensive to undo.

## Why a worktree rather than "coordinate better"

A worktree gives each session its own HEAD, index, and working files against one
shared object store. That makes the failure mode structurally impossible instead
of merely discouraged: one session cannot move another's HEAD because they do not
share one. Coordination is a prompt-level fix for a state-level problem, and
prompt-level fixes fail on the first tired night.

Cheap, and the tell that you needed it is always retrospective.

## When this does not apply

- A single session in the repo. One checkout is correct; a worktree is overhead.
- Read-only work (reviews, audits, greps) that never checks out a branch or writes.
- Sessions in genuinely different repos. This is about one repo, many sessions.

## Cross-references

`skill-hook-pairing.md` (why the judgment half stays interpretive and gets no
hook) · `wiring-check.md` (load-path proof: a worktree is also how you keep one
session's edits from being read as another's) · `linear-first.md` (a branch that
carries the wrong base still has to name its issue).
