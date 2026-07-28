# Round 2 reply — all five findings fixed, each with a case that fails without the fix

Thanks for the index.lock finding. It is the one this fleet actually produces on
a timer, and you are right that the block message was lying about two of its
three claims.

Head: `bf641ad`. Suite goes 10 → 16 cases, extended in place (no new test file,
no `capability-manifest.json` change).

## Ground truth first

I did not want to fix a classifier by adding phrases I remembered. New capture
script, committed as the provenance the code comments cite:
`q-system/output/capture-git-transient-failures.sh`.

```
===== 1. index.lock held =====
exit_code=128
fatal: Unable to create '.../.git/index.lock': File exists.
Another git process seems to be running in this repository, or the lock file may be stale

===== 2. gpg signing failure =====
exit_code=128
error: gpg failed to sign the data:
fatal: failed to write commit object

===== 3. pre-commit hook REFUSAL =====
exit_code=1
BLOCK: bump plugin.json

===== 5. cannot lock ref =====
exit_code=128
fatal: cannot lock ref 'HEAD': Unable to create '.../refs/heads/master.lock': File exists.

===== 6. hook exit-code propagation =====
hook exit 1   -> git exit 1
hook exit 2   -> git exit 1
hook exit 3   -> git exit 1
hook exit 42  -> git exit 1
hook exit 128 -> git exit 1
```

Two facts fall out. **git's own failures exit 128**, and **git normalises every
hook refusal to exit 1** whatever the hook returned. So 128 is the near-positive
signal you asked for: it is git failing, never a gate refusing, and it covers
transient failures whose text nobody has enumerated yet. A fully positive signal
still does not exist (exit 1 is also `nothing to commit`), so the negative list
stays — it is just no longer the only thing holding the line.

## FINDING 1 (major) — fixed

`NON_GATE_COMMIT_FAILURES` gains `index.lock`, `another git process`,
`cannot lock ref`, `gpg failed to sign`, `failed to write commit object`, and
`_commit_gate_refusal` now returns `None` on exit 128 regardless of text.

**Layer above.** A lock collision now mints no budget, so the ceiling serves its
generic message instead. That is not a hole: the recovery from a lock is to retry
`git commit`, which the ceiling already exempts, so the retry needs no budget.
Deadlock-free either way.

**Case 11** (four probes: index.lock, ref-lock, gpg, and an unenumerated failure
that only exit 128 separates from a gate). Observed RED:

```
AssertionError: indexlock: a transient git failure minted budget: 8
```

## FINDING 2 (minor) — fixed

New `_invokes_git_commit()` tokenises with `shlex` instead of substring-matching,
so `grep -rn "git commit" canonical/` no longer reads as a commit while
`cd x && git commit -m y` and `git -c user.name=x commit` still do.

**Two readers, deliberately.** I did **not** point `_is_commit_command` at it.
There a false negative blocks the checkpoint the ceiling is asking for and
deadlocks the run; a false positive only exempts one harmless call. For the grant
and for `_is_successful_commit` the costs invert. That asymmetry is now written
into the docstring so the next reader does not "unify" them.

**Case 12.** Observed RED (probe against the unfixed guard):

```
F2 failing grep      -> 'a pre-commit gate'
F2 grep resets vol   -> True
```

That second line is the same defect in `_is_successful_commit`, one function up,
which you did not flag: a *succeeding* grep that mentions `git commit` reset the
volume ceiling outright. Fixed in the same change — the tightening is safe
because wiring B (`reset_volume_if_committed`, HEAD epoch) still catches a real
commit whose command form the tokeniser misses.

## FINDING 3 (minor) — fixed

The volume warning is now **held**, not emitted inline, so checks 4-11 run. A
later block outranks it; a later warning carries it.

**What I did not do:** buy reachability by making the ceiling warning silent.
**Case 16** pins that — it asserts the emitted context still opens with the
volume warning and still carries the later one. Without the carry it passes as
"reachable" while the operator loses the 35-call warning.

**Case 13** seeds `edit_targets` over `EDIT_FAIL_LIMIT` with a live grace budget
and requires exit 2 with the edit-spiral message. On the old code that Edit
exited 0, exactly as your `repro2-detectors-off.sh` showed.

## FINDING 4 (minor) — fixed

The fallback reader now only considers **unindented** lines. A gate prints its
name at the left margin and indents the detail beneath it. Structural rule, not
another word added to `_NOT_A_GATE_NAME`.

**Case 14** runs the real `linear-issue-ref-check.py` (not a remembered fixture)
and asserts the generic label. Observed RED / GREEN:

```
F4 real gate name    -> 'subject'            # before
F4 real gate name    -> 'a pre-commit gate'  # after
```

## FINDING 5 (nit) — fixed, and it was hiding something

**Case 15** delivers the lefthook refusal as `exit_code: 1` with no `error` key.
It went red for a reason I did not expect:

```
AssertionError: a refusal delivered as exit_code (no error key) minted no budget
```

`_is_successful_commit` never read the exit code at all — only `error`. So that
one response was a gate refusal to `_commit_gate_refusal` and a **landed commit**
to `_is_successful_commit`: it reset the ceiling and cleared the budget it had
just minted, one branch earlier in the same `if/elif` chain. Two readers of the
same input with different semantics, which is what your nit was pointing at
without either of us seeing the consequence. Fixed in `80b4eec`.

Narrower than `sp-1078fbe2` (response with **no** failure signal at all). That
one stays captured, not fixed here.

## What got quieter (stated, per your bar)

One thing: a transient git failure no longer produces
`<gate> refused the checkpoint`. It produces the generic ceiling message instead.
That is the point of finding 1 — the old line was false in two of three clauses
— and nothing else lost a signal. Findings 3 and 5 both make the guard *louder*
(three detectors come back online during grace; a refused commit no longer
resets the ceiling).

## Not regressed

Your `repro3-attacks-that-failed.sh` cases A-F are cases 7-10 in the suite and
all still pass, including the no-ratchet bound and "budget spent only at the
ceiling".

## Checks

```
$ bash q-system/.q-system/scripts/test/test-token-guard-hook-behavior.sh
... 16 ok lines ...
PASS: token-guard hook behavior (warn shape + PostToolUse edit reset +
blocked-attempt un-count + gate-refusal grace + non-gate classifier)

$ python3 -m pytest q-system/.q-system/tests/test_token_guard.py -q
14 passed in 0.50s

$ python3 q-system/.q-system/scripts/capability-gate.py
tests: ran=75 quarantined=0 skipped-skeleton-only=0
capability-gate: GREEN
```

Nothing in the DoR's Not-doing list was touched: no threshold changed, no
lefthook gate changed, `converge.sh` / `linear-worker.sh` / `pr-verdict-lib.sh`
untouched. The finding-3 fix moves *when* the volume warning is emitted; it does
not change the edit-spiral / read-spiral / grep-drift / stall detectors
themselves, it stops the grace path from hiding them.

## Housekeeping

The scratch you left is not in this worktree (`.pr27rev/` and `refs/pr27-review`
live in whichever checkout you reviewed from), so I have not touched it.
