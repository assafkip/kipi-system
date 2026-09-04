<!-- prompt-only-enforcement-skip: this handoff DESCRIBES state and names the executables
     and PRs holding each claim. It asserts no enforcement of its own. -->
# Last handoff

**Session:** 2026-09-03, kipi-system-0e. Squash-artifact repair on the consulting branch, the review-gate parser (seven codex rounds, parked), branch protection on consulting main, and the closing sweep across three live sessions.

## Where things stand

**Owner of everything open: Sana.** Founder, verbatim, 2026-09-03: "Santa needs to do everything. Don't ask me to do things." `provenance: explicit_statement`. Also: "the alice repo is done" (topic closed, no push tonight). `provenance: explicit_statement`

### Shipped
- **Consulting `feat/gtm-visibility-surfaces`**: squash ancestry recorded (`merge -s ours 107a776e`), then `origin/main` merged with zero conflicts. `[verified: python3 q-consult/pipeline/job_staleness.py -> "verdict: clean"; 326 tests passed across staleness, approval lane, voice provenance, granola, drift_check, ledger, discovery_owner]`. PR #80 open, mergeable_state clean. `ledger.py needs-reply` unchanged on both sides. `[verified: python3 q-consult/email-watch/ledger.py needs-reply --help -> usage prints]`
- **Consulting main branch protection, reduced form**: PR required (0 approvals), force pushes and deletions blocked, NO required status check. `[verified: gh api repos/assafkip/ASK_AI_consultant/branches/main/protection -> required_pull_request_reviews.required_approving_review_count=0, allow_force_pushes.enabled=false, allow_deletions.enabled=false, required_status_checks absent]`. It does not block a PR merging on a false green; that needs the gate below.
- **ASK-1227** created. Spillover **sp-1e05b42c** (kipi-system ledger) captures the parser class with the structural direction: a structured verdict contract (`codex exec --output-schema` or a sentinel block), not prose parsing.
- Closing sweep (Sana, 2026-09-03 evening): consulting CLAUDE.md Reddit-gate doc committed and pushed as c768083d; consulting stash@{0} dropped after byte-identity check (recovery sha e5820dd9); kipi-system primary browser-record-lane files parked as `stash@{0}` "orphan: browser record lane + its CLAUDE.md doc, superseded by kipi-wt-land-bl". `provenance: imported` (Sana's sweep report, read here).

### Parked, and why
- **kipi-system PR #297** (branch `fix/review-verdict-slots`, worktree `.wt-reviewgate`, head f9af3dd5) is a DRAFT. Seven codex rounds; six found the same class (decoy `VERDICT:` tokens or fence state in the session transcript leaking into the verdict reader). Round seven still had one false-red path. Final branch state is better than main: codex final message captured via `-o "$REVIEW.last"`, readers prefer it, pr-190 real transcript resolves APPROVE. `[verified: from .wt-reviewgate, extract_verdict on assafkip_kipi-system__pr-190-20260815-023743.md -> APPROVE; rg-style decoy -> APPROVE WITH NITS; NOT ISSUED + empty block -> resolved empty]`. Do NOT add an eighth denylist rule. Next attempt starts from sp-1e05b42c.
- Spillover items **sp-1015d7a4, sp-8f13d9be, sp-3b31e4f5** remain open in `/Users/assafkipnis/projects/consulting/.prd-os/spillover.jsonl` (not kipi-system's ledger). sp-3b31e4f5 is a separate defect: `--engine claude` writes `kipi/claude-approved` and can never clear a stale `kipi/reviewer-approved=FAILURE`.

## Read this before running the reviewer
`pr-review-agent.sh <pr>` WITHOUT `--post` writes the verdict record and posts NOTHING (no commit status, no PR comment, no Linear post): every post call sits inside `if [ "$POST" = "1" ]` at pr-review-agent.sh:1235. Two approvals were lost that way today. `[verified: round-7 run with --post printed "commit status posted: kipi/reviewer-approved=failure on f9af3dd5"; rounds 3 and 6 without the flag printed no such line]`. Also: pushing nit fixes after an APPROVE WITH NITS resets the floor status on the new head and costs a full round. Capture nits as spillover, merge, then fix.

## Live sessions at close (all reported committed and pushed)
- **gmail connection**: consulting commitments sources (b5c1d1f2, 03cfbf63, 77e9916d), kipi-system PR #296 (64ba9e32, a9d3780b, c07c9602). Open loops it named: feed the morning-brief mail collector from `needs-reply` (cross-repo dependency, scope it, do not smuggle); commitment book went 40 -> 69 open rows today, pre-write backups in that session's scratchpad. `provenance: imported`
- **alice-c5**: 20 commits on Alice master, tip 69e617c, 201 ahead of a private remote, NOT pushed, founder closed the topic. 135 dirty paths left on founder ruling ("garbage"). Open measurement: does `browser_session.py` still need headful Chrome under `--headless=new`. `provenance: imported`
- **A live kipi-system session owns the primary checkout** (`fix/candidate-draft-one-definition`, 21 commits ahead of its remote, working PR #298 from `/Users/assafkipnis/projects/kipi-wt-instrument`). Sana's sweep stopped mutating there after one park. `provenance: imported`

## Why the Notion board was empty this morning, and the fleet shape behind it
The installed job runs the brief out of the PRIMARY dev checkout, which is on a feature branch with no board writer. `[verified: ~/Library/LaunchAgents/com.kipi.morning-brief.plist ProgramArguments -> /usr/bin/python3 /Users/assafkipnis/projects/kipi-system/q-system/.q-system/scripts/morning-brief.py, no WorkingDirectory; that checkout on fix/candidate-draft-one-definition, 83 ahead / 23 behind origin/main; board_rows.py and consulting_board.py absent there AND on origin/main]`. So "merged to main" is not "delivered" for any job pointed at that checkout. The brief's owner (gmail session) is repointing morning-brief at a main-tracking worktree with a pull step. Fleet-wide: 14 loaded com.kipi jobs, 22 consulting jobs (DEC-28, production runs the branch, decided), 6 loaded cole jobs all execute from dev checkouts on feature branches. `[verified: plistlib over ~/Library/LaunchAgents + launchctl list, 2026-09-04 08:4x]`. Captured as **sp-ed6860e6** with the fix shape (per-repo main-tracking worktree; launchd-health asserts executing branch == main or declared production branch). `provenance: observed`

## Real work found by the sweep, not tidy-ups
- **Browser record lane exists in two places with disjoint strengths**: `kipi-wt-land-bl` has the `assert_fetchable` guard but zero tests; the primary's parked stash has 6 `test_c6_*` tests but no guard. The merge needs both. `provenance: imported`
- **kipi-system primary `capability_manifest.py` is an OLDER variant than main** (lacks PR #285's ADD-collision and gone-fragment guards). Committing it would regress. Leave; resolves when the branch takes main. `provenance: imported`
- **Alice stash@{0}** (Sana's backfill-classify) is real: 19 item directories with no source.json across case-001/002, silently passed by the walker. Kept, labelled, needs a test before applying. `provenance: imported`

## Method notes
- Six rounds of one finding class = the fix SHAPE is wrong. Structural or park by round two, cap in the brief before dispatch. Written to memory as `feedback-same-finding-twice-go-structural`.
- A monitor that greps a review transcript for `VERDICT:` is fooled by the same decoys the parser is; I killed one agent on that false signal and lost a review round. Read the GitHub commit status per head, never the file.
- The founder's routing rule held again: repo settings on his GitHub account and a peer session's git are Sana's, not his. Fifth recurrence recorded in `feedback_sana_owns_the_build`.

## Tomorrow
Calendar for 2026-09-04: one event, 19:00 "Guinea Pig Cleaning – Lavie" on assafkip@gmail.com. `[verified: morning-brief.py run_claude with list_events on calendarId assafkip@gmail.com, week 2026-09-01..08 -> 9 events incl. this one; default-calendar read -> 0]`. This session's own connector binding is expired (session-level; the fresh headless sessions the brief uses work fine). `provenance: observed`

**Ownership (founder, 2026-09-04): the morning brief has ONE owner, the "gmail connection" session (PR #296).** My PR #299 (sana/morning-brief-all-calendars, ASK-1235) finishes its review round and is NOT merged by me; that session lands #296 then merges #299 behind it. `[verified: git merge-tree --write-tree origin/feat/consulting-morning-board origin/sana/morning-brief-all-calendars -> 0 conflicts at 02ae6db3]`. No further edits to morning-brief.py from this session. `provenance: explicit_statement` Final state handed over: head 63f6cc78, round-two verdict REQUEST CHANGES with one major (calendar list taken from the model's rewritten JSON instead of the raw list_calendars tool_result; the fix is reading tool_result blocks in `_parse_stream_json`), executed calendarId verification is in and sound, merged-tree suite against #296 green. `[verified: agent report; pr-reviews/codex/assafkip_kipi-system__pr-299-20260904-080927.md; merge-tree rc 0 at 63f6cc78, scratch merged tree 80 passed]` `provenance: imported`

**Defect found doing that, captured as sp-57823aef, Sana dispatched 2026-09-04 with a reproducer-first brief:** `collect_calendar` reads only the default calendar, which is empty; every event lives on the two named calendars, so the brief's calendar section has been printing nothing on days with events. `[verified: list_calendars -> 3 calendars, none primary; default week read -> {"events": []}; named read -> 9 events]`

---

# Session 2026-09-03/04, kipi-system instrument-discipline (Sana). Closed clean. `provenance: observed`

**Ask:** case-004 in Alice, five instrument defects in one day (a measurement never pointed at a known answer), lesson existed, did not arrive. Evaluate three candidates, build what survives.

### Shipped
- **PR #298 merged to main as 03127eab.** `instrument-lint.py` (PostToolUse on `investigation/findings/*.md` and `output/analyses/**`: a null-shaped claim needs a control LABEL; basename date or git add-date before 2026-09-04 exempt), 56-check reproducer, paths-scoped rule `instrument-discipline.md` with enforcement block, pairing-list entry, both settings files wired. Two Codex rounds applied, reviewer verdict APPROVE WITH NITS, auto-merged. `[verified: gh pr view 298 -> MERGED 2026-09-04T04:04:36Z; test_instrument_lint.py -> all green; fleet over instance-registry.json -> 246 in-scope, 0 red]`
- **Fleet sync from main applied by the founder** from a clean clone (primary checkout is on a feature branch; its local `main` was moved to origin/main after proving all 12 extra commits live on origin/fix/candidate-draft-one-definition). 24 instances updated. Alice has lessons-inject.py, its wiring, instrument-lint, and the rule. `[verified: grep -c lessons-inject / instrument-lint in Alice .claude/settings.json -> 1 each; rule file present]`
- Candidate A (ledger `control` field) REJECTED: case-004 wrote 0 ledger rows. The trigger-eval fixture was built then REMOVED: a paths-scoped rule never loads under skill-trigger-eval, so it measured the un-ruled model.
- Public mirror github.com/assafkip/voice-loop restored at 5f67594 after I pushed it from skeleton main (13f4a2c) for about an hour with `zscores` missing. `[verified: git show 5f67594:voiceloop/fingerprint.py | grep -c 'def zscores' -> 1]`

### consulting is HELD OUT of the fleet sync, on purpose
Its voice engine is ahead of every kipi-system branch (`fingerprint.zscores`, 5 call sites in pipeline/voice.py; absent on main, sana/voiceloop-draft-hook, fix/candidate-draft-one-definition). The sync's rsync --delete overwrites it and its suite errors. `[verified: grep -c 'def zscores' on each branch -> 0,0,0; consulting HEAD -> 1]`. The voicekit -> voiceloop rename IS done there (86d102b5, all 5 pre-commit checks green), four defects deep: cache-only package shell, a Friday-only red test, the migration rewriting the mirror's own rename table, then the engine mismatch. Memory: `project_consulting_engine_ahead_of_skeleton`. Two unstaged edits in consulting (`pipeline/voice.py`, `voice/exemplars.jsonl`) are NOT mine; left alone.

### Linear, all with DoR and owner:sana
ASK-1238 port consulting's engine into the skeleton (p2, the real finding) · ASK-1239 migration script: cache-only dir is not a package, rename table must not rewrite itself · ASK-1240 investigation flow writes ledger rows · ASK-1241 wire Alice's dead findings-verify-hook · ASK-1242 trigger-eval seeds a path for paths-scoped rules · ASK-1243 capability-gate check-only vs full mode disagree in consulting-kipi. Spillover ledger for this work: empty (sp-3a2bbc88 voided with evidence; six promoted). `[verified: spillover-promote.py output for each id -> status promoted]`

### The scar worth keeping
My first blast-radius measurement ran 4_points over a path that does not exist, returned zero in-scope files, and I read the zero as clean. Scar shape 5 from the brief, reproduced while building the gate for it. Recorded in the lint docstring, the rule, and `feedback_fixtures_from_producers` (third instance).

### Nothing pending. No background tasks. Scratch clone of main at the session scratchpad is disposable.
