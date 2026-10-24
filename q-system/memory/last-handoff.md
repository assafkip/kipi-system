# Session handoff, Oct 23 to 24 (openwitness video, brag repo in Sana's queue) [verified: date]. READ THIS FIRST.

## Done

- openwitness product video v7 APPROVED ("this works") [provenance: explicit_statement]. File `~/Downloads/openwitness-v7-will.mp4`; project `~/projects/openwitness/video` (own git), ruling 42. Voice ElevenLabs "Will" on eleven_v4; 2,320 characters used [provenance: observed, plan.md spend log].
- The brag skill repo is a dispatch-enabled instance. kipi-system#558 (registry row) merged after the fleet reviewer's APPROVE WITH NITS; assafkip/brag#1 (fleet layer seed) merged by the founder's one-time --admin merge; brag main protected, kipi/reviewer-approved required, admins included [verified: gh pr view 1 and 558 MERGED, gh api protection admins=true].
- `repo-preflight.sh ~/projects/brag-fork https://github.com/assafkip/brag.git` prints OK, exit 0 [verified: ran it 20:31Z].
- ASK-3036 (brag pace and readers checks) is in Sana's queue: label owner:sana, Linear project brag (P-ASK-78), Definition of Ready, Backlog, no assignee [verified: worker dry run printed "[dry] would work ASK-3036 (attempt 1/3)"].
- Filed ASK-3042 for Sana: pr-review-agent.sh exits 9 on a PR over 300 files [verified: brag PR 1 review log, HTTP 406].
- Memories: reference_sana_in_linear, project_brag_dispatch (new); project_openwitness, feedback_voice_is_kokoro, feedback_reference_is_vocabulary [provenance: observed].
- Plan with outcomes: `q-system/output/plans/brag-dispatch-onboarding-2026-10-24.md` [provenance: observed].

## Open, all in files

- Founder: openwitness separation key. Command in memory project_openwitness; CI `separation` stays red until it runs [provenance: observed].
- Founder, optional: the scoped skeleton sync into brag waits on `kipi-approve 9d2d466710bf9ca3e172eb062ad411d3faf39e8ebe10a33fa4c973636ac47160`. The next fleet sync applies the same 2 changes (.gitignore managed block, settings.json rewrite) [verified: dry run, Updated 1 Failed 0].
- Founder: 4 open loops (claude-guardrails #14, i-have-adhd #124, Gemini credits, Apify stills store) [verified: open-loops.py --report lists 4].
- Ask before switching /say to Kokoro (feedback_voice_is_kokoro).
- Sana: ASK-3036, ASK-3042, openwitness ASK-2953 to ASK-2957.
- The shared kipi-system checkout's main is 8 ahead and 2 behind origin/main from other sessions' auto-commits, so kipi-update.sh aborts from it [verified: git rev-list --left-right]. Not touched.
- MEMORY.md is at 24KB of the 24.4KB read limit [provenance: observed, hook report]. Not compacted.
- Google Calendar MCP session expired at wrap; tomorrow (Sunday Oct 25) not checked [verified: list_events error].

## Dead ends, do not retry

- Setting Sana as assignee or delegate through the Linear MCP: "One or more app users lack the required capability" [verified: save_issue, 3 attempts]. The label owner:sana is the route.
- kipi-update.sh on a repo with no q-system/: "instance prefix is missing". Seed with kipi-new-instance.sh [verified: dry run].
- ElevenLabs eleven_v4 ignores voice_settings.speed; slow lines with ffmpeg atempo [provenance: observed].
- `timeout` is not installed on this Mac [verified: which timeout gtimeout].
- `gh` in a fork checkout resolves PR numbers against the upstream repo; `gh repo set-default` first [verified: "Could not resolve to a PullRequest" before, merge queued after].

---

# Session handoff, Oct 23 (brag review, claudemy launch video) [verified: date]. (previous)

No code in this repo changed this session except the memory files below; git is untouched [provenance: observed].

## Done

- Reviewed github.com/latent-spaces/brag (skill + code) for dev-tools. Verdict given: do not install. Its first draft read generic and the look the founder wanted was beyond it [provenance: observed]. Founder then moved the work to a separate Sonos-style video.
- Claudemy launch video APPROVED by the founder ("keep this is good") [provenance: explicit_statement]: `~/projects/claudemy-video/sonos-cut/claudemy-sonos-cut-v3.mp4`, 28.1s [verified: ffprobe format=duration], copy in ~/Downloads.
- Rebuild with no API spend: `bash ~/projects/claudemy-video/sonos-cut/rebuild.sh`. Proven from the new folder: stills matched the delivered video at mean pixel diff 1.42 to 1.53, soundtrack byte-identical [verified: capture.py stills + numpy diff, cmp sonos.wav].
- Every founder ruling and measurement for the video is in `~/projects/claudemy-video/sonos-cut/plan.md` [provenance: observed].
- Spend: 8 Kling/Hailuo clips through the Apify MCP plus 6 gpt-image-2 stills; roughly $23 to $26 from the per-second and per-image list prices {{UNVERIFIED}} (billed totals not checked in the Apify or OpenAI consoles).
- Memories written: project_claudemy_sonos_cut, feedback_video_generic_is_structure, feedback_cut_speech_on_transcript [provenance: observed].

## Open, all in files

- Two founder-only loops added to `q-system/memory/open-loops.json`: `gemini-prepaid-credits-depleted`, `apify-claudemy-stills-store` [verified: open-loops.py --report lists 4 open].
- ASK-2937 (sp-f47d424b, owner Sana): kipi-design dogfood gate blocks any .html in a Claude Code scratchpad; repro exits 2 [verified: plugins/kipi-design/hooks/dogfood_gate.py on a scratch copy].
- MEMORY.md index is near its read limit, 22.9KB of 24.4KB per the hook's own report [provenance: observed]; not compacted this session.

## Dead ends, do not retry

- Gemini image models: HTTP 402 "prepayment credits are depleted" on gemini-3-pro-image, gemini-3.1-flash-image, gemini-2.5-flash-image [verified: generateContent calls].
- Sora 2 API: model record shows shutdown_date 2026-09-24 and /v1/videos returns 404 [verified: curl /v1/models/sora-2 and /v1/videos].

---

# Session handoff, Sep 1-2 (morning-brief Phases 2-4 as two prd-os PRDs) [verified: git log]. (previous)

Branch `prd/morning-brief-learns` in worktree `~/projects/kipi-wt-prd-mbl`, base `ddad93b1`, 61 commits [verified: git log --oneline ddad93b1..HEAD | wc -l]. Nothing pushed, nothing merged: git is Sana's.

## What shipped

- PRD A `prd-morning-brief-learns-2026-09-01`: 14 of 15 issues CLOSED, issue `mbl-board-live-readback` cleared not closed (needs `~/.config/kipi/notion-token` + `notion-board-page`, founder action). Archive refuses until that close receipt exists [verified: prd_runner.py archive].
- PRD B `prd-lessons-rail-and-up-rail-2026-09-02`: 14 of 14 issues CLOSED, every one RED-first, mutation-proven, reviewed twice (Codex; Claude subagents stamped `claude-review`/`claude-adversarial` when Codex was at capacity on issues 7 and 9) [verified: .prd-os/receipts.jsonl]. Archive refused by `gates run`: 52 blocking spillover items, 50 inherited, 2 this PRD's by design (sp-f09ac9e1 Sana dispatch, sp-193c5e93 plan-file paste) [verified: prd_runner.py gates run].
- New: `lessons_streak.py` (atomic streak + escalation ledger), `lessons-daily.sh` seams and Nth-failure escalation, `lessons_recall.py --corpus/--both`, `install-lessons-daily.sh` skeleton-only + `com.kipi.lessons-daily.plist` template, `install-plist.sh --all` honours `kipi-scope: skeleton-only`, `trigger-inventory.py` + `stages-exempt.json`, `kipi promote` (`kipi-promote.sh`: containment, scrub from registry + clients.json + `tripwire-terms.txt`, two-phase receipts bound to blob AND base under one lock, `--candidates`, `--void`), `kipi-push-upstream.sh` guard honours matching done receipts read at FETCH_HEAD only and refuses instance-side receipt edits, `q-system/.q-system/promotions.receipts` (NOT .jsonl: gitignored fleet-wide), the weekly drift reporter script + `com.kipi.lessons-drift.plist` + `drift-hubs.json` (the reporter's file name is deliberately not spelled here: its single-caller test pins the plist and the test as the only two tracked files naming it).

## Notion (founder-directed 2026-09-02, after the PRDs) [provenance: observed]

- Integration `kipi`; token at `~/.config/kipi/notion-token`, board page id at `notion-board-page`, lessons database id at `notion-lessons-db`. Content access granted to the Morning board page and the three databases below.
- Morning board page `<notion-page-id>`: four sections (Top of Mind gallery, This Week, Inbox, Lessons) as linked views, laid out like Bloom's task board. The 07:00 writer still writes bullets under headings there: sp-d351fa8c (redesign it to write Kipi backlog rows).
- Databases: `Kipi build log` `<notion-db-id>` (one row per issue/PRD closed), `Kipi backlog` `<notion-db-id>` (Bucket/Priority/Size/Source), `Kipi lessons` `<notion-db-id>` (the corpus mirror).
- `lessons_notion_sync.py` upserts every corpus lesson by id; wired into `lessons-daily.sh` after publish, non-fatal; first live run created every corpus row [verified: lessons_notion_sync.py output]. Status/Notes columns are the founder's and are never rewritten.
- Stray Chrome-created "Morning board" page `<notion-page-id>` is the founder's to trash (deletions are founder-only).

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
