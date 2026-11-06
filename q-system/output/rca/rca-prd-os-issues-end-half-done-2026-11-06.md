# RCA: prd-os issues end half done, PRs sit unmerged, and the tickets that record it are never picked up again

**Date:** 2026-11-06
**Trigger:** founder observation, 2026-11-06: "The prdos should run issues end to end and what keeps happening is that they are either half done or not done and tickets are left orphaned."
**Surface-fix commit:** pending
**Structural-fix commit:** pending

<!-- rca-recurrence-skip: the three matches rca-lint names (claude-tampering 2026-08-16, design-chain 2026-09-18, derived-copy-drift 2026-06-30) share vocabulary, not a root cause. The one real overlap, a fleet sync deleting a landed guard (root cause #7), is tracked as ASK-3821. -->

Scope: the whole issue path, not the plugin alone. `prd-os` splits the PRD, `kipi-dsse` runs the issue, `linear-worker.sh` dispatches it, `converge.sh` drives review rounds, `pr-review-agent.sh` reviews the PR, `ci-redrive.py` and `review-redrive.py` re-enter it, and `linear-alert-triage.py` is the consumer for every "needs a human" ticket the others file. The founder calls all of this "the prd-os system", so this RCA does too.

Inputs: this session's own measurements (commands in Verification), two peer sessions (chief and consulting, both answered 2026-11-06 with their own RCAs), and five read-only agents over chief, consulting, ktlyst product, kipi-scheduled, intel and kipi-system. Prior RCAs that already name part of this: `~/projects/consulting/q-consult/output/rca/rca-bot-send-trash-roadblocks-2026-10-29.md`, `~/projects/chief/canonical/grokbot/rca-parity-shipped-not-used-2026-11-06.md`, `rca-specification-reported-as-state-2026-08-02.md` (this directory).

## What happened

Issues are dispatched, built, reviewed and then stop. The stop is always one of five designed caps (worker attempts, converge rounds, reviewer rounds, rebase rounds, auto-merge not armed). Every cap ends the same way: a Linear ticket labelled `needs-triage` that says "needs a human". The one program that consumes that label has not completed a single decision since it was put under launchd. So the terminal state of the whole pipeline is a queue with no reader, and the work behind each ticket ages until it conflicts with main and is abandoned.

Expected: an issue goes open, in-progress, PR, review, merge, closed, with a receipt at each step. Actual: 17 open PRs in kipi-system alone (oldest 2026-09-24), 24 "hit the review round cap" tickets since 2026-10-03 (23 still Backlog), 9 "stuck after 3 attempts" tickets, 7 "converge parked" tickets, 3 "PR is NOT armed, goes green and sits forever" tickets, roughly 60 open spillover tickets, and a `needs-triage` queue of 1225.

## Surface symptom

Measured 2026-11-06 (commands in Verification):

- `gh pr list -R assafkip/kipi-system --state open`: 17 PRs. 10 are blocked on the `kipi/reviewer-approved` status, which reads either "review cap reached (3); needs a human decision" or "no reviewer verdict at this head". 3 are `DIRTY` (conflict with main). Three of the 17 are prd-os fixes for this exact problem, open since 2026-10-07: #529 (runtime receipt to close), #530 (one PR per spec), #532 (review on ready, one full and one fix-only round).
- Linear, query "hit the review round cap": 24 tickets since 2026-10-03, 23 in Backlog, 1 Done.
- Linear, query "stuck after attempts": ASK-899, ASK-921, ASK-868, ASK-1498, ASK-1499, ASK-1517, ASK-3752 in Backlog since as early as 2026-08-16.
- Linear, label `owner:sana`, state In Progress: 15 issues; ASK-2058 started 2026-09-24, ASK-1876 started 2026-09-30, both with their PR at the review cap.
- `~/.config/kipi/linear-alert-triage.log`: 15 nightly passes, every one "0 written, 0 skipped, 8 failed". Queue 701 on the first logged pass, 1225 on 2026-11-06. `linear-alert-triage.err`: every row "no working claude binary", last line "EVERY decision failed (8); an outage is not a quiet night".
- `launchctl list | grep linear-alert`: `com.kipi.linear-alert-triage` last exit status 1.

## Surface root cause

`q-system/.q-system/scripts/linear-alert-triage.py:569` `claude_binary()` tries, in order, `$KIPI_CLAUDE_BIN`, bare `claude`, `~/.claude/local/claude`, `/opt/homebrew/bin/claude`, `/usr/local/bin/claude`. The launchd plist `com.kipi.linear-alert-triage` sets no `EnvironmentVariables`, so bare `claude` has no PATH to resolve against, and the three fallback paths do not exist on this machine. The real binary is `/Users/assafkipnis/.local/bin/claude`. The function returns None, every decision is skipped "for tomorrow", and tomorrow is identical. No health check watches this job's output, so a promoter that has written zero decisions for weeks looks the same as a quiet night.

That is the proximate cause of "tickets are orphaned". It is not the cause of "issues end half done". Those are below.

## Structural root cause

### Root cause #1: every terminal state routes to a human, and the system's own ruling is that the human does not act

type: process

`linear-worker.sh:1697` to `1748` (3 attempts), `converge.sh:1291` (3 rounds, "Parked -- no redrive will re-enter it until you clear it"), `pr-review-agent.sh:395` to `445` (3 rounds, "decide merge, rework or close"), `linear-worker.sh:1948` to `1960` (2 rebase rounds, "a human resolves this one"), and ASK-835 / ASK-1996 ("PR is NOT armed, goes green and sits there forever. Needs a human") all terminate by filing a `needs-triage` ticket and paging once. The founder's standing ruling (`memory/feedback_founder_never_the_next_actor.md`, 2026-08-01, reaffirmed 2026-11-02) is that the founder is not a tier in the escalation ladder and every terminal state names a machine consumer. It is also canonical: `q-system/canonical/decisions.md:171` (RULE-015) reads "Needs a human decision is a defective deferral, not a terminal state", and the 2026-08-01 plan `terminal-state-redrive-2026-08-01.md:82` set one alternate-runner attempt before any human page. Every cap site quoted above prints the phrase the rule forbids. The caps were built to stop cry-wolf loops (ASK-1172, ASK-871) and they do stop them. What they hand off to is a label, and nothing holds the label.

The registry built to catch exactly this, `q-system/.q-system/terminal-states.json` (ASK-353, 2026-08-01, "loop-exits.md answers 'can the loop stop?' and never asks 'who acts next?'"), has 54 rows. 32 name no consumer. Among them: `attempts-cap-stuck` ("fable-escalate.py exists in code. It is not wired to this state"), `conflict-cap` ("Nothing selects on mergeable/mergeStateStatus"), `worker-degraded-approval-held` (nothing re-runs a degraded review), and the green-armed-but-not-landing state whose named consumer `pr-land-if-green.sh` (ASK-310) does not exist in any tree. `pr-restack.py`, the sweeper for conflicting PRs, is on main and declared inert pending a founder decision (sp-80307e44).

The founder's 2026-09-19 ruling (`memory/feedback_five_rounds_is_a_loop.md`: "Start a new agent and identify if you have been running in circles"), and the 2026-11-06 restatement ("after 3 failed merges we must stop, change agent and use Fable to do a full RCA"), exist only in memory notes. `grep -rn "fable\|rca" linear-worker.sh converge.sh pr-review-agent.sh` returns zero code lines. The Fable escalation that does exist (`token-guard.py`, ASK-311) fires only on three identical tool calls or three failed edits inside one session, sends a 25-record transcript tail with a 45-second cap, and is not wired to any merge, review or attempt cap.

### Root cause #2: the dead-letter consumer is broken and unwatched

type: code-defect

Surface root cause above. The structural half: `linear-alert-triage.py` is the single reader of the single label every cap writes to, and it has no caller-side health check. `launchd-health-check.py` sees the job run and exit; the job's own stdout says "0 written" every night and nothing compares that number to the queue size. The "an outage is not a quiet night" line was written for exactly this and prints to a log nobody reads. Same defect class as `rca-specification-reported-as-state-2026-08-02.md`: a file artifact (the log line) stood in for an observation. The queue has exactly one consumer by design: ASK-839 keeps alert tickets out of dispatch (`linear-worker.sh:626`), and `linear-alert-triage.py`'s own header already said "the declared consumer is the empty set" when the queue was 151. A second signal was available and unread: `handoff-2026-08-09.md:128` measured that 89 percent of Fable escalations were volume-ceiling hits, not stuck states, so the one escalation path that does run is mostly firing on the wrong trigger.

### Root cause #3: a ticket moved to In Progress never comes back, and every drain only reads Backlog

type: code-defect

`linear-worker.sh:721` and `:736` select only issues whose Linear state type is `backlog` or `unstarted`. `linear-dor-drafter.py:194` does the same (per the consulting peer; confirmed in `automated-filer-marking.md`). An issue the worker picks up is moved to In Progress by the agent's `kipi linear progress` call. When its run fails, caps out or its PR parks, nothing moves it back. It is now invisible to the worker, the DoR drafter and the redrives, and `linear-triage-health.py` calls it dormant only after 75 days. The 15 `owner:sana` In Progress issues, the oldest 43 days, are this. INFERRED for the exact transition; MEASURED for the filter and the population.

### Root cause #4: the review loop is sized for a rewrite and run on every change, and each round is a fresh reviewer that must produce findings

type: process

`issue_runner.py:68` caps review at 2 standard plus 1 adversarial for every issue. `pr-review-agent.sh:395` runs up to 3 rounds for every PR. Neither reads the change size. ASK-1749 shipped a change-size classifier for CI test selection (2026-09-19) and nothing on the review side consumes it. The founder's option 3 ruling (one Sonnet reviewer for a one-line fix, no adversarial; `memory/feedback_test_budget_option_1.md`) is prose. So is the newer and more specific "lean mode" ruling of 2026-10-30 and 2026-11-04 (consulting `memory/match-the-review-depth-to-the-blast-radius.md:82`): one review per PR and one fix round, then merge; nits get a written rejection on Linear, never a follow-up PR; adversarial review only for code that sends mail, touches client data, loses data or moves money. PR #532 ("review on ready, one full + one fix-only per PR") is that ruling as code and has been parked at the review cap since 2026-10-07. The ruling has been given at least three times (2026-09-18, 2026-09-23, 2026-10-30).

Each round is a fresh model that cannot read the prior round (ASK-3067, ASK-3316: review-scratch path denied). A round killed at the 2400-second timeout counts against the cap and its findings are lost (`pr-review-agent.sh:136`, `:1329`; chief PR #321 lost one of three rounds this way). The cap is reached on noise, the PR status is set to "needs a human decision", and Root cause #1 applies. Prior memory notes already name this class: `feedback_same_finding_twice_go_structural.md` (PR #297, seven rounds, six the same class), `feedback_five_rounds_is_a_loop.md` (PR #377, five rounds, got worse), `i-raised-the-review-cap-and-it-churned-all-day` (consulting).

### Root cause #5: work in progress is unbounded, so the oldest items conflict with main before anyone returns to them

type: capacity

`~/.config/kipi/linear-worker-attempts.json` tracks 269 issues. The daily dispatch cap is 10 issues (ASK-667, ASK-884: 60 to 80 agent sessions a day). New issues start every day while 24 capped PRs, 15 In Progress issues and 60 spillover tickets age. 3 of the 17 open kipi-system PRs are `DIRTY` and 2 of the 8 open across chief and the product repo are `CONFLICTING`. Stacked PRs on a squash-merge repo conflict once per parent squash (chief #322 on #320, kipi-system #563 on #562, 2026-10-29). No gate reads work-item age; nothing refuses a new `issue start` while a major spillover from the same PRD is open (chief: 64 open parity rows, 3 majors unowned 12 days while the next issues started). Fleet-wide: 2039 of 2956 consulting spillover rows are open, 25 of them blockers, and a row has no owner field. 30 consulting specs and 29 chief specs sit in-progress, the oldest from 2026-06-11. The one WIP limit that exists is in chief's `cloud_worker.py:66` (at 5 open own PRs in a repo, rework the oldest instead of opening another; added after 82 open `sana/*` PRs and "no fire went back to one"). It is not in `linear-worker.sh`.

The DSSE Stop gate, which should hold a session on its open issue, nags whichever session stops next, shares its 3-warning limit across the repo, and then lets the session end with a log row (`kipi-dsse/hooks/stop_gate.py:24`, `:107`). Consulting's `gate-bypasses.jsonl` holds 649 rows, every one a gate-exhaustion bypass on one issue that is still in progress.

### Root cause #6: the required CI check is red for reasons unrelated to the PR, so a green merge is impossible and builders route around it

type: implicit-contract

`validate` on the open kipi-system PRs runs 18 to 30 minutes and fails on: a plugin changed without a version bump (PR #530), `capability-gate` "present-but-undeclared" for a test added by an unrelated merge (PR #600), and the `test-updater-arms-new-jobs.py` case that inherits that red. chief's pre-commit floor has been red on every local commit since consulting #369 renamed `SYNC_OWNED` (2026-10-27), and a load-flaky PDF test fails 4 of 6 batch runs under parallel builders. A required check that is red for the tree rather than the diff cannot be made green by the PR's author, so the PR waits for a human (Root cause #1) or the floor is bypassed (`merge-bypass-gate.py` exists because of this). Inside the issue, `issue_runner.py:767` to `769` re-runs every required check 5 to 10 times against a 20-minute budget for every issue regardless of size. Two mechanical blockers make the close step itself fail on every chief issue, so agents route around it: `issue_runner.py close` fails with "No module named prd_runner" in that repo (sp-93f41220, worked around twice with a hand-set PYTHONPATH), and chief's `pyproject.toml` `-q` plus each spec's `-q` leaves pytest printing no count, which verify refuses (sp-dae00232, patched one spec at a time by amendment). The append-only `.prd-os` ledgers (receipts, gates, findings) conflict on every parallel merge, each conflict costing a 6-minute floor run plus CI (sp-f9ea5447); close receipts ship as separate follow-up PRs because of it. This is the third time the same shape has appeared: 19 of 22 open PRs conflicted on `capability-manifest.json` in August (fixed by one file per entry, #263), then all 20 approved PRs were CONFLICTING on `receipts.jsonl` in October with 0 merged (`prd-receipts-fragments-2026-10-01.md:16`). That PRD is approved and not built; `.gitattributes:15` sets `merge=union` on the ledgers and GitHub's merge ignores that attribute. Chief #326 had zero CI runs because it conflicted on those ledgers and was still reviewed and verified as if green (sp-946de69e).

The approval is pinned to one commit. Any commit after the review, including converge's own receipt commit (ASK-1888, fixed 2026-09-19) or a nit fix after APPROVE WITH NITS, leaves the PR blocked with auto-merge armed and nothing happening; `review-redrive.py:163` recorded 63 armed PRs stuck this way (ASK-2029).

### Root cause #7: rulings and lessons are recorded as prose and never reach the code that would enforce them

type: process

The two rulings this RCA was asked about: "fewer and shorter checks" is half in code (`check_budget.py`, ASK-1749, ASK-2316) and half in memory; "after 3 failures stop, change agent, Fable RCA" is entirely in memory. `~/.claude/rules/iteration-speed.md` rule 3 says every ruling goes into a file the code reads in the same turn. Across 17 consulting voice RCAs there are 71 open action lines, 24 of them prose with no executable (consulting peer). `rca-lint.py:276` matches recurrence only against RCAs in the same directory, so the same class across consulting, chief and kipi-system is never matched. `lessons-inject.py` surfaced 0 of 5 relevant lessons on four replayed incident prompts, and 0 of 256 lessons name an executable. The class "cap-out invisible to redrive" was fixed in ASK-871 (2026-08-16, Done), refiled as ASK-2209 (2026-09-29, Backlog), ASK-2940 (2026-10-23, Backlog) and ASK-3597 (2026-10-31, Todo).

Fixes that did land have been deleted by the fleet sync. kipi-investigations' `rca-built-not-wired-2026-06-14.md` found that "Open for v2 / follow-up" written in PRD prose is converted to nothing at split and evaporates at archive; its fix, `_deferral_tracking_gate` (commit f00ee9d7), was removed one day later by the plugin-sync commit 1d2568c5 and is in no `prd_runner.py` today. kipi-system #333 (2026-09-08) is the same event on a different guard: "restore the ASK-1040 guard and the 7 tests a fleet sync deleted". Measured in kipi-investigations' `.prd-os` today: 36 PRDs at `approved` never archived, 162 of 428 issue specs with no close receipt.

### Root cause #9: the fleet reviews Claude with Claude by default, nothing tests whether Codex is back, and gate 50 parked the 39 degraded approvals

type: config

`linear-worker.sh:1857` to `1886` (gate 50, ASK-2036): when the verdict record says `degraded: true`, the worker disarms auto-merge and skips the PR, with the cost stated in its own comment: "during a long codex outage approved PRs accumulate unmerged. That is the direction the loop should fail in." CORRECTED 2026-11-06 after a live test. The claim first written here, that every approved PR for seven weeks was parked by this branch, is wrong. Measured over verdict records since 2026-09-16: 486 `engine: claude, degraded: false`, 22 Codex clean, 39 Codex degraded (newest 2026-10-23). Gate 50 parked those 39. The larger cause is upstream of it: commit 77cb3a7e (#319, 2026-09-07, founder: "forget codex go with the claude fallback") moved both reviewer defaults in `pr-review-agent.sh:164` and `:261` to `claude`. That was right while Codex was broken. Codex now works: one `codex exec --model gpt-5.6-sol` call on `assaf@ktlystlabs.com` returned OK on 2026-11-06. Nothing tests whether Codex has come back, so the fleet still reviews Claude's work with Claude, and the independence the 2026-07-29 directive paid for is off by default with no signal. The founder's ruling of 2026-09-23 ("you dont need codex credits, you can use opus as a fallback") says the opposite of what the code does, and `terminal-states.json` row `worker-degraded-approval-held` records that nothing re-runs the review on a degraded record; it clears only when someone runs `kipi review` by hand. The independence the branch protects is already gone in practice: with Codex out, the "Codex" standard round, the adversarial round and the fallback are all the same model reviewing the same model. The prose says the fallback works, the code parks it, and nothing compares the two. Consulting's `q-system/output/rca/rca-enforce-in-code-ends-as-prose-2026-11-06.md` (root cause #2) carries the same finding from the consulting side and cites this file.

### Root cause #8: "closed" does not mean shipped

type: code-defect

`issue_runner.py:433` `_count_checked_deliverables` counts checkboxes in the spec. A Live deliverable can be checked with the text "PENDING deploy" and the issue closes; 5 of 23 chief gp-* issues closed that way and none received its receipt afterwards (chief peer, `~/projects/chief/.prd-os/issues/gp-*.md`). A PRD split produces mechanism issues and no activation issue, so founder hands ("use browse once") sit in Acceptance text with no trigger and dependents never start. `prd_runner.py gates run` exits 0 when zero gates executed (`prd_runner.py:3180` to `3195`; ASK-1038: 29 days green with nothing run), so an archive can pass with nothing proven. PR #529 (runtime receipt required to close) is the fix and is itself parked at the review cap.

## Verification

This RCA ships no fix, so verification here is of the diagnosis. Each claim above was produced by one of these runs on 2026-11-06:

- `gh pr list -R assafkip/kipi-system --state open --json number,createdAt,mergeable,statusCheckRollup`: 17 rows, oldest `2026-09-24`.
- `gh pr checks 559`: `kipi/reviewer-approved pending ... review cap reached (3); needs a human decision`. `gh pr checks 530`: `no reviewer verdict at this head (floor: absent is not approved)` and `validate fail 18m25s`.
- `gh run view 37565562634 --log-failed | grep FAIL`: `FAIL No plugin changed since origin/main without a version bump`. `gh run view 41522158416 --log-failed | grep RED`: `RED: present-but-undeclared: q-system/.q-system/scripts/test/test_instance_hook_dispatch.py`.
- Linear `list_issues query="hit the review round cap"`: 24 rows, 23 Backlog. `query="stuck after attempts needs a human"`: ASK-899, ASK-921, ASK-868, ASK-1498, ASK-1499, ASK-1517, ASK-3752 Backlog. `label=owner:sana state="In Progress"`: 15 rows, `ASK-2058 startedAt 2026-09-24`.
- `tail -8 ~/.config/kipi/linear-alert-triage.log`: eight rows of `triage pass: 0 written, 0 skipped, 8 failed`, queue `1006, 1090, 1136, 1142, 1166, 1196, 1211, 1225`. `grep -c "triage pass"`: 15. `head -1`: queue 701.
- `for c in claude ~/.claude/local/claude /opt/homebrew/bin/claude /usr/local/bin/claude; do ...`: only bare `claude` present. `command -v claude`: `/Users/assafkipnis/.local/bin/claude`. `plutil -p com.kipi.linear-alert-triage.plist | grep EnvironmentVariables`: no output.
- `sed -n 721p linear-worker.sh`: `if i["state"]["type"] not in ("backlog", "unstarted"): return False`.
- `grep -nE -i "fable|\brca\b" linear-worker.sh converge.sh pr-review-agent.sh` (non-comment lines): none.
- `sed -n 1857,1886p linear-worker.sh`: gate 50 comment "during a long codex outage approved PRs accumulate unmerged", then `disarm_automerge "$EXISTING_PR"` and `continue`.
- `python3` over `q-system/.q-system/terminal-states.json`: 54 rows, 32 with no consumer field.
- `grep -n "REVIEW_CAP_DEFAULTS = " issue_runner.py`: `{"standard": 2, "adversarial": 1}`. `grep -n "REPEAT_MIN\|REPEAT_MAX\|REPEAT_BUDGET_S" issue_runner.py`: `5`, `10`, `1200.0`.
- `python3 -c` over `.prd-os/issues/*.md` (last 40 by mtime): average 1.1 required checks, 0 full-suite.

Not verified in this session, taken from the peers and marked as theirs: the In Progress transition on pickup (Root cause #3), the 5 of 23 gp-* closes (Root cause #8), the 71 open RCA action lines and the lessons-inject replay (Root cause #7), the 2400-second lost round on chief #321 (Root cause #4).

## Contributing factors

- No work-item-age metric anywhere in the pipeline. Little's law says cycle time is WIP over throughput; throughput is pinned at 10 issues a day and WIP has no ceiling, so age grows without a signal.
- Hooks fail open fleet-wide: 69 of consulting's 70 hook entries pass silently when their script is missing (consulting peer, `G-enforcement-census.md`).
- The founder's always-on instruction budget is 2773 lines across 41 rule files; the rules that say "cap at 3, then stop and surface" are in that pile and have no executable.
- Three of the fixes for this RCA's own root causes (PRs #529, #530, #532) have been parked at the review cap since 2026-10-07. The pipeline cannot merge the fix to the pipeline.
- Review timeouts are charged as rounds; a slow reviewer loses its findings and burns the cap.
- Stacked PRs on squash merge guarantee one conflict per parent; the rebase budget is 2.

## Fixes shipped

- Surface fix: pending. Set `KIPI_CLAUDE_BIN=/Users/assafkipnis/.local/bin/claude` (or add `~/.local/bin/claude` to the candidate list) in `linear-alert-triage.py` and the plist; run one pass by hand; confirm "written" is non-zero.
- Structural fix: pending. See action items.

## Action items

Filed 2026-11-06 as three Urgent umbrellas with 16 children, team ASK_Consulting, project kipi-system, owner:sana, each child carrying a Definition of Ready the worker can pick up. Deduped against the 91 open action items in the nine other RCAs; each ticket names what it absorbs. The founder's three rulings of 2026-11-06 are RULE-2026-11-06-A, B and C in `q-system/canonical/decisions.md`.

Structural 1, ASK-3815: every "bounded by code" claim names its wired executable, or is lint-red.
- [ ] ASK-3818 Enforcement-claim lint: must/never/blocks lines carry `held_by:` or `ticket:` plus `expires:`; fail-open hooks are listed as advisory by `kipi check`. — owner: Sana — type: gate
- [ ] ASK-3819 rca-lint: recurrence across every repo's RCAs; an action item without an owner and a Linear id is refused. — owner: Sana — type: gate
- [ ] ASK-3820 terminal-states.json: every row names a consumer that exists on main; build or retire `pr-land-if-green.sh`, schedule or retire `pr-restack.py`. — owner: Sana — type: gate
- [ ] ASK-3821 Fleet-sync guard: the updater refuses to delete a function or test the skeleton added in the last 30 days. Red first: replay 1d2568c5 against f00ee9d7. — owner: Sana — type: gate
- [ ] ASK-3822 `gates run` with zero executed gates exits non-zero; `no-orphan-findings.md` says what the code does. — owner: Sana — type: code

Structural 2, ASK-3816: no ticket or PR reaches a state with no machine consumer.
- [ ] ASK-3823 needs-triage promoter: find claude under launchd, health-check written against queued, drain the 1225 over several nights at the existing cap. — owner: Sana — type: code
- [ ] ASK-3824 Every cap ends in code: Fable RCA of the full packet, one attempt by Opus carrying it, then one page. Fable diagnoses, Opus runs; "needs a human decision" removed from every cap message. — owner: Sana — type: code
- [ ] ASK-3825 Worker state round-trip: back to Backlog on fail, cap or park; the picker sees started tickets with no live claim. Red first: ASK-2058 is invisible to the dry run today. — owner: Sana — type: code
- [ ] ASK-3826 WIP ceiling (rework the oldest PR at 5 open, from chief's `cloud_worker.py:66`) and a work-item age gate on `issue start`. — owner: Sana — type: gate
- [ ] ASK-3827 Land #529, #530, #532; then review depth and verify repeats read the ASK-1749 size class (the founder's lean mode). — owner: Sana — type: code
- [ ] ASK-3828 CI `validate` on a PR runs the diff-earned set only; tree-wide gates run nightly on main and file against the commit that broke them. — owner: Sana — type: gate
- [ ] ASK-3829 prd-os ledgers as fragments (one file per row, since `merge=union` is ignored by GitHub); the two chief close blockers fixed in the runner. — owner: Sana — type: code
- [ ] ASK-3830 Closed means shipped: runtime receipt for Live deliverables, one activation issue per founder hand, PRD-prose deferrals become tracked issues. — owner: Sana — type: gate

Structural 3, ASK-3817: a reviewer outage never stalls the fleet and never fails silently.
- [ ] ASK-3831 One reviewer resolver for every review call site: Codex primary, Codex other account, Opus stamped; an outage is one health event a day. The ticket asks the founder one question: how the second Codex account is selected. — owner: Sana — type: code
- [ ] ASK-3832 Remove gate 50 (`linear-worker.sh:1857`); a degraded approval is an approval; re-arm every PR disarmed since 2026-09-16 and report how many land. — owner: Sana — type: code
- [ ] ASK-3833 A timed-out review round is not charged and its findings are posted; `model_gate` meters review rounds in `pr-review-agent.sh` and `converge.sh`. — owner: Sana — type: code

Settled by the founder's 2026-11-06 words, no ticket: the second runner at a cap is Opus ("move to opus everywhere"); Fable is the diagnosis only ("use fable to do a full rca").

## Literature

What is known, mapped to the root causes above. Each is a published source read in summary on 2026-11-06, not re-derived here.

- Same-model retries do not fix reasoning. Huang et al., "Large Language Models Cannot Self-Correct Reasoning Yet" (ICLR 2024, arXiv 2310.01798): without external feedback, performance drops after self-correction rounds. Supports Root cause #1 and the ruling to change the model, not retry.
- More review rounds add noise. Song, "More Rounds, More Noise" (arXiv 2603.16244, 2026): single-pass review F1 0.376 beat every multi-turn variant; a fresh second review with no prior context was worst (0.263); later rounds generate false positives faster than true findings. Supports Root cause #4 and the fresh-reviewer-per-round design being the wrong one.
- Agents loop and abandon. SWE-agent (arXiv 2405.15793) names "Failed Edit Recovery" (23.4 percent of failures) and "Gave Up Prematurely". METR (arXiv 2503.14499) names "premature task abandonment" as half of one model's failures. Majgaonkar et al. (arXiv 2511.00197): failed trajectories are longer and higher-variance; agentic tools get trapped in long unproductive loops in the repair stage. Supports the 3-attempt cap and the need for an outside diagnosis at the cap.
- Multi-agent failures are design failures. Cemri et al., "Why Do Multi-Agent LLM Systems Fail?" (NeurIPS 2025, arXiv 2503.13657): 14 failure modes in three groups, one of which is "task verification and termination"; the authors find most failures come from system design, not model limits. Supports treating this as a pipeline design defect, not a prompt problem.
- Escalation thresholds are miscalibrated per model. DiSorbo and Ju, "Act or Escalate?" (arXiv 2604.08588, 2026): models differ by 25 points in when they defer; overconfident models act when they should hand off. Supports a coded cap rather than a model-judged one.
- Abandoned pull requests have known causes. Khatoonabadi et al. (ACM TOSEM, arXiv 2110.15447; 265,325 PRs): abandoned PRs are more complex, have longer reviews, and the top reasons are difficulty addressing review comments, lack of review, CI failures and merge conflicts. Li, Yu et al., ICSE 2022: lack of integrator responsiveness is the main deterrent; two thirds of integrators simply close abandoned PRs though most contributors would pick them up. Supports Root causes #4, #5 and #6: every one of those causes is present here.
- Stale bots trade backlog for abandonment. Khatoonabadi et al., "Understanding the Helpfulness of Stale Bot" (arXiv 2305.18150, also indexed as "GitHub Stale Bot Considered Harmful", DOI 10.1145/3624739): closing stale PRs clears the backlog and lowers active contributors. Supports not answering this with an auto-close.
- Flow: cycle time is WIP over throughput, and aging is the leading signal. Little's law (relationship of averages; Vacanti, Actionable Agile Metrics; Planview Viz notes that letting WIP grow breaks the law's assumptions). Work Item Age is the one flow metric that gets worse by doing nothing. Supports Root cause #5 and the age gate.
- Dead-letter queues need a named owner and a replay procedure. Gravitee DLQ guidance: a DLQ policy names retry count, backoff, retention, ownership and recovery; "a DLQ without an owner isn't a safety net". Supports Root cause #2.
- Retry budgets, not retry counts. Google SRE, Handling Overload: a per-request cap of three attempts plus a per-client budget of 10 percent of traffic. Supports a fleet-level cap on review rounds per day, not only per PR.
- Action items need an owner and a tracking number. Google SRE workbook postmortem practice (cited by the consulting peer). Supports the rca-lint action item above.
- Loop detection in coding agents is coarse. Anthropic-adjacent terminal-agent paper (arXiv 2603.05344): doom-loop detection added after agents repeatedly called the same tool with identical arguments; iteration counts alone were too coarse. Matches `token-guard.py` exact-retry, and shows the detector is the easy half.

Not found: controlled evidence for andon-style stop-the-line rules in software delivery. The argument is by analogy to Toyota; the pattern libraries list "alarm fatigue" and "fear of stopping the line" as its failure modes, both visible here.

## Lessons collected from the other projects, 2026-11-06

Asked of the chief and consulting sessions directly, and read by agents from chief, consulting, ktlyst product, kipi-scheduled, intel and kipi-system. One line each, grouped, with where it stands. The full lists are in the agent transcripts and the two peer replies; the ones that changed this RCA are already woven in above.

Already in code:
- chief `cloud_worker.py`: at 5 open own PRs, rework the oldest before starting a new issue (2026-09-30).
- chief `lgtm`: PRs idle over 14 days are closed, at most 25 a day, branch kept, issue back to the queue. The literature below says this trades backlog for abandonment; measure before copying it.
- chief `lefthook.yml`: pre-commit runs only the owning tests; the full suite runs once in CI (2026-09-30).
- kipi-system `converge.sh` and `attempts-ledger.py record-capout`: a cap-out is readable so the redrives stop re-entering it (ASK-871). The founder clears it by hand, which is the defect this RCA names.
- kipi-system `linear-route.py` (ASK-1887): 102 tickets that failed the worker's pick filter are routed instead of counted.
- kipi-dsse verify contract 2 (ASK-1810): repeats, real-path observation, defined-vs-ran counting.
- ktlyst `check_gate_inventory_realized.py`: every declared gate is on the line that ships, for gates only.

Prose only, and contradicted by running code:
- "Opus is the fallback, never park on a Codex outage" (founder 2026-09-23) versus `linear-worker.sh` gate 50.
- "At the cap, merge if no blocker or major, otherwise file spillover and stop; Sana decides, never the founder" (consulting memory 2026-10-03) versus `pr-review-agent.sh` "needs a human decision".
- "Lean mode: one review, one fix round, merge" (founder 2026-10-30, 2026-11-04) versus the fixed 3-round and 2+1 caps.
- `no-orphan-findings.md` claims `gates run` fails on any open spillover item; the code blocks only on the active scope.

Prose only, not contradicted, not built:
- Commit WIP when a subagent stops with uncommitted changes; four runs edited 28 files and committed none (consulting RCA 2026-10-29).
- Commit, push and open the PR in one command; four builders left branches unpushed 10 to 90 minutes (consulting 2026-10-31).
- Push, confirm the remote has the commit, then arm auto-merge; never push to an armed branch (consulting 2026-10-16).
- One issue, one change, is "the single strongest predictor of convergence" (kipi-system plan 2026-07-28). Split any PR over about 3 files or 2 bots (consulting 2026-10-03).
- Same finding class on two consecutive rounds means the fix shape is wrong; go structural or park (kipi-system memory, three times).
- Stop the agent on a second identical failure and start a fresh one whose only job is to find why it repeated (consulting 2026-10-03, `iteration-speed.md` rule 2).
- Every new gate ships with its wiring on the same merge; "the project consistently builds detection without enforcement" (ktlyst RCA 2026-05-16).
- Receipts at the issue level need a closeout layer that re-asserts the integration (ktlyst PRD 2026-05-05).
- A PRD split delivers mechanisms; one issue must own the journey, or nothing is used (chief RCA 2026-11-06: 0 of 17 new doors used from the phone in 477 turns).
- A reversal ruling must regenerate its derived texts, or builders read the old rule 14 days later (chief, DEC-88).
- A permission refusal that is intermittent (ASK-141: refused on attempts 1, 2, 3, 6, allowed on 5) cannot be told from a permanent block, and the note recording it is gitignored, so ASK-142 is on its sixth session since 2026-08-15 (ktlyst spillover 2026-11-01).
- Round caps keyed per commit SHA reset on every fix commit; key them per item (kipi-investigations lesson `cap-the-shared-resource-not-the-paths-that-call-it.md`; partly in code via `record-capout`).
- "No more deferring" and "when about to stop or ask, launch an agent team and continue" (kipi-investigations memory, founder 2026-05-29 and 2026-06-19). Prose only.
- If Codex is at capacity, retry once, then review with a Claude subagent stamped as such; a false Codex stamp is worse than a missing review (kipi-system lesson 2026-09-02; the stamp is in code, the one-retry rule is prose).

## Lessons

- A cap that hands off to a label is not a terminal state. It is a terminal state only when the label has a reader whose output is measured against the queue.
- A fresh reviewer per round is the design that produces infinite findings. Review once well, size the depth to the diff, and carry the prior round's findings into the next.
- Age is the signal that work is dying. Measure it, gate on it, and stop starting new work when the oldest item is past the merged-cycle-time tail.
- A ruling in a memory file protects the session that wrote it. The three fixes for this RCA's own causes have been parked at the review cap for 30 days; the pipeline must be able to merge the pipeline's fixes.
