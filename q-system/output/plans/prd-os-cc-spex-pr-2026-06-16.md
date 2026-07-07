# PR design: closeout gate for cc-spex (rhuss/cc-sdd)

Date: 2026-06-16
Mission: `oss-contribution-mission-2026-06-16.md` (PR into existing project)
Target: rhuss/cc-sdd (a.k.a. cc-spex), Apache-2.0, Python+bash, spec-kit extensions

## The thesis (why this PR belongs)

cc-spex already produces review findings and already STATES the rule, but only as
a prompt the agent can skip:
- `spex-gates/.../review-code.md:369`: "DO NOT proceed with deviations unresolved.
  ... Only 100% compliance proceeds to verification."
- `spex-gates/.../verify.md`: "Claiming work is complete without verification is
  dishonesty, not efficiency. Evidence before claims, always."
- `spex-deep-review/.../run.md:545`: flow state advances "even if findings remain."
- `review-plan.md:183`: "If 'Skip': Proceed without changes. Note that blocking
  issues remain unresolved." (skip is allowed)

So the gate is advisory. In autonomous mode (`ask: smart|never`) the verify/stamp
commands are told to "complete the verification and return" with no deterministic
check. This is exactly receipts-not-prompts: convert their own stated principle
into an enforced gate.

## The contribution (one mechanism, their conventions)

A deterministic closeout gate. NOT a port of prd-os. One script + one wiring line.

`review-findings.md` (written by spex-deep-review at `specs/<feature>/`) has a
summary table:
```
| Severity  | Found | Fixed | Remaining |
| Critical  | N     | N     | N         |
| Important | N     | N     | N         |
```
Their own GATE PASS rule: "If Critical + Important = 0: GATE PASS." The script
reads the Remaining column for Critical+Important and exits nonzero when > 0.

## Files the PR touches (small, reviewable)

1. `spex/scripts/spex-closeout-gate.sh` (NEW) — the deterministic check. Mirrors
   the bash+jq style of the existing `spex-flow-state.sh`.
2. `spex/extensions/spex-gates/commands/speckit.spex-gates.verify.md` — add a
   "Step 0: closeout gate" that runs the script first and refuses on nonzero.
   (verify is their "Final Completion Gate"; stamp delegates to it.)
3. A test under their `tests/` convention (fixture: review-findings.md with
   Remaining>0 must block; with 0 must pass).
4. README / extension docs: one line noting the enforced closeout gate.

## Gate behavior (acceptance-friendly defaults)

- No `review-findings.md` present => PASS (exit 0). Does not force deep review;
  only gates when recorded findings exist. (Lower-friction for maintainer.)
- Unparseable table => PASS with stderr warning, unless `SPEX_CLOSEOUT_STRICT=1`.
  Never a false block. (prd-os fail-closed is available behind the env flag.)
- Critical+Important Remaining > 0 => BLOCK (exit 1) with the counts and a
  pointer to resolve or re-run review.

## Acceptance criteria (done = green, not "looks right")

- [ ] `bash spex/scripts/spex-closeout-gate.sh` exits 1 on a fixture with
      Remaining Critical/Important > 0, prints the counts
- [ ] exits 0 on a fixture with all Remaining = 0
- [ ] exits 0 (with warning) when no review-findings.md exists
- [ ] their existing test suite stays green (`make test` or their runner)
- [ ] the new test passes under their convention

## Landing strategy (mission = a MERGED PR, not just an opened one)

1. ISSUE FIRST. Open a short issue: "Enforce the existing 'do not proceed with
   unresolved findings' rule deterministically." Get maintainer buy-in before the
   PR. Cold feature PRs merge less often.
2. PR only after a thumbs-up (or if the maintainer says "just send it").
3. Branch on a fork. Keep the diff tiny and framed as enforcing THEIR principle.

## Blockers / handoff

- `gh` auth token is INVALID (`gh auth status` failed). Fork/push/PR/issue all
  need working gh. `gh auth login` is interactive => founder action. Async
  unblock: `gh auth login`.
- All build + test happens in the local clone at /tmp/prd-os-targets/cc-sdd.
  Nothing touches GitHub until founder go + gh auth.
