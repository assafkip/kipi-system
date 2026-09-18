# Mutation sweep: finding tests that run, pass, and cannot fail

Engine: `q-system/.q-system/scripts/mutation-sweep.py`
Paired check: `q-system/.q-system/scripts/test/test-mutation-sweep.sh` (its own
negative control, declared in the capability manifest so it runs on every commit)

**Posture: ON-DEMAND and ADVISORY.** Never a blocking hook. It rewrites files in
the working tree while it runs, so it refuses a dirty tree. Same posture as
`skill-trigger-eval.py`: real cost, run when the question is asked.

## The class it detects

Not a missing check. A check that RUNS, PASSES, and is structurally blind to the
thing it exists to catch. Seventeen instances were measured in a single session
on 2026-08-29, which is what made it a class rather than a bug: a fleet harness
that only passed because it read the developer's real `$HOME`; a temp-file leak
test that counted files in `$TMPDIR` while the code it tested used `mktemp`,
which ignores `TMPDIR` on macOS; a race test whose fixture sent every thread
down the starvation path, so both of its assertions would have passed against a
guard with no locking at all.

## When to run it

- After building or hardening any gate, guard, or validator.
- When a test suite has been green for a long time and nobody can name the last
  time it went red.
- Before trusting a suite you inherited.
- Periodically over the whole declared population.

## Commands

```
# The harness's own negative control. Run this first, always.
python3 q-system/.q-system/scripts/mutation-sweep.py --self-test

# Declared tests that execute nothing at all (see below). Seconds, read-only.
python3 q-system/.q-system/scripts/mutation-sweep.py --zero-exec-scan

# Full sweep over the capability manifest. Serial by design; budget an hour.
python3 q-system/.q-system/scripts/mutation-sweep.py

# Bounded: one subsystem, or resume an interrupted run from the ledger.
python3 q-system/.q-system/scripts/mutation-sweep.py --only 'capability|leak'
python3 q-system/.q-system/scripts/mutation-sweep.py --resume
```

Ledger: `q-system/output/mutation-sweep/results.jsonl` (append-only, one row per
test, carries every exit code and sha so a verdict can be re-derived rather than
re-trusted). Summary: `summary.json`, `zero-exec.json`.

## Reading the verdicts

| Verdict | Meaning |
|---|---|
| `KILLED` | Disarming the subject turned the test red. The test can fail. |
| `SURVIVED` | The test exercises the subject, but the subject can no longer report failure and the test is still green. **A finding.** |
| `SURVIVED-ABSENT` | Green even with the subject file deleted. **Worse:** no version of the subject could turn this test red. |
| `UNMEASURED-no-dependency` | The tripwire did not turn the test red, so the candidate subject is not exercised. Usually a wrong guess, not a defect. |
| `EXCLUDED-baseline-red` | Already failing. Mutation cannot be measured on a red test. |
| `harness-error-*` | The harness could not produce a trustworthy verdict. Never counted as a pass or a finding. |

A `SURVIVED` row names the test and the subject. Localise it by disarming one
site at a time; the sweep deliberately disarms them all at once so the run
finishes.

## Why the whole-population sweep still misses things

Mutation testing can only see a test that EXECUTES the code. Three of the
seventeen instances are invisible to it by construction, so they get their own
checks:

- **Executes nothing.** The capability gate runs each python3 entry as
  `python3 <file>`. A pytest-style module has no entry point, so that command
  imports it, defines the test functions, and exits 0 — a pass, with nothing
  run. Such a test cannot notice a mutant, so it reads as `no-dependency`,
  which is indistinguishable from a bad guess. `--zero-exec-scan` is the check:
  static detection, one confirming run, cross-referenced against the paths CI
  actually hands to pytest, because that cross-reference is what separates
  "runs somewhere else" from "runs nowhere".
- **Environment-dependent green.** A test that passes only because of something
  in the developer's `HOME`, `TMPDIR`, or shell. Re-run the suite under a
  hermetic environment and diff the results against the normal run; any test
  that changes verdict was reading the environment, not the code.
- **Swallowed signal.** A guard's exit code discarded by `|| true`, `2>/dev/null`,
  or a captured stream. Grep, do not reason: a guard whose result is piped into
  a discard is not a guard.

## Guarding the harness itself

Two of the seventeen instances WERE mutation harnesses. One reported perfect
survival because a module-level import error killed all thirteen cases, each
recorded as "mutant did not write". One reported perfect survival because it ran
no tests at all. A survival report from a harness that ran nothing is the worst
possible output here, so every verdict is proved rather than assumed:

- the mutant is confirmed applied by sha256 re-read **from disk**, not by "the
  write returned";
- the mutant is confirmed syntactically valid (`ast.parse` / `bash -n`), so a
  broken mutant cannot score a free kill off any test that merely imports it;
- the baseline must be green, or the test is excluded rather than scored;
- after every restore the test is re-run and must be green again;
- each run gets a private `PYTHONPYCACHEPREFIX`, because a one-character mutant
  leaves the file the same size and the restore lands in the same second, so
  CPython will happily serve the mutant's cached bytecode for restored source;
- restore is a `cp` from a backup taken in-process, never a git checkout, and it
  is installed on SIGTERM/SIGINT/SIGHUP as well as `finally` — `finally` does not
  run on a signal, and the first long run of this sweep was killed mid-flight;
- `run_contained` is imported from a **copy** of `capability-gate.py`, so the
  sweep runs each test exactly the way the gate does and can never end up
  executing its own mutant as its runner.

`--self-test` asserts the harness still discriminates, on a fixture whose
answers are known by construction: a test that reads its subject's verdict is
`KILLED`, one that only checks "something was printed" is `SURVIVED-ABSENT`, one
that calls the subject and ignores the answer is `SURVIVED`, and one that names
no subject yields no candidate. It went red twice before it went green.

## Skeleton vs instance

The engine and its paired check live under `q-system/.q-system/`, so they ship
to every instance. That is deliberate: the manifest and the gate they operate on
are themselves synced there, and an instance carrying a
`capability-manifest.local.json` overlay has declared tests of its own that
nobody else can sweep. Nothing schedules it, and nothing blocks on it.
