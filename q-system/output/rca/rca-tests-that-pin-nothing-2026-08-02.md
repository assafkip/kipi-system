# RCA: nine green tests survived having the code they guard deleted

**Date:** 2026-08-02
**Trigger:** A Fable-model reviewer ran a mutation pass on PR #74's test suite instead of reading it, and reported that reverting both shipped fixes left the suite green.
**Surface-fix commit:** b6af3e0, 1e4c748 (kill-tests added)
**Structural-fix commit:** pending — see Action items

## What happened

PR #74 shipped with 9 passing tests written reproducer-first: each was observed
red before the fix and green after. That procedure was followed and the suite
still pinned almost nothing.

An adversarial reviewer gutted the implementation on copies and re-ran. Surviving
mutants — the suite stayed green with each of these applied:

- both round-1 fixes reverted (`_witness_rank` → plain sort; the engine
  generated-exclusion removed) — **the two fixes shipped with zero coverage**
- the `-m` and `spec_from_file_location` arms removed from `MODULE_REF_RE`
- both lookarounds removed from `filename_re`
- the generated prefix un-anchored (`startswith` → `contains`)
- `SURFACE_NAMES` dropped entirely
- `MD_INVOCATION_RE` reduced to a single arm — 5 of its 6 arms untested
- `_is_test_file` replaced with always-True

Only gutting `is_generated_surface` was killed by the suite.

Two related findings the same night. The prose-negative fixture — the test whose
job was proving a doc mention does not count as wiring — **passed only because its
sample sentence happened to avoid the leaky tokens**; the filter it guarded
matched ordinary English ("The source of the bug is engine_x.py"). And the first
version of the ASK-312 test asserted the helper and not the call site, so a revert
of the fix would have passed.

## Surface symptom

A green suite on a PR carrying a defect that marked 25 dead engines LIVE, and two
shipped fixes that could have been silently reverted at any later date without a
single test objecting.

## Surface root cause

Each test asserted the behaviour the author had just implemented, on a fixture the
author had just written, at the layer the author had just edited. Reproducer-first
guarantees the test fails before the fix; it guarantees nothing about whether the
test fails when the fix is later removed, and those are different properties.

## Structural root cause

type: missing-test

**Nothing measured whether a test could fail.** Red-before-green proves the test
responds to the original defect. It does not prove the test is bound to the code
that fixed it, and for a detector — a program whose output is a *distribution* over
a real corpus — the two come apart badly:

- The properties that matter are population statistics (25 engines flipped, 163 of
  785 witnesses miscited, 9.2% of LIVE verdicts resting on one regex arm). A
  tempdir fixture with four files exhibits none of them, so a fixture-based test
  can be green while the real behaviour is wrong.
- A regex with six alternatives needs six cases; one fixture exercises one arm and
  looks like coverage for all six.
- A fixture the author invents encodes the author's model of the bug. The
  prose-negative case is the clean example: it tested the sentence the author
  imagined, not the sentences the corpus contains.

The corrective was already known and written down. `reference-review-tooling-2026-07`
records "mutation-check every test that asserts a safety property" from three prior
occurrences, and `fable-discipline` requires a negative self-test. Both were in
context. Neither is executable, so neither ran.

## Verification

The mutation pass, re-run here against the pre-fix generator from `origin/main`:

```
new test vs PRE-fix generator   -> 5 of 8 fail   (the suite can detect the original defect)
new test vs fixed generator     -> 8/8 OK
```

After the kill-tests were added for the surviving mutants:

```
test-capability-map-wiring.py   18/18 OK   (was 9)
```

And on ASK-312, the same discipline applied deliberately rather than after the
fact — mutant validated as applied, parsing, and differing before trusting the
result:

```
mutant: VERDICT="$(resolve_verdict ...)" -> VERDICT="$DERIVED_VERDICT"
  mutant validated: applied and differing
  suite result: FAIL 2 of 16   (including the call-site wiring check)
```

## Contributing factors

- **The kill-tests immediately proved their worth.** One added because of the
  mutation table caught an over-tightening in a replacement regex within a minute
  of existing — a change that would have dropped every `./script` caller.
- **Two same-lab review rounds read the tests and passed them.** The gap was found
  by a reviewer on different weights that chose to run mutants rather than read.
- **The suite's own green was the reason nobody looked.** 9/9 with a documented
  red-before-green history is exactly the evidence that stops further inquiry.
- **`capability-gate: GREEN` also passed** throughout, so two independent green
  signals agreed and both were uninformative.

## Fixes shipped

- Kill-tests added for the surviving mutants (`b6af3e0`, `1e4c748`); suite 9 → 18.
- ASK-312's suite ships with a call-site wiring assertion and a documented
  mutation result (`5495a9b`), and pins the pre-fix line by name so a revert
  cannot pass silently.
- Fixtures for ASK-312 are the three real producer artifacts byte for byte, not
  reconstructions.

## Action items

- [ ] Build `mutation-check.py`: given a test and its target, apply a declared
      mutant set, assert each is *validated as applied, parsing, and differing*
      before trusting the result, and require at least one test to fail per
      mutant. Run it periodically rather than per-commit — it is expensive, and a
      per-commit cost gets it switched off. Owner: Sana.
- [ ] Require a declared mutant for every test registered in
      `capability-manifest.json` that guards a safety property, starting with the
      gate suites (`test-severity-floor`, `test-review-gate-no-fake-green`,
      `test-capability-map-wiring`). Owner: Sana.
- [ ] For any detector-shaped change, make an old-vs-new population diff across
      the five real instances a required pre-merge artifact. Both real defects in
      this PR came from that diff and neither came from a review round.
      Tracked as `sp-63a21b0e`. Owner: Sana.
- [ ] Add a call-site wiring assertion to every test that exercises a helper
      through the library rather than through its caller. A correct helper nobody
      invokes is the ASK-312 defect one layer up. Owner: Sana.

## Lessons

- Red-before-green and can-this-test-fail are different properties. The first is
  about the defect, the second is about the fix, and only the second survives the
  fix's author leaving.
- A fixture you invent tests your model of the bug. For a detector, the corpus is
  the fixture: run it against the real instances and diff the population.
- A regex with N alternatives has N cases. One passing fixture is coverage for one
  arm and camouflage for the rest.
- Two green signals that agree are one signal if nothing has established either
  can go red.
