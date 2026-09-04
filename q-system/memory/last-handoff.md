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

**Defect found doing that, captured as sp-57823aef, Sana dispatched 2026-09-04 with a reproducer-first brief:** `collect_calendar` reads only the default calendar, which is empty; every event lives on the two named calendars, so the brief's calendar section has been printing nothing on days with events. `[verified: list_calendars -> 3 calendars, none primary; default week read -> {"events": []}; named read -> 9 events]`
