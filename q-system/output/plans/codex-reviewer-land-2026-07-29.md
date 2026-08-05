# Land the Codex reviewer in the unattended loop (ASK-221) — 2026-07-29

## What / why

Founder directive 2026-07-29: Codex reviews Sana's work, unattended. Decision already
taken (this session): keep PR #34's `codex exec` engine, kill PR #45's Linear-agent
delegation. This plan executes that decision end to end.

The gap being closed: `linear-worker.sh:72` routes review through
`pr-review-agent.sh`. PR #34 makes that script's PRIMARY engine codex, so the
required `kipi/reviewer-approved` status becomes a Codex verdict. That is the whole
objective.

## Approach (the pick)

Land #34, close #45, fix the one bash reader. Rejected alternatives and why, from
verified reads:

- **Reuse `codex-companion.mjs` from the worker.** Rejected. `--background` is parsed
  at `codex-companion.mjs:718` and never read (`handleReviewCommand` always calls
  `runForegroundCommand` at :739); job state lands in a purgeable
  `os.tmpdir()/codex-companion` keyed on the *worktree* path (`state.mjs:29-42`,
  `MAX_JOBS=50`); and `DEFAULT_INLINE_DIFF_MAX_FILES = 2` (`git.mjs:8`) with no CLI
  override, so every real fleet PR would be reviewed with no inline diff.
- **PR #45's Linear-agent delegation.** Rejected. Advisory status only (not a
  required check, so it cannot gate), 5 failed live attempts on ASK-221, and it adds
  a third verdict reader.

## Findings to triage BEFORE landing (as the implementing agent)

I did not author these commits. Verify each fix with a reproducer that fails on the
parent commit and passes on the fix. A test that cannot fail is not a test.

| # | From | Sev | Claim | Claimed fixed at |
|---|------|-----|-------|------------------|
| A | `dfacddd7` | minor | `--agent` matched the marker anywhere in the body | `de2a9c3` |
| B | `6789ca54` | minor | first-line anchor still accepts `**sana** prose` (needs the full `**sana** · ` delimiter) | `403bc0b` |
| C | `6789ca54` | major | no tree-vs-PR-head guard: Codex runs and derives a verdict when the reported PR head is not an ancestor of the working tree HEAD | `403bc0b` |

C is the one that matters. Codex's own repro showed `codex_ran=yes` +
`verdict: APPROVE` against a head that was not in the tree. If 403bc0b does not
actually refuse before dispatch, it does not land.

## Files to touch

- `q-system/.q-system/scripts/pr-verdict-lib.sh` — sp-c0a9dac3: `verdict_from_findings`
  uses `sed -n '/^FINDINGS:/,/^END FINDINGS/p'`, which concatenates every block and
  runs to EOF when unclosed. Fix in this ONE reader. Do not add a second.
- `q-system/.q-system/scripts/pr-review-agent.sh` — verify the tree-vs-head guard.
- `q-system/.q-system/scripts/linear-sync.py` — verify the attribution prefix.
- `q-system/.q-system/scripts/verify-codex-review-live.sh` — retarget from the dead
  ASK-253 delegation path to the engine path that actually ships; it becomes the receipt.
- `~/.claude/plugins/marketplaces/openai-codex/plugins/codex/prompts/adversarial-review.md`
  — uncommitted edit to a live gate. Resolve.

## Acceptance criteria

- [~] Findings A, B, C each have a reproducer that FAILS before the fix and PASSES after
      PARTIAL, and the gap is now on the ledger as `sp-600441d2`. Their reproducers live
      in `test-severity-floor.sh`, which is the ONE suite with no pre-fix ref hatch, so
      none of its 169 checks has ever been observed to fail. Passing is not evidence
      there. Do not claim this one until the hatch exists.
- [x] sp-c0a9dac3 reproducer: multi-block review where an early block's severity would
      win under the old `sed` range; fails on current lib, passes after
      `KIPI_TEST_LIB_REF=e5aa6bc bash test-findings-block-reader.sh`
        -> `FAIL: THE DEFECT (sp-c0a9dac3): a review that explicitly REFUTED round 1's
           blocker derived ...`; working tree -> `PASS: 9/9`
- [x] Unclosed-block reproducer: truncated review does not derive APPROVE
      `KIPI_TEST_LIB_REF=b281881 bash test-findings-block-reader.sh`
        -> `FAIL: the lib has no has_complete_findings_block`; working tree -> `PASS: 9/9`
      This is the finding found beyond the three that were handed over: an open FINDINGS
      block at EOF used to read as an empty one and derive APPROVE, so a review truncated
      mid-sentence approved the PR. Fixed in 1d5347d, reproducer above, and the ref hatch
      is what makes it provable rather than asserted.
- [x] `pr-verdict-lib.sh` still has exactly ONE findings-block reader (grep proves it)
      asserted by the suite itself: `ok: the lib has exactly one findings-block reader`
- [x] PR #34 checks green, verdict triaged, merged
      Round 1 on `1d5347d`: REAL codex run, `REQUEST CHANGES`, two findings, both ACCEPTED
      and fixed (`b090ba7`, `fa4608a`), triage posted as a PR comment. Merging `1d5347d`
      would have broken the live loop.
      Round 2 on `fa4608a`: REAL codex run, `degraded=0`, ONE minor, derived
      `APPROVE WITH NITS`, `kipi/reviewer-approved=success` on that sha, `validate` pass.
      Merged as `f277389` at 2026-07-30T04:22:55Z. Minor captured as `sp-583dc1a0`.
- [x] The merge is LIVE in the copy launchd executes (not just in the repo)
      The loaded plist runs `/Users/assafkipnis/projects/kipi-system/kipi-dispatch.sh`,
      that checkout sat at `1597eaf`, and `kipi-dispatch.sh` has NO `git pull` -- so the
      merge alone would have left the loop on the old Claude-only reviewer. This is the
      exact scar the wiring rule names. Fast-forwarded (`merge --ff-only`, no collision
      with the one dirty tracked file) to `f277389`; verified in the running copy:
      `REVIEW_ROOT` at pr-review-agent.sh:222/240, `--engine codex` at
      linear-worker.sh:1133.
- [x] PR #45 closed unmerged with a reason on the PR
- [x] Salvage follow-up issue filed (the 444c484 trigger measurement, the live-plist
      load-path proof pattern, the last-block insight) — ASK-254
- [x] Attribution correction posted on ASK-221 as one top-level comment,
      `--agent claude-session`, naming `8a3ebf43…` (00:25:49Z) and `1b365138…`
      (00:36:40Z), acceptances withdrawn; originals untouched
- [x] `spillover add --source ASK-221` capture recorded
      `sp-600441d2` (no ref hatch on the big suite), `sp-d8adb370` (voided into the
      pre-existing `sp-d3a22cb6` with the stdin root cause attached)
- [x] Marketplace prompt edit resolved, decision stated
      reverted; `sp-c5a17b4a` voided — the shipping reviewer builds its prompt inline
      and never loads that file
- [~] **The objective proven by a RUN:** a real `pr-review-agent.sh --engine codex`
      invocation whose output shows a Codex verdict, plus the verifier reporting the
      live worker reaches that path. Not an assertion.
      REVIEWER HALF: DONE, twice, for real. Round 1 wrote
      `{"verdict":"REQUEST CHANGES","stated":"REQUEST CHANGES","derived":"REQUEST CHANGES",`
      `"source":"findings","engine":"codex","head_sha":"1d5347d…"}` and posted
      `kipi/reviewer-approved=failure` on that exact sha, `degraded=0`.
      LIVE-DISPATCHER HALF: NOT DONE, and blocked tonight — see "Dispatcher proof" below.

## PR #46, the follow-on the reviewer earned (2026-07-30)

Built from `sp-583dc1a0`, the minor codex raised on #34 round 2: the reviewer's Linear
post ended in `>/dev/null 2>&1 || true`, so a failed issue post printed nothing and the
run still exited 0. Merged as `03e39ee`.

Round 1 came back `REQUEST CHANGES` with two majors, **both mine, both real**:

- **The success path posted to Linear TWICE.** My fix edited the TAIL of the existing
  call; the opening lines stayed, and their trailing `\` continued into the new comment
  block, so the original ran without `--agent` or `--evidence`. Two permanent comments
  per review, the first misattributed. It reached ASK-221 before codex caught it. Case 5
  was blind to it because case 5 only drives the FAILURE path. Case 6 now counts calls
  with a logging stub, ordered AFTER case 5 so case 5's failure stays a real missing file.
- **The failure path claimed a page it cannot confirm.** `slack-notify.sh` no-ops silently
  when unconfigured (deliberate, per founder-notifications.md), so a zero exit is not
  delivery. Now it attempts, reports what came back, and leaves the stderr WARN as the
  always-written record.

`KIPI_TEST_REVIEWER_REF=263d134 bash test-review-tree-guard.sh` -> `FAIL: the success
path made 2 calls to linear-sync.py, not 1`; working tree -> `PASS: 24/24`.

Round 2 on `1000890`: one minor, `APPROVE WITH NITS`, status success, `validate` pass.

**The lesson worth keeping:** two of the three defects found tonight were introduced by
the fix for the previous one, and each was caught only because a real reviewer read the
real diff. Editing the tail of a multi-line shell invocation is how both happened.

## Two traps found by watching the runs, not the diffs

- **`sp-48688b24`** the PR comment posts the RAW review file, and codex output ran
  278-435KB against GitHub's 65536 limit, so 3 of 4 rounds failed with
  `Body is too long`. Round 2 of #46 was small enough and succeeded, so it is
  size-dependent. I first filed this as "never works"; overstated, voided with the reason.
- **`sp-bc42f1d3`** CAPTURE WAS MISSING THE LEDGER THE GATE READS.
  `.prd-os/spillover.jsonl` is gitignored, so every worktree has its own. 13 items filed
  from the `ask-221` worktree were invisible from the main checkout, where `gates run`
  was green about work it could not see. Consolidated by hand (15 records appended,
  backup in scratchpad). The load-path scar applied to the ledger itself.

## Dispatcher proof (the half that is not done)

Read from the LOADED plist, not the repo copy
(`/usr/libexec/PlistBuddy -c "Print :EnvironmentVariables:…" ~/Library/LaunchAgents/com.kipi.dispatch.plist`):

- `KIPI_DISPATCH_DAILY_MAX=3`, `KIPI_DISPATCH_RESET_HOUR=7`, `KIPI_DISPATCH_MAX=1`
- `ProgramArguments` -> `/Users/assafkipnis/projects/kipi-system/kipi-dispatch.sh`
  (the founder's MAIN checkout, not a worktree)
- `launchctl print` -> `runs = 130`, `last exit code = 0`, job active
- `~/.config/kipi/dispatch-count-2026-07-29` -> `3`. Cap fully spent.

Two independent blockers, and the ordering between them is forced:

1. **The cap is spent.** A budget day runs 07:00 -> 06:59, so the allowance refills at
   07:00 local on 2026-07-30. The dispatcher keeps beating every 15 min until then
   (`dispatch-lastbeat` moved at 20:50) and each tick is a no-op skip.
2. **Main does not have this code yet.** `origin/main`'s `pr-review-agent.sh` (365
   lines) has no `--engine`, no `CODEX_MODEL`, and no tree guard, and `main`'s worker
   calls `$REVIEWER_CMD "$PR_NUM" --issue "$ISSUE" --post` with no engine flag. The
   live loop reviews with Claude today. So a dispatcher run tonight could not exercise
   the codex path even with budget: the merge is a PREREQUISITE for the proof, not a
   consequence of it.

What will happen at 07:00 local on 2026-07-30, once #34 is merged: the beat finds
`dispatch-count-2026-07-30` absent, dispatches up to 3 issues, and the worker's
`linear-worker.sh:1133` runs `pr-review-agent.sh --engine codex`. What would prove it:
a `pr-<N>.verdict.json` with `"engine":"codex"` for a PR **this agent did not review by
hand**, plus `kipi/reviewer-approved` on that PR's head, plus the matching
`DISPATCH`/reviewer lines in `~/.config/kipi/dispatch.log`. Not the verifier script.

## Patterns to follow (from this repo's own code)

- Single reader of one input: `pr-verdict-lib.sh:72-78` states the doctrine. Three
  readers is the defect PR #45 introduced; do not repeat it.
- Verdict record is the chokepoint: `head_sha_from_record` + `verdict_from_record`,
  written once, read by `linear-worker.sh:597-599` and `converge.sh:161-163`.
- Load-path proof: `verify-codex-review-live.sh` resolves the LIVE plist
  (`com.kipi.dispatch`, StartInterval 900) and asserts against the script the
  scheduler will actually execute. Generalize this, do not delete it.
- Test isolation: `test_linear_sync_comments.py` monkeypatches `graphql`. No live
  Linear in tests, ever.

## Constraints

- Work in a git worktree. The founder's checkout is on `main`; a branch switch there
  yanks their tree.
- Destructive ops stay hook-blocked. If one is needed, name it and stop.
- Do not merge red. Do not merge on an untriaged verdict.
