# Session handoff, Sep 1-2 (morning-brief Phases 2-4 as two prd-os PRDs) [verified: git log]. READ THIS FIRST.

Branch `prd/morning-brief-learns` in worktree `~/projects/kipi-wt-prd-mbl`, base `ddad93b1`, 61 commits [verified: git log --oneline ddad93b1..HEAD | wc -l]. Nothing pushed, nothing merged: git is Sana's.

## What shipped

- PRD A `prd-morning-brief-learns-2026-09-01`: 14 of 15 issues CLOSED, issue `mbl-board-live-readback` cleared not closed (needs `~/.config/kipi/notion-token` + `notion-board-page`, founder action). Archive refuses until that close receipt exists [verified: prd_runner.py archive].
- PRD B `prd-lessons-rail-and-up-rail-2026-09-02`: 14 of 14 issues CLOSED, every one RED-first, mutation-proven, reviewed twice (Codex; Claude subagents stamped `claude-review`/`claude-adversarial` when Codex was at capacity on issues 7 and 9) [verified: .prd-os/receipts.jsonl]. Archive refused by `gates run`: 52 blocking spillover items, 50 inherited, 2 this PRD's by design (sp-f09ac9e1 Sana dispatch, sp-193c5e93 plan-file paste) [verified: prd_runner.py gates run].
- New: `lessons_streak.py` (atomic streak + escalation ledger), `lessons-daily.sh` seams and Nth-failure escalation, `lessons_recall.py --corpus/--both`, `install-lessons-daily.sh` skeleton-only + `com.kipi.lessons-daily.plist` template, `install-plist.sh --all` honours `kipi-scope: skeleton-only`, `trigger-inventory.py` + `stages-exempt.json`, `kipi promote` (`kipi-promote.sh`: containment, scrub from registry + clients.json + `tripwire-terms.txt`, two-phase receipts bound to blob AND base under one lock, `--candidates`, `--void`), `kipi-push-upstream.sh` guard honours matching done receipts read at FETCH_HEAD only and refuses instance-side receipt edits, `q-system/.q-system/promotions.receipts` (NOT .jsonl: gitignored fleet-wide), the weekly drift reporter script + `com.kipi.lessons-drift.plist` + `drift-hubs.json` (the reporter's file name is deliberately not spelled here: its single-caller test pins the plist and the test as the only two tracked files naming it).

## Notion (founder-directed 2026-09-02, after the PRDs) [provenance: observed]

- Integration `kipi`; token at `~/.config/kipi/notion-token`, board page id at `notion-board-page`, lessons database id at `notion-lessons-db`. Content access granted to the Morning board page and the three databases below.
- Morning board page `3cfbf98c052981bd88e0dc27eaae166f`: four sections (Top of Mind gallery, This Week, Inbox, Lessons) as linked views, laid out like Bloom's task board. The 07:00 writer still writes bullets under headings there: sp-d351fa8c (redesign it to write Kipi backlog rows).
- Databases: `Kipi build log` `7c012a0580554b4197407d0509fe7bbe` (one row per issue/PRD closed), `Kipi backlog` `0a09bd16b12e49bfa792fad15e008ed0` (Bucket/Priority/Size/Source), `Kipi lessons` `7a9d173f9fae442aba69238fa81acec4` (the corpus mirror).
- `lessons_notion_sync.py` upserts every corpus lesson by id; wired into `lessons-daily.sh` after publish, non-fatal; first live run created every corpus row [verified: lessons_notion_sync.py output]. Status/Notes columns are the founder's and are never rewritten.
- Stray Chrome-created "Morning board" page `3cfbf98c052980c6a30cf744535cb37c` is the founder's to trash (deletions are founder-only).

## Landing steps (Sana, in this order)

1. Merge `prd/morning-brief-learns` (61 commits [verified: git log --oneline ddad93b1..HEAD | wc -l]; pre-commit gates green on every one [provenance: observed]).
2. In the main checkout: `bash q-system/.q-system/scripts/install-plist.sh com.kipi.weekly-improve`, `... com.kipi.lessons-drift`, `bash q-system/.q-system/scripts/install-lessons-daily.sh` (refuses from a worktree by design), then `launchctl kickstart` each and record the launchd fact for sp-f09ac9e1's sibling note.
3. Paste scratchpad `plan-2h-2i-section.md` (also in commit `02847a32`'s message [provenance: observed]) into `q-system/output/plans/morning-brief-overhaul-2026-08-30.md` above "Promotion rule for this register"; resolve sp-e7a50229 and sp-193c5e93.
4. Fix the PRD B body wording captured as sp-5c3e4776 (receipts file name) and sp-b9a4625d (the override is never honoured), then archive PRD B; archive PRD A after the founder's Notion credential lands and `mbl-board-live-readback` closes.
5. Decide the 9 consulting candidates: `KIPI_PROMOTE_SKELETON=<skeleton> bash kipi-promote.sh --candidates --instance ASK_AI_consultant` (live output saved as `.prd-os/issues/lr-promotion-candidates-status.live-run.txt`).

## Open captures from this session (all in `.prd-os/spillover.jsonl`)

sp-f09ac9e1 (3a Sana dispatch: fan-out aborts on a non-main skeleton HEAD), sp-636e91cf (--both lists a shared lesson twice), sp-44930c1d + sp-bc5a7fc1 (stale doc lines), sp-7c45ccee (inventory cannot see glob-invoked tests), sp-24aa7ebe (the inventory has no trigger of its own), sp-57cd7332 (push guard skips its deletion check when the instance has no lessons), sp-5c3e4776 + sp-b9a4625d (PRD B doc drift).

---

# Session handoff, Aug 30 overnight [verified: date]. (previous)

## What shipped

Twelve PRs merged to origin/main [verified: git log --oneline origin/main -12].
Merged: 269, 277, 278, 283, 282, 284, 264, 253, 276, 258, 252, 198 [verified: git log --oneline origin/main -12].
The three the brief named as DIRTY are all in.

- 269 voiceloop rename + the converged verify floor, nine review rounds [verified: ls ~/.config/kipi/pr-reviews/codex/*pr-269*].
- 277 lessons-inject. It had never delivered a lesson [verified: probe_hook_envelope.py].
- 278 voiceloop-band-lint. Same class: writing to a channel nobody reads [verified: gh pr view 278].
- 283 ASK-1129, root pytest fleet-wide. 282 and 284, the backlog sweeper [verified: gh pr view 283].

## The two findings that matter most

**A UserPromptSubmit hook needs `hookEventName` or its payload is discarded.**
Measured, not inferred. Three headless `claude -p` sessions, a unique marker in
each, and a positive control that had to pass before the other arms counted
[verified: python3 q-system/.q-system/scripts/probe_hook_envelope.py].

    nested WITH hookEventName        -> delivered
    nested WITHOUT hookEventName     -> ABSENT
    top-level additionalContext      -> ABSENT

The last of those matches the scar already recorded in token-guard.py
[provenance: observed]. The published docs, read back by a summarizer, said the
key was optional. They were wrong, and trusting them would have reverted a
correct fix [provenance: observed]. The probe is reusable.

**Consequence, still open: `voice-dna-loader.py` emits the shape that does NOT
deliver** [verified: grep -n -A3 hookSpecificOutput on that file]. So the
founder's voice DNA has not been reaching the model through that hook, which
downstream gates cannot see because they all measure the output and none check
whether the input arrived [provenance: inferred]. Tracked as sp-e85ff9dc and
sp-c4031c2e. One-key fix. Sweep every `additionalContext` emitter in one pass,
with the probe.

## ASK-1129 is closed

Root pytest went from aborted collection, nothing executed, to a fully green root
run [verified: python3 -m pytest -q --no-header at the repo root].
Counts: 1777 passed, 3 skipped, 0 errors [verified: same command].
The floor can now be armed in the instances that were blocked, though that has
not yet been run in an instance [provenance: inferred].

The brief said one kipi-design test. Measured, it was two files from two causes,
and chasing the numbers found a third [verified: python3 -m pytest --collect-only -q at origin/main].
That third: 8 floor tests that could not go red [verified: the probe module in scratchpad].

## Backlog state

`pr-restack.py` is on main and drains two mechanical conflict classes:
capability-manifest and version-only `plugin.json` [verified: the sweep reports in scratchpad].
The manifest class was the conflict in 35 of 40 DIRTY PRs [verified: restack-dry.txt].
Both resolvers refuse rather than guess, and both refusal branches are tested
[verified: the resolver probes in scratchpad].

Current sweep: examined 22 of 52 open PRs, 22 conflicted, 0 restackable [verified: python3 pr-restack.py].
The mechanical layer is drained; what remains needs judgment.
PR 207 is refused on purpose [verified: capability_manifest.py --add-from on that branch].
It edits a declaration, and the replay tool reads an edit as a removal.
Tracked as sp-6b25c567.

## consulting

Merged and pushed, floor green on 5 of 5 checks [verified: bash q-system/.q-system/verify.sh --full].
The "data decision" in sp-9ebb574b was a false alarm. clients.json, gtm-queue.json
and pipeline-ledger.json differed from main only in timestamps, local newer in
every case, zero rows at risk [verified: a structural diff across HEAD, origin/main and the merge base].

Caught mid-session: the worktree moved the branch ref under the primary checkout,
leaving many paths that auto-commit could have committed as a revert of the merge.
Classified: 4 stale, 28 live job writes, 65 untracked [verified: a per-path comparison against 427530f4 and HEAD].
Refreshed only the stale ones [verified: git checkout HEAD -- on exactly those four paths].

Open and unverifiable: that branch is far ahead of its main with no PR [verified: git rev-list --left-right --count].
A memory says production runs the branch deliberately (DEC-28), but that decision
is not in `decisions.md` or memory [verified: grep over q-consult/canonical/ and q-consult/memory/],
so I acted on neither reading. sp-0edfcad6: write the decision down, or land the work.

## The pattern worth carrying forward

Repeatedly this session a check or a report could not tell "found nothing" from
"looked at nothing", and every instance was in work written minutes earlier
[provenance: observed]. The porcelain assertion that passed against its own
defect. The `!=` that passed against a corpus walk. The import guard green only
because of what was missing locally. Floor tests that could not go red. The
discarded hook envelope. A sweep that under-examined the backlog and printed a
small number [provenance: observed].

Written up as a lesson, merged with 277 [verified: git log --oneline origin/main -12]:
`q-system/lessons/the-author-of-a-fix-picks-the-oracle-the-fix-already-passes.md`.
Its first rule: name the input that makes the assertion RED for the reason you
care about, before writing it.

## Needs the founder (removals only)

Untracked in the kipi-system root: `.rescue/`, `error.log`,
`fix-perm-wildcards.py`, `sana-brief2-report.md`. A stray `.verify-cache/` in the
consulting worktree. Many stale worktrees under `~/.config/kipi/review-trees/`
and `.claude/worktrees/` [verified: git worktree list]. None touched.

## Spillover filed this session

sp-ecb82e8f (tripwire cries wolf on a branch switch) · sp-66e74091 (MCP deny
wildcards, owned by ASK-1144) · sp-e9e3b43a (path guard is direction-blind, and
blocked three honest reads including the attempt to file this) · sp-0f3a664b and
sp-7bd5da63 (kipi-mcp reds, and the scope-measurement correction) · sp-80307e44
(pr-restack declared inert) · sp-947f04c7 (publish_gate skip is coarse) ·
sp-6b25c567 (add_delta reads an edit as a removal) · sp-e85ff9dc and sp-c4031c2e
(voice-dna-loader envelope, now measured) · sp-5a39176b (kipi-mcp tests may run
an installed copy) · sp-ef1ef4cd (coding-cookie claim, needs one fixture) ·
sp-0edfcad6 (consulting branch vs main).
