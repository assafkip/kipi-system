# RCA: a fail-closed resolver made the grounding Stop hook call a healthy manifest unreadable

**Date:** 2026-08-22
**Trigger:** CI `validate` went red on `e469bddc` (run 32602044138), 11 failures in `test_grounding_manifest_health.py`
**Surface-fix commit:** pending
**Structural-fix commit:** pending

## What happened

A Codex review finding was fixed by making `evidence_ledger.instance_root()` refuse
to resolve a canonical root for an unregistered repository. The refusal was correct
for the hazard it targeted (an unattended run appending evidence against the wrong
tree) but was written as a blanket `if not registered: raise`. That is broader than
the hazard. It broke 11 tests and, more seriously, made `system_manifest.health()`
raise underneath the grounding Stop hook, which then reported a **healthy** manifest
as unreadable on every turn.

## Surface symptom

```
FAILED test_no_stdout_payload_when_the_manifest_is_healthy
AssertionError: emitted a payload on a healthy manifest:
'{"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext":
"GROUNDING GUARD WARNING: the subsystem-coverage check is NOT running because
the manifest is unreadable. system_manifest.health() raised ResolutionError..."}}'
```

and, for the other ten:

```
evidence_ledger.ResolutionError: /tmp/pytest-of-runner/pytest-9/test_.../repo:
not a registered instance and not the skeleton. Refusing to resolve a canonical
root by guessing.
```

## Surface root cause

`evidence_ledger.py`, the guard added immediately after `registered` is computed:

```python
if not registered:
    raise ResolutionError(...)
```

`system_manifest.manifest_path()` calls `instance_root(repo)` with the strict
default, and `health()` calls `manifest_path()`. A pytest `tmp_path` repository is
by construction neither a registered instance nor the skeleton, so every synthetic
repo raised.

type: code-defect

## Structural root cause

### Root cause #1 — the guard was written to the caller, not to the hazard

The reported hazard was specifically a **write**: evidence appended from a stray
clone against the wrong canonical tree. The guard was written as a property of the
repository (`not registered`) rather than of the operation (`is about to write`).
Read-only callers were swept in for free. `instance_root` already carried a
`strict` axis for exactly this distinction, and its own docstring advertised
`strict=False` "for callers that must degrade rather than refuse" — the design
anticipated the split, and the new guard sat above it instead of inside it.

type: implicit-contract

### Root cause #2 — blast radius was measured for one resolver and not its twin

Earlier the same session, a resolver change to `paths.py` was prototyped, measured
(4 cases fixed, 53 collateral tests broken), and reverted on the strength of that
number. The `evidence_ledger` resolver is the same class of change and received no
equivalent measurement; only its own suite (`test_evidence_ledger.py`, 21/21) was
run. Two changes of one class, one measured, one not. The discipline existed and
was applied inconsistently, which is worse than not having it, because the green
suite read as evidence of safety.

type: process

### Root cause #3 — the full gate was not run before pushing

CI's `validate` step runs `capability-gate.py`, which executes 179 declared tests
including `test_grounding_manifest_health.py`. Locally only the directly-related
suite was run. An earlier attempt to run the full gate in the background was
started with `nohup` from a tool call and died with its parent, and that death was
never noticed or retried, so the one check that would have caught this pre-push
silently produced nothing.

type: process

### Root cause #4 — health()'s never-raise contract was documented but not enforced

`health()`'s docstring states it "deliberately returns a status instead of raising"
because its caller is an unattended hook, and that absent must never be reported as
a problem. Nothing executable held that contract: no test asserted that `health()`
does not propagate an exception from its resolver. A prose promise on a function
whose whole value is not raising is a promise that can be broken by a change three
call-frames away.

type: missing-test

## Verification

Ran the failing suite before and after the narrowing fix:

```
before: 11 failed, 5 passed in 0.28s
after : 16 passed in 0.20s
```

Confirmed the original review finding is still fixed — the write path still refuses
an unregistered repo:

```
write path REFUSED (reviewer fix intact)
```

Confirmed the resolver's own suite still passes, including two new cases pinning the
narrow contract (`allow_unregistered` still refuses ambiguity; resolves a single tree):

```
23/23 passed
```

## Contributing factors

- The refusal's own error message advertised `strict=False` as the escape hatch, but
  `strict=False` restores the full legacy guess including `sorted()[0]` between two
  candidate domain dirs. The advertised hatch was wider than any caller wanted, so
  neither the blanket refusal nor the advertised alternative was the right shape.
- `test_grounding_manifest_health.py` lives under `q-system/.q-system/tests/`, not
  beside `evidence_ledger.py`, so nothing about editing the resolver pointed at it.
- A review was in flight against the branch while these pushes happened, so the
  reviewer refused with "head moved between two reads" and posted no status, costing
  a review round that would not have caught this anyway.

## Fixes shipped

- Surface fix: narrowed the guard to `if not registered and not allow_unregistered`,
  and had `system_manifest.manifest_path()` opt in as a read-only degrading caller —
  pending commit.
- Structural fix: added `allow_unregistered` as an explicit third axis on
  `instance_root` (write callers refuse, read-only callers degrade, ambiguity refuses
  for everyone) plus two cases pinning that contract so it cannot silently widen back
  to either extreme — pending commit.

## Action items

- [ ] Run the full `capability-gate.py` locally before every push that touches a shared resolver, and confirm it CONCLUDED rather than assuming a backgrounded run finished — owner: sana — type: process
- [ ] Add a test asserting `system_manifest.health()` never propagates an exception from its resolver, so its never-raise contract is executable rather than prose — owner: sana — type: test
- [ ] When a change lands in a shared resolver, enumerate its callers and run their suites, not only the resolver's own — owner: sana — type: process
- [ ] Review whether `strict=False` still has any legitimate caller now that `allow_unregistered` exists; if not, retire it so the ambiguous guess has no entry point — owner: sana — type: code
- [ ] Never start a long verification with `nohup` from a tool call without a monitor that reports its conclusion — owner: sana — type: process

## Lessons

- Write a guard to the hazard, not to the caller. "Unregistered repo" is a property
  of the repository; "about to append evidence" is the property that was actually
  dangerous, and only the second should have refused.
- A green suite for the module you edited is not a blast-radius measurement. The
  measurement is the callers' suites, and the gate that CI actually runs.
- Applying a discipline to one change and not to its twin is the failure mode to
  watch for. The prototype-measure-revert loop was used correctly on `paths.py` in
  the same session and simply not repeated here.
- A docstring promising "this never raises" needs a test, or it is a comment.
