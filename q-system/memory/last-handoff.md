# Last handoff — 2026-08-06

Tracking **ASK-402** (related: ASK-363, ASK-287). Two sessions in one day; this
doc covers both. Every number carries its provenance on its own line. Anything
marked `imported` came from a subagent's report and was NOT re-run by me.

## Session 1 — the adversarial sweep

A research doc on "adversarial AI code review" was pasted for comparison against
prd-os. My first review concluded "we already have that" — wrong, because it
compared architectures by READING. Everything below came from EXECUTING the
system in virgin repos instead.

| PR | What |
|---|---|
| #111 | **P0 data-loss.** `kipi update`'s rsync `--delete` could remove `my-project/`, `memory/`, `canonical/`. `kipi-update-deletion-guard.py` reads what rsync actually plans to delete and refuses. [verified: ran a real `kipi update` against a fixture — without the guard `my-project/current-state.md` and `memory/last-handoff.md` were DESTROYED; with it, refused and intact] |
| #110 | prd-os delivers what it promises: `/prd-os-init` writes the `.gitignore` entry it claimed, `archive` consults spillover, receipts are computed not stamped. Plus `test_virgin_repo_lifecycle.py`. [verified: most new checks RED against the pre-change tree] |
| #112 | `grep -c ... \|\| echo 0` is not a zero-safe count [verified: `grep -rn` across `test/*.sh`]. Plus `spillover reclassify`. |

## Session 2 — what shipped <!-- pin -->

**PR #114 MERGED** — `7aa9cdd3` on main [verified: `git cat-file -e origin/main:q-system/.q-system/scripts/test/test-review-degraded-provenance.sh` returns 0]. The verdict record now names the model that ACTUALLY wrote the review. This was orphaned work: commit `b40b360c` sat in a worktree with no PR, absent from main [verified: `git cat-file -e origin/main:<path>` → fatal, does not exist], found by sweeping all 10 `.claude/worktrees` for unmerged commits.

**Open PRs, none merged, all behind the GitHub Actions outage:** #113 (this doc), #115 (deletion-guard docstring), #116 (dead dry-run guard + 2 lessons), #117 (`--dry` false failures), #118 (restore message names the kind), #119 (independence spec, no code) [verified: `gh pr checks <n>` on each — only #114 has a green `validate`].

**8 worktrees removed**, founder-authorized [verified: disk check after; only `judgment-compiler` and `opus-fallback` remain under `.claude/worktrees/`].

## The defect class, now with five instances <!-- pin -->

**Code that RECORDS a claim it never COMPUTED** [provenance: explicit_statement, session 1]. Session 2 found it five more times, and the last one is the hardest:

1. `INSTANCE_OWNED` — a *name* allowlist deciding what counts as founder data
2. `[ "$DRY_RUN" != "1" ]` at `kipi-update.sh:1207` — `DRY_RUN` is only ever `--dry-run`, so the comparison can never be false. A guard preventing nothing. [verified: fixed in #116 with a test that makes the comparison able to be false]
3. `model_rsync_excludes()` — a directory named `build` *assumed* to be a build cache; `design-room/build/` is authored output. Made `--dry` report false failures. [verified: fixed in #117; pre-fix mutant goes RED on the exact phantom deletion]
4. `"restored untracked: <path>"` — a generic message printed for tracked files too. **It names a git state the code never computes.** [verified: fixed in #118; the fixture confirms the tracked file is still tracked afterwards, so the message's claim is checked by the run that prints it]
5. **`no-orphan-findings.md`'s backstop covers one of two findings systems.** The rule says a `deferred` disposition auto-creates a spillover item *(findings_writer)*. True — and false at the ISSUE level, where `issue_findings.py` had no fan-out. [verified: `deferred finding-2, finding-8, finding-9` → `defer-* items: []`. `finding-8` had no item and would have vanished at closeout.] Fixed in both systems [provenance: imported — Sana; 5/5 mutants killed, 744 passed].

Instances 1-4 are statements that don't match their code. **Instance 5 matches its
code exactly and still misleads**, because the reader supplies the generalization.
That is the harder failure and the one to watch for.

## What the ledger work established <!-- pin -->

The founder's complaint was "557 spillover items sit at the `minor` default" [provenance: explicit_statement].
Three reframings, each by measurement:

- **The approved baseline plan was withdrawn**, not deferred. A baseline written today makes pre-existing debt exit-neutral, and every open blocking item pre-dates it — so landing it would green the gate over all of them at once. A third exit from the ledger next to fixed and voided. [provenance: imported — Sana]
- **Automated candidate-voiding is a rounding error.** Across 571 open items: 466 name files that exist, 24 partial, **3** name files absent everywhere, **77 name no file artifact at all** [provenance: imported — Sana's extractor, which it corrected for a 25% error rate in the deciding bucket before reporting]. The 77 is the inflow-gate population and it is 25x the outflow one.
- **The real shape: automated inflow, manual outflow.** The ledger went 574 → 578 → 581 → 590 open during one session's work [provenance: imported]. The stock is a symptom. Filed as `sp-1e6af115` with the proposal marked as a proposal, including *gate the rate, not the level* — a gate on the total is permanently red, which teaches everyone to step over it.

**Blocking items: 14 at session start → 11 now** [verified: `prd_runner.py gates run`], but 6 of the current 11 were
filed *today* by this work, so pre-existing went **11 → 5** [verified: same command; each removal carries the command that proved it dead].

## Lessons filed to the corpus (not left in chat) <!-- pin -->

- `a-broken-checker-that-fails-loud-is-luck-not-diligence.md` — a BSD-grep empty alternation exited non-zero and was read as "illegal value", flagging all 8 comparisons including the 7 correct ones. Caught only by reading stderr instead of the verdict.
- `a-basename-is-not-a-fact-about-what-a-thing-is.md` — instances 1, 2 and 3 above. If the same shape appears three times in one component, the component has a habit, and the habit is the defect.
- The state-claim rule: **a state named in a log line, docstring, comment or report is a CLAIM, not an observation — measure it before filing a defect about it.**

## What cost us the most, twice each

**Unmeasured claims relayed upward.** Three reached the founder as fact and were
retracted within the hour.

- A "silent de-tracking across live instances" that does not happen [verified: the restore loop runs BEFORE the sync staging in `kipi-update.sh`, so the file is back with content identical to HEAD and git sees no change].
- A "skeleton-shipped plugin outside version control for months" [verified: the skeleton has no such plugin at all — not tracked, not on disk].
- An "uncommitted backlog" that is actually an intermittent race between generator jobs and their commits [verified: only 4 files actually block, not 91; `feed.xml` alone carries 35 commits in 90 days]. All three came from a **plausible pattern**, not
carelessness. A pattern is a hypothesis; one confirming check costs less than a
relayed claim.

**A mutation harness that cannot run its mutants reports perfect survival.** Three
"surviving" mutants were all bad mutants — two semantically equivalent, one
anchored on an 8-space line that is a substring of a 16-space line earlier in the
file, so it mutated a different function [provenance: imported]. *Validating a
mutant is on disk is not validating it landed in the right place or changed
behaviour.*

**The ceiling on "watch it fail" is the set of mutants you can imagine.** Four
mutants on #114 were well-chosen and all four were killed [provenance: imported]. The degraded fallback
reviewer ran five, and the fifth survived at 8/8 — the `ENGINE=claude` branch had
zero coverage, so deleting it left the suite green while printing the message
claiming the record distinguishes them [verified: reviewer's reproducer,
reproduced in the PR]. A second reader is the only thing that raises that ceiling,
degraded or not. **Parking that review until Codex returns would have shipped a
test with a hole in it.**

## Gates that held against their own author <!-- pin -->

Worth recording, because it is the evidence they are real:

- `mark reviewed` REFUSED, demanding `complete-review` with hashed evidence. The blocker is executable: `plugins/kipi-dsse/scripts/issue_runner.py` computes the receipt and exits nonzero without the evidence hashes [provenance: observed].
- The instruction-budget ratchet blocked a commit that duplicated a scar narrative into an always-on rule. **Rules carry the rule; code carries the story.**
- `prd_split` refused a hand-written issue spec (*"marker not generated by prd_split.py"*). The work shipped OUTSIDE the DSSE wrapper with the gap named, rather than forging a marker. Re-wrapping through a real Linear issue is in flight.
- The destructive-op hook blocked an `rm -rf` in a mutation harness; the cleanup was dropped rather than a bypass requested.

## Environment

- **Codex down until 2026-08-09 18:53** [verified: real billed `codex exec` → "You've hit your usage limit ... try again at Aug 9th, 2026 6:53 PM"; read the output, not the exit code]. Every review this session ran DEGRADED on the claude fallback. Re-run list in `sp-0b8fbea6` and `sp-80a93612`.
- **GitHub Actions major outage** all session [verified: `githubstatus.com/api/v2/components.json` → `Actions: major_outage`]. The tell was in run metadata, not logs: jobs ran exactly 15m0s with **zero steps recorded** and `log not found` — a job recording no steps never got a runner. `environmental-trigger` class: stop on attempt 1, surface, do not retry. Only #114's `validate` has gone green.

## Founder decisions this session <!-- pin -->

- **Remove the 8 landed/empty worktrees.** Done.
- **Voice-DNA stays public, deliberately** [provenance: explicit_statement]. Supporting measurement [provenance: imported — Sana's shingle probe]: the public `founder-voice` references are 99.5% identical to the private untracked copy, 0 placeholders, public since the marketplace migration; repo is PUBLIC with 98 stars and 21 forks all created after that date [verified: `gh repo view`], so a history purge reaches origin only. `sp-f1148dc6` VOIDED as founder-directed. **Do not re-raise as a leak.**
- **Podcast generation stays running.** The 2026-08-01 audit disabled the three *reporting* jobs; the two *generating* jobs were never paused and have published daily since [verified: `launchctl print-disabled`]. That was the intent. Memory `project_jobs_audit_2026_08_01.md` CORRECTED — it previously asserted the podcast was paused. **Settled; do not re-raise.**

## Open, nothing blocked

- **finding-10 `scs-severity-provenance`** is next: `severity_source: default|explicit` at write time, and the gate's REPORT line split into assessed vs never-triaged. Motivated by the 77-item measurement. A triage rule cannot key on a field indistinguishable from its default; **1 of 570 items has ever been reclassified** [provenance: imported].
- **5 PRs need green runs** before anything merges. Nothing was force-merged.
- **The commit chokepoint** for `gtm-partner` / `ASK_AI_consultant`: generator jobs dirty their own trees and the updater refuses on tracked changes. Writers named (`build_rss.py`; `notify.py`/`daily.py`/`surface_report.py` for `latest.txt`). Design is ONE commit call in the orchestrator, not three at the writers. Unbuilt on purpose.
- **Alice still refuses updates** [provenance: imported — Sana]. Her evidence items were committed (219 files, pathspec-limited, 0 staged outside the tree) but two tracked modifications remain and they are real in-progress work, not exhaust.
- `sp-2c7e5819` — **a launchd job's paused/running state has no verification anywhere.** Nothing asserts the enabled set matches the intended set. Wants an intended-state manifest diffed against `launchctl print-disabled`, same shape as the capability manifest.
- `sp-cc2de280`, specced in PR #119 [provenance: observed] — `degraded` encodes the CAUSE ("codex was asked and failed") while consumers read it as the PROPERTY ("not independent"). `independent` must be **derived and recomputed**, never stored.

## Working agreement (unchanged, re-confirmed) <!-- pin -->

- **Sana owns the build.** Engineering decisions route to Sana. Founder authorizes publish / spend / delete only. Held all session: three things that looked founder-shaped dissolved into ordinary work under two cheap checks.
- **Do not stop at a boundary.** Held: "Codex is down" was not a blocker, "unmeasured" was not a zero, "founder-gated" applied to the delete and not to assembling the evidence for it.
- **Do not commit to a branch under active review.** A push after a review invalidates the reviewer status and costs a re-review [verified: the new head commit carried no statuses at all, and `kipi/reviewer-approved` is a required context]. Batch fixes before re-firing.
- **Search `.prd-os/prds/` before proposing.** Three times this session the approved plan already contained the answer. Re-read it at each increment boundary, not once at the start.
- **One worktree per agent.** A subagent switched the shared worktree's branch mid-session and reverted this file to a July copy under me. Nothing was lost [verified: `docs/handoff-2026-08-06` intact at `d6a44ecc`; Sana's work pushed at `9feb831e`], but write from your own worktree.
