# RCA: PR #786 used all 3 review rounds and still could not merge, validate red on 9 review tests

**Date:** 2026-11-13
**Trigger:** iteration-speed.md rule 6. PR #786 reached the review cap (3 rounds: 00:50Z REQUEST CHANGES, 00:56Z APPROVE WITH NITS, 02:03Z APPROVE) with Skeleton Validation red on both runs (00:50Z run 43340273401, 01:57Z run 43348697308). ASK-4796.
**Surface-fix commit:** 66768b4d (lib-copy lists, consumer patches)
**Structural-fix commit:** 33dad1cc (the claude line back in pr-review-agent.sh; the consumer patches reverted). PR #795 replaces #786.

## What happened

PR #786 moved the reviewer's claude command line out of pr-review-agent.sh into a new sourced file, review-lean-lib.sh. The PR's own tests and the reviewer both passed it. Nine older review tests went red in CI. Auto-merge was armed but could never fire, and the review cap was used up by rounds that read the diff and not the CI result.

## Surface symptom

From run 43348697308:

- `FAIL: round 1 did not reach the stub (0 calls), so every check below is vacuous` (test-review-delta-round.sh, and the same shape in 5 more).
- `FAIL - the direct gh/curl block on the claude engine is gone` (test-review-blocked-verdict.sh).
- `AssertionError: "$FLEET_CLAUDE -p --model '$CLAUDE_MODEL'" not found` (test_model_routing.py).
- `FAIL - KNOWN_UNWRAPPED names pr-review-agent.sh (sp-3bcc9e16) but discovery no longer reaches it` (test-script-stable-under-self-edit.sh).

## Surface root cause

Line 202 of pr-review-agent.sh sources `$SCRIPT_DIR/review-lean-lib.sh`. Eight tests stage the reviewer into a scratch dir from a fixed file list that did not name the new lib. The `.` failed, with no `set -e` to stop it, so `review_claude_cmd` was undefined, `bash -c ""` ran nothing, and the stub saw 0 calls. Three more tests read the claude argv literal out of pr-review-agent.sh, where it no longer lives.

## Structural root cause

### Root cause #1
type: implicit-contract

"What the reviewer needs next to it in a scratch dir" is restated by hand in 9 test files. No test checks those lists against the `.` lines of pr-review-agent.sh, so adding a sourced lib breaks every list at once and only CI notices.

### Root cause #2
type: missing-test

At least five consumers find the reviewer's model call by reading pr-review-agent.sh: `bare_calls` (test_model_routing.py), `discover_drivers` (test-script-stable-under-self-edit.sh), the blocked-verdict grep, `voiceloop/call_sites.py` (test_model_call_sites.py) and test-subscription-only.sh. Moving the line into a lib as a printed string hid it from all of them. The first fix (66768b4d) patched three consumers one by one. Round 4 found two more: call_sites.py skips an assignment's value, so the reviewer left the metering census, and test-subscription-only.sh printed a pass over a file it no longer scanned. CI's per-diff test selection did not run test_model_call_sites.py, which is how this passed `validate` (ASK-4801).

### Root cause #3
type: process

Review rounds read the diff and not the CI result. Rounds 2 and 3 approved a head whose `validate` was red. That spent the cap with no finding left to fix (memory note "APPROVE is not a green check", ASK-2036).

## Verification

- Red first, on 827d2a43: ran the 9 tests locally. All 9 exited 1, with the same FAIL lines as CI.
- Green after, on 33dad1cc: all 9 exited 0. So did 5 more lib-copy tests (dry-run-labelled, reviewer-status-identity, gh-repo-scope-reviewer, artifact-repo-keyed, root-guard), test_model_routing.py and test_review_lean.py.
- test_model_call_sites.py and test-subscription-only.sh: the same 3 failing ids and the same FAIL lines on 33dad1cc as on origin/main c395d6aa. Those are fleet-instance state on this Mac (ASK-4119, ASK-2772, ASK-2775). The round-4 reds for kipi-system are gone.
- Negative self-tests, mutate.py on pr-review-agent.sh, 4 of 4 KILLED and restored: `--model` removed (model-routing red); disallowedTools removed (blocked-verdict red); `$FLEET_CLAUDE -p` renamed (test_model_call_sites.py's kipi-system subtests red); `${REVIEW_LEAN_FLAGS}` not spliced (test_review_lean.py red).

## Contributing factors

- No `set -e` in pr-review-agent.sh, so a failed `.` did not stop the run. The run went on to the engine, and the symptom showed up far from its cause.
- The PR's own suite (test_review_lean.py) checked the lib on its own, never the reviewer staged the way the older tests stage it.

## Fixes shipped

- Surface fix: every lib-copy list that copies reviewer-token-lib.sh now also copies review-lean-lib.sh. The tree-guard loop and the scratch slice prelude source it too (66768b4d).
- Structural fix: the claude line goes back into pr-review-agent.sh's `bash -c` string, the same as main. The lib only sets `REVIEW_LEAN_ENV` and `REVIEW_LEAN_FLAGS`, which the line splices in, and both are empty when off. Every consumer reads the reviewer again, so the three consumer patches were reverted (33dad1cc). test_review_lean.py now expands the REAL template. Mutants on the reviewer line, 4 of 4 KILLED.

## Action items

- [ ] Derive the scratch-dir file list from pr-review-agent.sh's own `.` lines, so a new sourced lib cannot be missed by a hand-kept list. Owner: sana. Type: test. ASK-4800.
- [ ] Declare expected_tests for test_model_call_sites.py, so a diff that moves a claude call runs it in validate. Owner: sana. Type: gate. ASK-4801.

## Lessons

- Moving a command line into a sourced lib also moves it away from every detector that found it by reading the file. Leave the line where the readers are, and move only the parts that vary.
- Two rounds of the same class (consumers fixed file by file) mean the fix is the wrong shape. Stop patching readers.
- A review round on a head with red CI spends the cap and fixes nothing. Read statusCheckRollup before asking for a round.
