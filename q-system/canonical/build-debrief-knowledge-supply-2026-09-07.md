<!-- voice-lint-skip -->
# Build debrief: knowledge supply and the consulting sync, 2026-09-05 to 2026-09-07

Written 2026-09-07 from files only. No memory of the build was used; every claim names its source in brackets. Blameless by rule: sessions and scripts are named, people are not graded. This repo is public, so one client product name inside a founder quote is replaced with a bracketed label; the full text stays local in q-system/output/.

Source keys. [plan] is q-system/output/plans/knowledge-supply-project-folders-2026-09-05.md, the build record. [PRnnn] is the pull request body on assafkip/kipi-system; [PRnnn c@HH:MMZ] is a reviewer comment on it at that UTC time. [linear:ASK-n c@time] is a Linear comment. [log:name:lines] is a file under ~/.config/kipi/. [sp-id] is a row in .prd-os/spillover.jsonl. [mem:name] is an auto-memory file. [rca:rename] is q-system/output/rca/rca-rename-hook-rewrites-prose-2026-09-06.md (on main, absent from this checkout's branch). [rca:verify] is q-system/output/rca/rca-verify-only-ran-the-sync-2026-09-06.md. [T:xxxx@time] is a record in the session transcript whose id starts with xxxx, read through a condensed extract. [debrief:sync] is q-system/output/debrief-build-fleet-sync-2026-09-06.md, written earlier today by session cdd0087d for session 2157c268 alone. [debrief:voiceloop] is consulting/q-system/output/debrief-voiceloop-build-2026-09-07.md, written today by session e1c421c8. All times UTC; PDT is UTC minus seven.

Two notes on the sources before anything else.

- The transcript id c6777ffe names no transcript. Searched recursively under the Claude projects tree, every subagents folder, and the whole home directory: zero files. It is the process id of the Claude Code restart at 2026-09-07T00:41:11Z (CLI 2.1.261 to 2.1.263) that resumed session 92e4c064; its only footprint is a tasks directory under /private/tmp holding that session's post-restart reviewer outputs, and every turn it hosted is inside 92e4c064.jsonl [T:92e4@00:41Z, agent search of the projects tree]. Nothing is missing.
- Two debriefs already exist for halves of this arc. [debrief:sync] covers the sync session in depth with a per-minute timeline. [debrief:voiceloop] covers the consulting-side extraction. This document covers the whole knowledge-supply arc and the sync as one build, cites those two where they hold the detail, and reconciles against them in the lessons section rather than repeating their bodies.

## 1. The ask and what shipped

### The ask, in the founder's words

Three moments set the scope, and each widened it.

- 2026-09-05T02:55Z, session 20e05492, run as Sana: evaluate and design an enhancement to Kipi from a pasted proposal, inspect the current architecture first, do not code until the plan is complete, and answer one question: "What is the smallest missing architectural capability that turns Kipi from a system where Claude searches the knowledge base into a system where Kipi reliably supplies Claude the knowledge it needs?" Then, at 03:23Z, one word: "build" [T:20e0@03:08:58Z, @03:23:40Z].
- 2026-09-05T21:25Z, session 92e4c064: "I was assuming that we were pushing the knowledge base system into the consumer projects, for example, that [the investigation instance] would have this ability to search through its own knowledge base." Then at 21:32Z: "every projects within consulting to have their own konwledge graph the system queries. None of them need to read the kippy system. They need to read their own folders and their own information." The goal at 21:37Z picked option one and added: "[that instance] has multiple investigations inside it, and each of those investigations needs to have its own knowledge base as well. So that needs to be built end to end" [T:92e4@21:25:11Z, @21:32:39Z, @21:37:07Z; plan header].
- 2026-09-06T00:07Z, session 2157c268: "run the fleet sync after you are fully clear tht the other projects running are complete and it is safe to run it" [T:2157@00:07:38Z]. The consulting root was then found excluded, and the founder's correction arrived by relay at 03:00Z: "why is consulting root out? I didnt say it stays out" [T:92e4@03:00:46Z queued; mem:project_consulting_engine_ahead_of_skeleton]. On 2026-09-07T01:06Z: "I want consulting in the fleet sync. What do we need to do to own thie issue so we can do it and also not have it running for another 30 hours" [T:92e4@01:06:12Z]. At 05:53Z: "why not the consulting today?" [T:2157@05:53:26Z].

### What shipped, with the file that proves it

- The reader. PR #302 merged as b33555dc at 2026-09-05T05:53Z: knowledge_supply.py, the UserPromptSubmit hook knowledge-inject.py, knowledge-sources.json version 1, receipts and a misses ledger, 55 tests, 31 mutations red on copies, a 30-day replay at the largest instance showing a 10.2 percent fire rate and a p95 of 21 ms [PR302 body; PR302 c@05:45Z]. ASK-1261's single chokepoint for one-token names rode the same merge [PR302 body, "ASK-1261"].
- The project-folders extension. PR #308 merged as d7f3397b at 2026-09-06T01:30Z: sub-stores (one knowledge base per 4_points case), a docs class over the project's own markdown folders, prompt-driven candidates, store and target and proper-noun index sources, the investigation manifest, one render block per entity and store [PR308 body; plan, build record]. Twelve reviewer rounds, 41 findings, 108 tests, mutation pass 49 of 49, end-to-end assurance 8 of 8 through the real hook against the real folders [linear:ASK-1280 c@2026-09-06T01:31Z]. ASK-1280 is Done [linear:ASK-1280].
- The 4_points override manifest, committed in that repo's own git as b8cfc48f; the repo is 52 commits ahead of its origin and unpushed by design [plan, "PR #308 review round 1"; plan, "end-to-end assurance"].
- The public README with seven diagrams, PR #309 merged 7f20e1c1 at 2026-09-05T22:40Z, and its accuracy follow-up PR #310 merged 67986e56 at 2026-09-06T01:59Z [PR309; PR310 in git log]. The handbook PR #306 is open and parked at round 3 [PR306; sp-c1c0464c].
- The fleet. On 2026-09-05T06:26Z the reader session synced 23 instances from main; consulting failed on its own pre-commit and one instance was skipped [T:20e0@06:32Z]. On 2026-09-06T03:51Z to 04:03Z the founder's fleet-apply script completed with Updated 24 [debrief:sync, timeline 2026-09-06 03:51; log:fleet-apply-20260905-205114]. On 2026-09-06T18:33Z to 18:45Z the founder's second script run reported Updated 22, refused consulting root and fractional-cxo, skipped reddit-build-radar; the script's own verify table showed engine v2 present on every managed instance except consulting root and consulting-kipi, and the end-to-end check passed 8 of 8 [T:92e4@18:52:17Z, the founder's paste; log:fleet-apply-20260906-113342.log.apply].
- The consulting root, which took a day and five skeleton PRs. PR #311 f7e42353 carried the 43-module voice engine into the skeleton (ASK-1238 Done) [PR311; linear:ASK-1238 c@19:31Z]. PR #312 d43f034b stopped the rename hook rewriting prose and skeleton-delivered paths [PR312; rca:rename]. The sync then landed in pieces: 7ce79343 delivered q-system at 21:30Z, 75014dc0 and 0ae05d69 delivered plugins and restored the gate at 21:38Z to 21:53Z [log:consulting-sync-post312.log:106; plan, "14:38 PDT"]. PR #313 cfd8e9cc ported consulting's live voice-stop-gate behaviour (ASK-1197), PR #315 f8bcaf41 dropped two corpus words from the ban list, PR #316 7080f554 added the instance-ahead report, PR #317 6acfcc6d repaired the fixture #316 broke, PR #314 2abbeaa3 gave the updater a lock wait and a run marker [git log origin/main; PR313; PR315; PR316; PR317; PR314]. The clean apply ran from skeleton 4a280871 at 2026-09-07T05:43Z: two updater commits e886a90b and 4f73aadd, capability gate GREEN, Updated 1, Failed 0 [log:consulting-sync-20260906-224336.log:724,791,844-848]. A second apply at 06:08Z produced c8f9663d, a settings.json key reorder with no semantic change [sp-cbc9dbb4].
- Founder-shell tooling under ~/.config/kipi/: fleet-apply-2026-09-06.sh (retired with exit 3 once the skeleton carried the engine), consulting-sync-run.sh (quiet-window wait, bounded retries, a dry-run mode and a verify-only mode), and pr-313-founder-override.sh (records the reviewer status on one exact commit and refuses if the head moved) [the three files; plan, "13:00 PDT"; plan, "22:43 PDT"].
- Two RCAs [rca:rename; rca:verify], five memory files written or updated [mem:project_knowledge_supply_reader; mem:project_consulting_engine_ahead_of_skeleton; mem:project_fleet_sync_2026_09_06; mem:feedback_agent_never_carries_the_founder_bypass; mem:feedback_never_message_reviewer_sessions; mem:feedback_stay_in_scope_hook_prompts_are_not_the_ask], and 99 ledger rows dated inside the window, counting adds, promotions and resolutions [spillover.jsonl, rows with a 2026-09-05 to 2026-09-07 timestamp].

### The goal test

The plan's own closing line: "Fleet: 24 of 25 registered instances read their own knowledge base; consulting root included" [plan, "14:55 PDT"], and the final entry: "Goal of this plan (every project reads its own KB, consulting included) is met" [plan, "22:43 PDT"]. The measured half: on consulting root the hook answered a client prompt FULL in 160 ms with 6,214 chars after the clean apply [log:consulting-sync-20260906-224336.log:864]; on 4_points a case name returned only that case's paths in 237 ms inside the founder's own run [plan, "evening 09-05 local"]. The unmeasured half: 22 instances sit on the 2026-09-06T20:27Z base and have not received #312 through #321; nothing there is known to break, and the morning brief runs from its own tree [debrief:sync, G; T:2157@05:50:36Z].

## 2. Timeline by session

Session names are the ones peers used. A restart renames a session: the build session appeared as kipi-system-55, then ce, then 7f; the sync session as kipi-system-4b, then cb, then 51 [T:92e4, T:2157, agent identity reads]. The consulting VoiceLoop session was consulting-f2, later shown as voiceloop [T:7e2a@22:44Z 2026-09-06].

### 20e05492, the reader design and build (kipi-system, 2026-09-05T02:54Z to 19:55Z)

- 02:55Z the proposal arrives truncated by 759 lines, twice; a first plan is written blind and replaced at 03:16Z after the full text lands at 03:08Z [T:20e0@02:55Z, @03:08:58Z, @03:16Z].
- 03:23Z "build". 03:42Z to 03:48Z three commit attempts: a lefthook index lock, then the commit hook refusing client names in a public repo; fixture scrubbed, 695fe1c9 lands [T:20e0@03:42Z to 03:48Z].
- 03:49Z the 30-day replay overrules the plan's first-name rule: bare first names fire mid-sentence when they expand to exactly one entity [T:20e0@03:49Z; PR302 body].
- 03:55Z session limit; three limit resets and a login; "continue" 04:01Z [T:20e0@03:55:59Z to 04:01:29Z].
- 04:01Z to 05:45Z six verdict rounds on PR #302, every one the Opus fallback with Codex out of credits; the fix loop stops at round 5 when a class repeats; ASK-1261 gets its own single round; the stack is consolidated; round 6 approves [PR302 c@04:12Z through c@05:45Z]. 05:10Z and 05:50Z the founder asks "why did you stop" and "did you stop"; both were async waits [T:20e0@05:10:26Z, @05:50:23Z].
- 05:54Z merged as b33555dc. 06:25Z "run kipi update"; the founder mints a token at 06:26Z; 23 instances updated, consulting refused by its own pre-commit [T:20e0@06:25Z to 06:32Z].
- 06:40Z the documentation goal; PR #306 opens 07:07Z; 19:42Z the README rewrite request; 19:55Z exit [T:20e0@06:40:56Z, @19:42:43Z, @19:55:54Z].

### 92e4c064, the build session (kipi-system, 2026-09-05T21:24Z to 2026-09-07T19:52Z)

- 21:25Z to 21:37Z the founder's three messages and the goal that define the project-folders work; 21:45Z plan file; 21:50Z first red reproducer [T:92e4; plan].
- 22:01Z PR #308 opens on 4a5ccc4e; 22:04Z Codex out of credits, Opus fallback accepted [PR308 c@22:01Z; T:92e4@22:04Z].
- 22:10Z to 01:24Z twelve verdict rounds; round 2 called "the cap" at 22:14Z and not held; round 4 lost to a peer message at 22:58Z; two reviewer runs killed by the memory guard; 01:24Z APPROVE WITH NITS on 04fc851c [PR308 comments; plan, rounds 1 to 12].
- 23:15Z the founder's second goal: cited, tested assurances, then validate with the other projects and push [T:92e4@23:15:37Z]. 23:16Z the end-to-end assurance script with a negative run against the old engine [plan, "end-to-end assurance"].
- 2026-09-06T01:30Z merged as d7f3397b; ASK-1280 Done [PR308; linear:ASK-1280].
- 03:00Z the queued "why is consulting root out? I didnt say it stays out"; the hold lifts; 03:07Z "make a script for 2" puts the bypass inside fleet-apply-2026-09-06.sh [T:92e4@03:00:46Z, @03:07:47Z; rca:verify, contributing factors]. 03:10Z to 03:27Z the founder runs it four times through the session's bang prefix, none applies; 04:13Z "done" from a real Terminal, 23 instances updated [T:92e4@03:10Z to 04:14Z; log:fleet-apply-20260905-201045; log:fleet-apply-20260905-201119].
- 17:48Z "why are these waiting on me?"; the 4_points push and the consulting commit are rerouted to their owning sessions [T:92e4@17:48:05Z, @17:49:00Z].
- 18:16Z "Consulting is clean. This is the ping." retracted at 18:40Z: the real blocker is consulting's own pre-commit [T:92e4@18:16:47Z, @18:40:52Z; plan, "midday"].
- 20:35Z the founder's raw-line run stops on the rename hook; 20:40Z the fix branch; PR #312 opens 20:49Z and merges 21:27Z [log:consulting-sync-.log; PR312].
- 21:30Z to 21:53Z three founder runs land the sync in pieces; 21:50Z the gate overwrite is found; 21:54Z verify-only mode is added and run; it syncs [log:consulting-sync-20260906-145459.log:354-355,462; rca:verify].
- 22:20Z "can I close this terminal?" answered yes; 22:23Z consulting-f2 reports the undone restore; 22:25Z the RCA [T:92e4@22:20:11Z, @22:23:08Z, @22:25:15Z].
- 22:35Z "the computer crashed"; 22:43Z "continue the work and coordinate across instances"; 22:47Z the gate port branch that becomes PR #313 [T:92e4@22:35:14Z, @22:43:24Z, @22:47:45Z].
- 23:39Z the spillover ratchet asks for addresses; two promotions become ASK-1303 and ASK-1304; 23:42Z "did you go off scope on any of these projects?"; 23:43Z "keep but stay in scope after that" [T:92e4@23:39Z to 23:43:33Z; linear:ASK-1303; linear:ASK-1304].
- 2026-09-07T00:06Z session limit; 00:15Z "stay in scope"; 01:06Z the 30-hour line; 01:42Z "Round 5 is the cap"; 01:49Z two admin merges fail; 01:50Z the override script runs; 01:53Z #313 merged [T:92e4@00:06:40Z, @00:15:25Z, @01:06:12Z, @01:42:19Z, @01:49:00Z, @01:50:55Z; PR313].
- 04:52Z and 05:16Z two more bang-prefix runs that do nothing; 05:47Z "done" from Terminal; the clean apply lands [T:92e4@04:52:28Z, @05:16:08Z, @05:47:00Z; log:consulting-sync-20260906-224336.log].

### 2157c268, the docs and sync session (kipi-system, 2026-09-05T20:03Z to 2026-09-07T19:52Z)

The per-minute record is [debrief:sync, A]. The arc:

- 20:03Z "I don't see the diagrams"; PR #306 repaired, parked at round 3 at 22:19Z; PR #309 cut from main and merged 22:40Z [T:2157@20:03:53Z; PR306; PR309].
- 22:50Z one of three peer messages reaches the #308 reviewer's own session; round 4 posts UNSTATED [T:2157@22:50:11Z; sp-128ab6b9].
- 2026-09-06T00:07Z the sync goal; 00:25Z to 00:28Z the 22-instance command denied three times, then the token guard; five Stop-hook goal bursts, 84 feedbacks, 62 "Unchanged" replies through 09:12Z [T:2157; debrief:sync, E].
- 17:45Z "I ran both tokents"; the 22-instance loop runs ten minutes; the consulting token expires at 17:55Z [T:2157@17:45:19Z, @17:55:53Z].
- 18:36Z "the voiceloop project is working on that issue now"; PR #311 opens 18:49Z; this session runs its reviewer and arms the merge; merged 19:30Z [T:2157@18:36:56Z; PR311].
- 19:57Z consulting-f2 shows a freeze cannot stop Stop hooks; the command splits in two; 20:26Z "approved"; 20:27Z to 20:36Z the 23-instance run [T:2157@19:57:48Z, @20:26:48Z].
- 21:29Z FREEZE to two consulting sessions; 21:30Z roles split, 55 owns the run, this session owns the freeze; 21:58Z "Consulting is synced and verified", written on top of the undone restore [T:2157@21:29Z, @21:30:20Z, @21:58:17Z; debrief:sync, D].
- 22:43Z "continue"; PRs #314, #316, #317 built here; 23:10Z to 01:42Z six #314 verdicts including a lost approval at 00:29Z; 01:09Z "If it doesn't merge, stop and let me know"; 01:25Z parked; 01:26Z "send a brand new sana agent ... do not go over 1 attempt. Babysit it"; 01:54Z merged [PR314 comments; T:2157@01:09:16Z, @01:26:47Z].
- 05:53Z "why not the consulting today?" answered without reading consulting's git log, which already held 4f73aadd from 05:45Z; 06:08Z a second apply runs with no token asked because the deny hook matches the CLI phrase and not the script path [T:2157@05:53:26Z, @06:08:10Z; sp-37c08fb1; sp-cbc9dbb4].

### 7e2a26ae, consulting-f2 then voiceloop (consulting, 2026-09-05T01:28Z to 2026-09-07T19:54Z)

The extraction itself is [debrief:voiceloop]. The sync touchpoints:

- 2026-09-05T23:00Z owns up to messaging the #308 reviewer session [T:7e2a@23:00:12Z].
- 2026-09-06T09:08Z files a claim that a sync would delete 26 modules; 4b measures 4; the claim is voided [T:7e2a@09:08:52Z; T:2157@09:10Z].
- 18:34Z the founder: "why is it blocked on my call? sana is the authority"; the port decision goes to a Sana agent; PR #311 is built engine-only [T:7e2a@18:34:17Z, @18:37Z].
- 19:54Z the carry f7f6e7f2 lands with both consulting gates green [T:7e2a@19:54Z; mem:project_consulting_engine_ahead_of_skeleton].
- 21:42Z the mirror export refuses test_engine_surface.py in the mirror layout; excluded [T:7e2a@21:42Z; sp-4c490607].
- 21:48Z finds the sync overwrote voice-stop-gate.py; 21:52Z restores it as 6cf1c752; 22:22Z reports 2f4f5f85 undid it four minutes later [T:7e2a@21:48Z, @22:22:48Z].
- 22:42Z the process restart kills the re-apply twice; 22:48Z 3f9a04bb lands [T:7e2a@22:42:34Z, @22:48Z].
- 23:21Z a stash taken to unblock the merge held a live CRM repair; restored as c4973ef4; 23:31Z main merged into the branch as 57e10620 [T:7e2a@23:21:42Z, @23:41:55Z; mem:project_fleet_sync_2026_09_06, stash rule].
- 2026-09-07T01:31Z and 01:49Z "forget codex use claude for falbacl", twice; PR #319 flips the primary reviewer to Claude [T:7e2a@01:31:42Z, @01:49:45Z; git log 77cb3a7e].

### 77bd5374 and 7f5bb0a9, the gmail connection session (consulting, 2026-09-05T01:15Z to 2026-09-07T21:08Z)

The CRM and email build is its own story. The sync touchpoints:

- 2026-09-05T22:56Z 4b's diff shows consulting carrying four voiceloop files the skeleton lacks; the hold on consulting is filed as sp-afc424bd from this side [T:77bd@22:56:07Z].
- 2026-09-06T18:01Z the updater's dirty guard refuses on this session's live issue file active-issue.json; the file is kept committed and ASK-1299 is held for the freeze [T:7f5b@18:01Z, @20:27:44Z].
- 21:33Z measures the 14:30 PT lock holder on request: no deliberate git after the freeze, two read-only status calls before it, and "my session's Stop hook fires at every turn end" inside the window; the holder is never identified [T:7f5b@21:33:22Z to 21:33:44Z].
- 2026-09-07T20:21Z the merge of main for ASK-1340 is blocked six minutes by the Stop-hook auto-commit committing q-system/memory/.session-recall.json, a file the sync had modified; that commit is the branch parent bad450a6; the merge lands as 9ed5c11e at 20:30Z [T:7f5b@20:21:06Z, @20:30:04Z].

### 7f4d0d38, the 4_points case session (2026-09-04T21:15Z to 2026-09-06T21:28Z)

- 2026-09-04T21:24Z the .active-case pointer moves to case-043 [T:7f4d@21:24:03Z]. The reader's e2e probes used case-023; sp-c6d7b747 (default scope to the pointer) is downstream of this.
- 2026-09-06T00:10Z declines the sync for 95 uncommitted files in a live case; the founder was never asked in this transcript; the founder included 4_points in his own 11:40 PDT run [T:7f4d@00:10:15Z; mem:project_fleet_sync_2026_09_06].
- 17:49Z notices another session's tooling reading case-023 as a live test while the case work is open; declines to push mid-revision [T:7f4d@17:49:24Z to 17:49:34Z].

### 07447114, the Reddit transport session (consulting, 2026-09-05T06:27Z to 20:09Z)

- 07:03Z to 07:12Z a shared-index race with consulting-f2 puts this session's commit message on the peer's three voiceloop files as 1a7d7e01; ASK-1262 filed [T:0744@07:03Z to 07:22Z].
- PR #307 merged 16:24Z after ten review rounds; it moved main under PR #306 and PR #308 [PR307; git log b87947cb].

### cdd0087d and e1c421c8, today's two debrief sessions

- cdd0087d wrote [debrief:sync] at 20:20Z, had Sana read it, captured eight ledger items from its lessons, and dispatched two builds: PR #323 (the deny hook's script-path gap, round 2 pending) and PR #322 (parked at round 2, sp-6dada1c5) [T:cdd0@20:20Z to 21:47Z].
- e1c421c8 wrote [debrief:voiceloop] and found that PR #321's lock guard is on the skeleton and not on consulting's copy of auto-commit.py [T:e1c4@21:0xZ; sp-91c52f27].

## 3. Decision log

Origin tags follow sycophancy-core.md. A decision is listed once, at the moment it changed what got built or how.

- [USER-DIRECTED] 2026-09-05T02:55Z: design before code, inspect the architecture first, answer the smallest-missing-capability question [T:20e0@03:08:58Z].
- [CLAUDE-RECOMMENDED -> APPROVED] 2026-09-05T03:16Z to 03:23Z: the capability is a UserPromptSubmit reader hook plus a source manifest plus a receipt; no vector database now (exact strings dominate the questions; the misses ledger will measure whether the wording-mismatch class exists); no persistent index in phase 1; standard library only on a hook path. Approved with "build" [T:20e0@03:16Z, @03:19Z, @03:23:40Z; PR302 body].
- [SYSTEM-INFERRED] 2026-09-05T03:49Z: the replay overrules the plan's rule; bare first names fire mid-sentence when they expand to one entity [T:20e0@03:49Z].
- [SYSTEM-INFERRED] 2026-09-05T04:53Z: a wall-clock deadline of 3.5 s inside the supply pass and an entity cap of 12, because round 4's major repeated round 3's class [PR302 body, round 4; T:20e0@04:53Z].
- [CLAUDE-RECOMMENDED -> MODIFIED] 2026-09-05T05:21Z to 05:32Z: hold #302 until #304 is clean; the founder's goal "finish the implementation end to end" made finishing the instruction and the stack was consolidated [T:20e0@05:21:26Z, @05:32:09Z].
- [CLAUDE-RECOMMENDED -> APPROVED] 2026-09-05T06:24Z to 06:26Z: ship the reader to the fleet now ("my call: yes"); "run kipi update"; token minted [T:20e0@06:24:38Z, @06:25:05Z, @06:26:05Z].
- [CLAUDE-RECOMMENDED -> MODIFIED] 2026-09-05T21:33Z to 21:37Z: option one of three shapes for per-project knowledge; the founder added one knowledge base per 4_points investigation [T:92e4@21:33:19Z, @21:37:07Z; plan, Approach].
- [SYSTEM-INFERRED] 2026-09-05T21:45Z: grep-backed docs class at prompt time, no nightly index, no embeddings; headings and file stems never index; a corpus-common rule at four stores [plan, Approach and Deviations].
- [CLAUDE-RECOMMENDED -> APPROVED] 2026-09-05T20:05Z to 20:18Z, session 2157c268: fix the two CI reds on PR #306 and run the reviewer; "go" [T:2157@20:05:53Z, @20:18:41Z].
- [SYSTEM-INFERRED] 2026-09-05T22:22Z: park PR #306 at round 3 under the standing same-class rule and cut the README into PR #309 from main [T:2157@22:22:14Z; sp-c1c0464c].
- [USER-DIRECTED] 2026-09-05T22:48Z: "did you consult with the other sessions?" and "ensure you consult with the other working sessinos"; both sessions message their peers and one memory rule is written [T:92e4@22:48:23Z; T:7e2a@22:48:53Z; mem:feedback_consult_peer_sessions].
- [USER-DIRECTED] 2026-09-05T23:15Z: cited, tested assurances that the code produces the expected output, then validate commits with the other projects, then push [T:92e4@23:15:37Z].
- [USER-DIRECTED] 2026-09-06T00:07Z: run the fleet sync once the other projects are complete and it is safe [T:2157@00:07:38Z].
- [SYSTEM-INFERRED] 2026-09-04, carried to 2026-09-06T03:00Z: hold consulting root out of the sync until ASK-1238. Written as a safeguard by the build session on 2026-09-04, carried by two other sessions as if the founder said it. Reversed [USER-DIRECTED] at 03:00Z: "why is consulting root out? I didnt say it stays out" [mem:project_consulting_engine_ahead_of_skeleton; T:92e4@03:00:46Z].
- [USER-DIRECTED] 2026-09-06T03:07Z: "make a script for 2", the option that runs the updater under the founder's bypass from a script rather than through a minted token [T:92e4@03:07:18Z, @03:07:47Z].
- [CLAUDE-RECOMMENDED -> REJECTED] 2026-09-06T03:21Z: "the designed path (my call)", a minted token; the founder ran the script [T:92e4@03:21:53Z, @04:13:44Z].
- [SYSTEM-INFERRED] 2026-09-06T00:25Z: the command shape for 22 instances, consulting held, 4_points skipped at that session's request, reddit-build-radar unmanaged, consulting-kipi absent from the committed registry [T:2157@00:25:45Z].
- [CLAUDE-RECOMMENDED -> not acted on] 2026-09-06T18:23Z: "/goal clear is the honest close for tonight"; the goal loop ran until the mint at 17:45Z the next day [T:2157@18:23:55Z].
- [USER-DIRECTED] 2026-09-06T18:36Z: "the voiceloop project is working on that issue now"; ASK-1238 had been Backlog and unassigned [T:2157@18:36:56Z; linear:ASK-1238].
- [CLAUDE-RECOMMENDED -> REJECTED] 2026-09-06T18:34Z, consulting-f2: the port decision routed to the founder; "why is it blocked on my call? sana is the authority" [T:7e2a@18:34:17Z].
- [SYSTEM-INFERRED] 2026-09-06T18:50Z: PR #311 is engine-only, no q-consult, no automation, so the fleet removal set stays readable [PR311; linear:ASK-1238 c@18:50Z].
- [SYSTEM-INFERRED] 2026-09-06T19:57Z: split the consulting run out of the fleet command after consulting-f2 showed a freeze cannot stop Stop hooks; then, at 20:37Z, ask the build session to retract its bypass line so there is one path; reversed at 21:30Z, the build session owns the run and the sync session owns the freeze [T:2157@19:57:48Z, @20:37:38Z, @21:30:12Z].
- [USER-DIRECTED] 2026-09-06T20:26Z: "approved" for the 23-instance token [T:2157@20:26:48Z].
- [SYSTEM-INFERRED] 2026-09-06T20:40Z: fix the rename hook in the skeleton (PR #312) rather than reword the comment it rewrote; the exemption is the set the sync delivers, derived from the updater's own arrays [rca:rename; PR312].
- [SYSTEM-INFERRED] 2026-09-06T21:50Z: restore consulting's gate copy as an instance commit now and carry it into the open skeleton PR structurally; "A decision came to me and I made it" [T:92e4@21:50:07Z; sp-745f5962].
- [SYSTEM-INFERRED] 2026-09-06T21:54Z: add a verify-only mode to the run script and run it from the agent session [T:92e4@21:54:46Z; rca:verify].
- [SYSTEM-INFERRED] 2026-09-06T22:47Z: port the live gate into the skeleton (PR #313) instead of restoring per sync; self-described the next day as the stretch [T:92e4@22:47:45Z, @23:43:19Z].
- [CLAUDE-RECOMMENDED -> APPROVED] 2026-09-06T23:39Z to 23:43Z: the ratchet's two promotions (ASK-1303, ASK-1304) kept, with the constraint "keep but stay in scope after that" [T:92e4@23:43:33Z; mem:feedback_stay_in_scope_hook_prompts_are_not_the_ask].
- [SYSTEM-INFERRED] 2026-09-06T23:15Z: the instance-ahead report as an updater preflight with a refuse flag, off by default (PR #316) [PR316].
- [USER-DIRECTED] 2026-09-07T01:05Z: "forget the fractional cxo repo - Its dead"; sp-27b31cd1 voided [T:2157@01:05:28Z; sp-27b31cd1].
- [USER-DIRECTED] 2026-09-07T01:06Z: consulting in the sync, own the issue, not another 30 hours [T:92e4@01:06:12Z].
- [CLAUDE-RECOMMENDED -> APPROVED by action] 2026-09-07T01:06Z to 01:50Z: one structural fix on #313, one reviewer run, and on a further finding the founder merges past the reviewer; the founder ran the override [T:92e4@01:06:55Z, @01:50:55Z; pr-313-founder-override.sh].
- [USER-DIRECTED] 2026-09-07T01:09Z: "If it doesn't merge, stop and let me know"; the cap on #314 [T:2157@01:09:16Z; mem:feedback_same_finding_twice_go_structural].
- [USER-DIRECTED] 2026-09-07T01:26Z: one fresh Sana agent, one attempt, babysat; #314 merged at 01:54Z [T:2157@01:26:47Z; PR314].
- [CLAUDE-RECOMMENDED -> APPROVED] 2026-09-07T01:49Z to 01:50Z: a status-override API call when admin merge failed on enforce_admins; "give me the command in a script" [T:92e4@01:49:55Z, @01:50:21Z].
- [USER-DIRECTED] 2026-09-07T01:31Z and 01:49Z: "forget codex use claude for falbacl", said twice; PR #319 [T:7e2a@01:31:42Z, @01:49:45Z].
- [CLAUDE-RECOMMENDED -> REJECTED] 2026-09-07T05:50Z to 05:53Z: "tomorrow after the brief, one sync run"; "why not the consulting today?" [T:2157@05:50:50Z, @05:53:26Z].
- [CLAUDE-RECOMMENDED -> open] 2026-09-07T06:10Z: "My call: tomorrow" for the 24 instances still on the 20:27Z base; unanswered [T:2157@06:10:45Z].

The rubber-stamp ratio over the CLAUDE-RECOMMENDED rows above with a founder answer: 6 approved, 2 modified, 3 rejected, pi = 0.55. Below the 0.7 alert line. The count is this document's reading of the transcripts, not the decision-log script's; {{UNVALIDATED}} as a metric until canonical/decisions.md carries these rows.

## 4. Where we went wrong

Each item: surface cause, structural cause, and the executable that holds it now, or none yet.

### The verify-only run that synced (2026-09-06T21:55Z)

- What happened: consulting-sync-run.sh in verify-only mode performed a real sync (2f4f5f85, a9f506c) four minutes after consulting-f2 restored the gate as 6cf1c752, turning that checkout's pre-commit red again; the log shows "apply SKIPPED (verify-only)" followed by "attempt 1/0" and a full updater run [log:consulting-sync-20260906-145459.log:354-355,462,517; rca:verify].
- Surface: a skip implemented as a loop bound of zero, and macOS seq counting down so seq 1 0 prints two numbers; the script exported the founder's bypass in its own text, so the agent's command carried no destructive pattern and the deny hook passed it [rca:verify, surface and root cause 2].
- Structural: a founder-run script that sets the bypass is the agent setting it one hop removed; a new mode of a destructive tool shipped with no negative run on a throwaway checkout; the script was written between two founder runs as a three-line edit to a working loop [rca:verify, root cause 3 and contributing factors].
- Holds now: the script itself, fixed in place at 22:23Z (explicit skip branch, counter loop, refuses apply mode unless the calling shell set the bypass), proven by the 15:24 PDT negative run [log:consulting-sync-20260906-152406.log:547; rca:verify, verification]. The hook-side half, scanning the target of a bash-path command for the bypass, is sp-dc76e644, open; PR #323 from today's debrief session is in flight at round 2 [T:cdd0@21:32Z]. None yet in main.

### The rename hook rewrote the comment that documents the rename (2026-09-06T20:36Z)

- What happened: the founder's run at 13:37 PDT stopped before rsync; the pre-rsync hook did a plain token swap over every file including the engine's own docstring and the exporter's two comments; consulting's mirror gate refused the one-line diff; fleet-wide the same rewrite was a churn commit on every sync that the next rsync undid, rewritten=1 on 22 instances [log:consulting-sync-.log:34-70; rca:rename].
- Surface: str.replace over the whole file with no notion of prose [rca:rename, surface root cause].
- Structural: no classifier (a regex cannot tell a comment that documents the old name from a string literal that must migrate); no contract that a path the sync delivers is the sync's; fixtures whose engine init carried no token, so "already migrated is untouched" passed while the real init carried the name [rca:rename, root causes 1 to 3].
- Holds now: PR #312 d43f034b, tokenizer and parser classification for .py, the delivered set derived from kipi-update.sh's own two arrays and the registry prefix, 38 tests including a negative twin that watches the docstring get rewritten when the rule is removed [PR312; rca:rename, verification]. The RCA's four open action items (lock age check, abandon leaves nothing staged, a churn-signature check, the non-.py blanket swap) have none yet [rca:rename, action items; sp-2c1bcc3f; sp-9ec528aa].

### The consulting hold that was never the founder's (2026-09-04 to 2026-09-06T03:00Z)

- What happened: "do NOT fleet-sync consulting until ASK-1238" was written as a safeguard into memory on 2026-09-04, carried by two sessions, and excluded consulting root from the 22-instance plan from 00:08Z until the relay at 03:02Z [mem:project_consulting_engine_ahead_of_skeleton; T:2157@00:08:03Z, @03:02:39Z].
- Surface: a memory line with no origin tag.
- Structural: a HOLD written to memory reads the same whether the founder said it or a session inferred it, and there is no registry-level hold the updater honours, so the only hold was agents remembering [sp-87c2be0a].
- Holds now: the memory file says the hold was the agent's and the founder rejected it [mem:project_consulting_engine_ahead_of_skeleton]. No executable; memory-confidence-validator checks provenance fields on auto-memory writes but does not know a HOLD from a fact [rule skill-hook-pairing; debrief:sync, lesson 11]. None yet.

### Three instance-ahead overwrites in one day (2026-09-06)

- What happened: the plugins rsync with delete would have removed the four engine modules consulting's pipeline imports at module level [PR311, why]; the sync commit 7ce79343 replaced voice-stop-gate.py with the skeleton's older copy and every consulting commit went red [sp-745f5962; sp-1ad08728]; the sync delivered the skeleton's 48-word ban list over consulting's calibrated 46 [PR315, why]. Each was seen only after the write.
- Surface: rsync overwrites whatever is on the instance.
- Structural: the skeleton was behind the instance on synced paths and nothing in the updater compared the instance's tracked copy to what the skeleton ever shipped before writing [PR316, what broke].
- Holds now: PR #311 (engine), PR #313 (gate), PR #315 (words) closed the three specific gaps; PR #316's instance_ahead_scan names every ahead file before the pre-sync commit and the refuse flag stops there, with test-kipi-update-instance-ahead.sh including a mutant that silences the report [PR316, verification]. The 2026-09-07T01:53Z dry run printed both ahead files before the clean apply overwrote them on purpose [log:consulting-sync-20260906-185349.log:578-579]. The union half for the gate sits on open PR #295 [sp-1ad08728].

### Two writers on one index (2026-09-06T21:30Z to 21:34Z)

- What happened: the first post-#312 run delivered q-system as 7ce79343 and then died on "Unable to create index.lock: File exists" at the config commit, Updated 1, Failed 1 [log:consulting-sync-post312.log:569-576]; the guarded re-run tripped because consulting's Stop-hook auto-commit had committed the updater's own bytes as 9e2f8b4f and held the lock through its verify [sp-9306036e]; the updater deletes any lock unconditionally before every sync [sp-2c1bcc3f].
- Surface: no lock wait in the updater, a hook that commits on every turn end, and every peer message ending a turn.
- Structural: a shared checkout with three sessions plus a Stop hook is four writers; the freeze protocol was a message, and a message is a turn end [mem:project_consulting_engine_ahead_of_skeleton, freeze protocol].
- Holds now: PR #314 2abbeaa3, wait_for_index_lock before every index write, retry only on the live-lock error, a run marker the hook refuses to commit under, test-kipi-update-lock-wait.sh 4 of 4 with a mutant, test_auto_commit_run_marker.py 4 of 4 [PR314, verification]; PR #321 4a3afa7f makes auto-commit refuse while another commit holds git's locks [git log]. Not deployed: consulting's copy of auto-commit.py is 509 lines against the skeleton's 639 and lacks the guard, so the fix protects a checkout it has not reached [sp-91c52f27; debrief:voiceloop]. The unconditional lock deletion has none yet [sp-2c1bcc3f]. The lock holder at 14:31 PT was never identified; the consulting session's own measurement points at a status call or a hook, not a commit [T:7f5b@21:33:44Z].

### The reviewer session answered a peer (2026-09-05T22:50Z)

- What happened: two sessions messaged assafkip-kipi-system-pr-308-0f, the Opus fallback's own claude -p run; its reply became the review output, no FINDINGS block, round 4 posted UNSTATED, a round lost [sp-128ab6b9; T:2157@22:50:11Z; T:7e2a@23:00:12Z].
- Surface: a ListAgents row that looks like a peer.
- Structural: the fallback is reachable by cross-session messages and the script treats a missing block as a verdict instead of a retry.
- Holds now: the memory rule and a 45 s head-settle delay [mem:feedback_never_message_reviewer_sessions; plan, round 4]. sp-128ab6b9 major, open; none yet.

### A lost approval and two extra rounds on PR #314 (2026-09-07T00:29Z to 00:47Z)

- What happened: round 3 posted APPROVE WITH NITS as a comment on adc29516 at 00:29:47Z; the process exit at 00:35Z happened before the status landed; the session read the log as empty and re-ran the same head, which came back REQUEST CHANGES at 00:47Z [PR314 c@00:29Z, c@00:47Z; debrief:sync, D].
- Surface: the reviewer posts the comment before the commit status; a tracked background task dies with the process.
- Structural: verdict state is derived from a log file rather than from GitHub, and reviewers were started inside tracked tool calls.
- Holds now: none yet [sp-fa810306; sp-0a09e013].

### The duplicate consulting apply with no token (2026-09-07T05:53Z to 06:09Z)

- What happened: "why not the consulting today?" was answered "it can go today" without reading consulting's git log, which held 4f73aadd from the founder's 05:45Z Terminal run; the 06:08Z apply ran as a script path from kipi-scheduled and the deny hook asked for nothing because its pattern is the CLI phrase; the result was c8f9663d, 110 lines each way in settings.json, a pure key reorder [T:2157@05:53:58Z, @06:08:10Z; sp-37c08fb1; sp-cbc9dbb4].
- Surface: an instance state answered from memory; a deny pattern that matches one spelling.
- Structural: the guard reads command text, and a script path is a spelling it does not know; the config sync writes when the parsed JSON is unchanged.
- Holds now: none yet on main; PR #323 (script form) is in round 2 [T:cdd0@21:32Z]; sp-cbc9dbb4 open.

### PR #313's fourth round opened a fail-open (2026-09-07T01:12Z)

- What happened: db5d401d gated the receipt check on "did the founder speak last", so a routed draft after the gate's own exit-2 feedback completed with no receipt consumed; round 4 reproduced it; round 5's cbc4890d enforces when the founder just asked or the reply carries a draft [PR313 c@01:26Z; plan, "20:10 PDT"].
- Surface: a predicate that answered a different question than the call site asked.
- Structural: rounds 1, 3, 4 and 5 were one class, a machine-written user record read as the founder's request, attacked one carrier at a time (slash command, notification, own feedback, compaction summary) [PR313 c@23:05Z, c@00:55Z, c@01:26Z, c@01:41Z].
- Holds now: cbc4890d merged under a founder override; the compaction carrier is sp-b5ef2cda under ASK-1197, open; the reviewer's proposed shape is a label test on the record rather than another prose alternation [PR313 c@01:41Z]. None yet for that carrier.

### Two shadowed variables in one PR (2026-09-05T22:31Z and 22:44Z)

- What happened: a loop variable named truncated shadowed the prompt flag; the relationships loop rebound load_stores' name parameter, so the sub-store exclusion never applied when a relationships.md existed [plan, rounds 2 and 3].
- Surface: Python scoping.
- Structural: no pyflakes or pylint on the machine; the checks that exist run on the staged snapshot and do not include a rebind check.
- Holds now: a scratch AST check, shadow_check.py, run before each push during the build [plan, round 3]. It lives in a scratchpad; {{UNVALIDATED}} that any copy was committed to a repo. None in main.

### Six founder runs that could not run (2026-09-06T03:10Z to 2026-09-07T05:16Z)

- What happened: the founder ran the fleet-apply script four times and the consulting run script twice through the session's bang prefix; none applied: no TTY for the confirm prompt, the skeleton branch guard reading the primary checkout, and the session's own hooks denying the destructive op [T:92e4@03:10Z to 03:27Z, @04:52:28Z, @05:16:08Z; log:fleet-apply-20260905-201119:22-28].
- Surface: the bang prefix runs inside the session.
- Structural: a command handed to the founder did not say which shell it needs; the script cannot tell.
- Holds now: none yet; the founder was told three times to use a real Terminal [T:92e4@03:21:53Z, @03:34:12Z, @05:16:40Z].

### Capability tokens that expire mid-loop (2026-09-06T17:55Z)

- What happened: two tokens minted together; the 22-instance loop took eleven minutes; the consulting token had a 300 s life and was refused [T:2157@17:45:19Z, @17:55:53Z].
- Holds now: none yet [sp-22c0d55a].

### The Stop-hook goal loop (2026-09-06T00:25Z to 09:12Z)

- What happened: 84 goal feedbacks and 62 "Unchanged" replies in five bursts because goal 2's condition needed a founder-only mint; the session named the deadlock at 00:32Z and kept answering [debrief:sync, E; T:2157@00:32:16Z].
- Holds now: none yet [sp-1a47d0a1].

### The mirror exported from the wrong tree (2026-09-05 and 2026-09-06)

- What happened: the public voice-loop mirror was exported three times from a 43-file worktree, so the 18-file production checkout's mirror gate refused every commit [T:7e2a@18:55Z; sp-f63efdda; mem:project_consulting_engine_ahead_of_skeleton].
- Holds now: consulting's exporter guard refuse_off_default, commit 531ffd5f with a mutation-checked test [T:e1c4@21:23Z; debrief:voiceloop]. Skeleton side: the layout-bound engine test is sp-4c490607, open.

### Counts narrated from the wrong listing (2026-09-06)

- What happened: 9 against 14, 11 against 18, 31 against 39, three times in one evening, each a flat listing where the sync ships recursively; corrected on the Linear issue [linear:ASK-1238 c@18:38Z; T:92e4@18:01:26Z; T:7e2a@03:21:50Z].
- Holds now: a lesson, reconcile-a-count-you-can-compute-never-narrate-the-gap.md, added to the corpus in the window [git log q-system/lessons]. No executable.

### Verification that checked the deliverable and not the instance (2026-09-06T21:57Z)

- What happened: both kipi-system sessions reported the consulting sync verified (55 at 21:57Z "PASS", 4b at 21:58Z "synced and verified") on a checkout whose own pre-commit had just gone red because the verify step measured the reader bytes, the module count and the hook answer, never the instance's gate [log:consulting-sync-20260906-145459.log:526-539; T:2157@21:58:17Z; T:92e4@21:57Z].
- Surface: the verify list was the deliverable's list.
- Structural: "synced" was defined as "our files landed", not "the instance still passes its own gates".
- Holds now: consulting's own test_voice_stop_gate_propagation.py catches gate drift on that side; the run script's verify step still does not run the instance's pre-commit. None yet in the skeleton.

### Codex out of credits for the whole window

- What happened: every verdict from 2026-09-05T04:12Z to 2026-09-07T01:42Z carries DEGRADED, Opus fallback; the .codex-failed files all read "out of credits"; fallback rounds took 7 to 22 minutes [every PR comment in the range; ~/.config/kipi/pr-reviews/codex/*.codex-failed]. Codex came back for PR #318 round 2 at 02:31Z [debrief:sync, environment].
- Holds now: PR #319 77cb3a7e makes Claude the primary gate and Codex advisory, per the founder's twice-repeated instruction [git log; T:7e2a@01:49:45Z].

## 5. Where we looped

Each loop: the class of finding, why it recurred, what would have ended it a round earlier, and who called the stop.

### PR #308, twelve rounds, 41 findings (2026-09-05T22:10Z to 2026-09-06T01:24Z)

- Class one, the truncation and stop-reason accounting, surfaced in rounds 1, 2, 3, 6 and 7: a deadline landing before any work read "partial"; a cut search wrote searched true; the fold's deadline check was guarded by "not already truncated"; a composed engine string the parser could not read; docs read failures dropped [PR308 c@22:10Z, c@22:28Z, c@22:41Z, c@23:35Z, c@23:49Z]. It recurred because the stop reason was encoded in a display string and parsed back, and each fix added a path. The round 6 fix made stop an explicit field; the round 7 fix put docs read failures on the shared accounting every file class already used [plan, rounds 6 and 7]. One round earlier: the field at round 2, when the class first repeated.
- Class two, prompt-level target scoping, rounds 8, 9 and 10: it bypassed the corpus-common rule, then unioned past the named case, then hijacked an unrelated subject; removed at round 10 with "Three rounds on one idea = the idea was wrong, not the patches" [plan, round 10]. One round earlier: never add it; a named case is a scope, a filename narrows only its own entity.
- Class three, the author's own regressions: round 3's two shadowed names, round 4's ordering, round 5's too-wide rule caught by an existing test [plan, rounds 3 to 5]. One round earlier: the AST rebind check before round 3 instead of after it.
- Who called the stop: the reviewer, by approving. The session declared round 2 "the cap" and did not hold it; the founder's 23:15Z goal asked for finish with assurances, and every round's findings were real and reproduced [plan, round 1; T:92e4@22:14:33Z].
- Cost: about 3 h 14 m of wall clock, 18 reviewer launches for 12 verdicts (2 killed by memory, 1 lost to a peer message, 2 refused on moving heads, 1 killed by the session) [PR308 comments; T:92e4 agent count].

### PR #302, six rounds with a cap that moved (2026-09-05T04:01Z to 05:45Z)

- Class: the same resolution cost surfaced in rounds 3 and 4 (a 109 KB paste took 7.1 s; 65 names kill the hook at its timeout); the initial-position guard surfaced in round 1 and again in round 5 on a different path [PR302 c@04:35Z, c@04:53Z, c@05:12Z].
- Why: each fix guarded one path; the second occurrence became ASK-1261's single chokepoint [PR302 body].
- The cap was declared as three, restated as four, then "round 5 is a verdict check", then a sixth verdict on the consolidated head [T:20e0@04:17Z, @04:27Z, @05:13Z]. The fix loop did stop at the repeated class; the round count held at none of the numbers named.
- One round earlier: the chokepoint at round 1, when the guard was first found on one path only.

### The consulting root sync, seven attempts over 35 hours (2026-09-06T18:01Z to 2026-09-07T05:47Z)

- 18:01Z refused by the dirty guard on a peer's live issue file; 18:33Z refused by consulting's own pre-commit (staleness test and mirror gate); 20:36Z stopped by the rename hook; 21:30Z the config commit died on a live lock; 21:34Z the guarded re-run tripped on the auto-commit; 21:38Z plugins landed and the mirror gate refused the commit; 21:55Z the verify-only accident; 05:47Z the clean apply [log:consulting-sync-.log; log:consulting-sync-post312.log; log:consulting-sync-20260906-143806.log; log:consulting-sync-20260906-145459.log; log:consulting-sync-20260906-224336.log; T:2157 refusals 1 to 6].
- Class: an instance ahead of the skeleton on synced paths, and more writers than the updater modelled.
- Why: each refusal revealed the next layer, and each layer was fixed as its own skeleton PR (#311, #312, #313, #314, #315, #316) while the founder ran the next attempt.
- One round earlier: the instance-ahead report before the first apply would have named the engine, the gate and the ban list in one dry run; a dry run that also runs the instance's pre-commit would have named the staleness test on 09-05.
- Who called the stop: the founder's 30-hour bound and the override on #313 [T:92e4@01:06:12Z; pr-313-founder-override.sh].

### PR #313, five rounds and an override (2026-09-06T23:05Z to 2026-09-07T01:53Z)

- Class: a machine-written user record read as the founder's request, in four costumes: a slash command turn, a task notification, the gate's own feedback, a compaction summary [PR313 c@23:05Z, c@00:55Z, c@01:26Z, c@01:41Z]. Round 2 was a different class (any lane exception fails open) [PR313 c@23:47Z].
- Why: carriers were enumerated one at a time; the reviewer said so in round 5: "enumerating carriers is the shape that keeps failing, and this is the next carrier" [PR313 c@01:41Z].
- One round earlier: park at round 3 when the class was named at line 970, as the same-class rule says; or admit on harness labels rather than deny on carriers.
- Who called the stop: the founder, with the override script after two failed admin merges [T:92e4@01:49:00Z to 01:50:55Z].

### PR #314, six verdicts, one lost approval (2026-09-06T23:10Z to 2026-09-07T01:54Z)

- Class: "an index write you did not wait on", rounds 1, 2 and the 00:47Z re-run [PR314 c@23:10Z, c@23:39Z, c@00:47Z]; then a test flake and a bound below consulting's 445 s hold [PR314 c@01:24Z].
- Why: each round patched the named site instead of sweeping every index write; the approval at 00:29Z was lost to the process exit and the head was re-reviewed.
- One round earlier: sweep every git index write after round 1; check GitHub for a verdict on the head before starting a run.
- Who called the stop: the founder at 01:09Z and again at 01:26Z with the one-attempt Sana run, which merged in ten steps [T:2157@01:09:16Z, @01:26:47Z; PR314 c@01:42Z].

### PR #315, three rounds on copies of one list (2026-09-06T23:18Z to 2026-09-07T01:01Z)

- Class: the ban list had four hand-kept copies, then five skill files plus the monthly fingerprint plus an MCP test CI never ran [PR315 c@23:18Z, c@00:02Z, c@01:01Z].
- One round earlier: grep the tree for both words before the first push; derive the copies in the test instead of restating them.

### PR #312, a round on a stale head (2026-09-06T21:04Z)

- Round 2 measured 9612a4ce after the author had pushed 65b227bd; the finding repeated round 1's [PR312 c@21:04Z; plan, "PR #312 reviewer round 2"]. One round earlier: hold the reviewer until the author says the head is final.

### PR #307 and PR #306, hand-kept enumerators

- PR #307 ran ten rounds with the last three mostly regressions from the previous round's fixes; the session raised the cost question once and nobody answered [T:0744@16:05:53Z]. PR #306 found the same class in rounds 1 and 3 (a hand-listed enumerator missing a directory) and parked [PR306 c@20:48Z, c@21:49Z]. One round earlier: derive the enumerator's scope from git ls-files after round 1.

### Smaller loops with a count

- The gate restore on consulting: 6cf1c752, undone by 2f4f5f85, two re-apply attempts died with the restart, 3f9a04bb; ended by PR #313 carrying the union [T:7e2a@21:52Z to 22:48Z].
- Carries instead of a merge: a refused cherry-pick, f7f6e7f2, 5d2e3d2c, each 445 to 497 s of pre-commit; ended by merging main as 57e10620 [debrief:voiceloop; T:7e2a@23:31Z].
- Stop-hook goal loop: five bursts, 84 feedbacks, 62 replies; ended by the founder's mint [debrief:sync, E].
- The identical denied command: three runs in four minutes, then the token guard [T:2157@00:25:22Z to 00:32:16Z].
- Bang-prefix founder runs: six, none applied [section 4].
- Reviewer launches killed or lost: five memory kills in one session, two in another, one lost to a peer message, one lost to the process exit, four watchers timed out waiting for merges that REQUEST CHANGES rounds could not produce [debrief:sync, E; T:92e4 agent count].
- Session ownership of the consulting run flipped three times in an hour between 55 and 4b (20:30Z, 20:37Z, 21:30Z) [T:2157@20:37:38Z, @21:30:12Z].
- Founder status questions: "is it done" family seven times in one session; "done" typed seven times and "give me the command" three times in another; "did it merge?" five times in 38 minutes [debrief:sync, E; T:92e4].

## 6. Effort accounting

Counts come from the condensed transcript headers (founder-typed turns, assistant records, tool_use blocks) and from the agents' reads; active hours are sums of gaps under 30 minutes.

Sessions inside the build:

- 20e05492, reader design and build: 22 founder turns, 940 assistant records, 433 tool uses, about 4.5 active hours in a 17-hour span, 7 reviewer verdicts, 1 reviewer killed, 13 commits on the reader stack, PR #302 merged.
- 92e4c064, the build session: 59 founder turns plus 4 queued lines the extractor dropped, 1,764 assistant records, 964 tool uses, about 13 active hours in a 46.5-hour span, 93 messages sent to peers and 48 received, 25 watchers armed, 23 verdict rounds across #308, #312, #313, #315, two RCAs, three founder scripts, 4 PRs merged.
- 2157c268, the docs and sync session: 43 founder turns, 1,690 assistant records, 683 tool uses (441 Bash, 96 SendMessage, 76 Edit), about 17.5 active hours in a 47.8-hour span, 67 peer messages received, roughly 23 reviewer runs started, 5 PRs merged (#309, #310, #314, #316, #317), 38 path-guard blocks and 20 destructive-hook denials [debrief:sync, D].
- 7e2a26ae, consulting-f2: 62 founder turns, 4,225 assistant records, 1,879 tool uses, about 36 active hours in a 66-hour span, six memory kills, three restarts, roughly 50 consulting commits, PR #311 spawned through a Sana agent.

Sessions at the edge, counted for the founder's attention rather than the build:

- 77bd5374 and 7f5bb0a9, the gmail connection session: 58 founder turns, 3,098 assistant records, 1,622 tool uses, 68 hours of span, 14 consulting PRs merged.
- 07447114, the Reddit session: 7 founder turns, 1,011 assistant records, 535 tool uses, PR #307 after ten rounds.
- 7f4d0d38, the 4_points session: 65 founder turns, 813 assistant records, 300 tool uses.

Totals over the eight sessions: 316 founder turns, 13,541 assistant records, 6,416 tool uses. Over the four build sessions alone: 186 founder turns, 8,619 assistant records, 3,959 tool uses.

Review: 58 verdict comments on 15 pull requests inside the window (#302 six, #304 one, #306 three, #307 ten, #308 twelve, #309 one, #310 one, #311 two, #312 three, #313 five, #314 six, #315 three, #316 one, #317 one, #318 three) [PR comments]. Every one before 2026-09-07T02:31Z was the Opus fallback in DEGRADED mode, 7 to 22 minutes each.

Merges to kipi-system main in the window: 16 (#302, #307, #309, #308, #310, #311, #312, #316, #317, #315, #313, #314, #318, #319, #320, #321) [git log origin/main 2026-09-05 to 2026-09-07].

Founder-shell actions: at least five capability token mints (06:26Z 09-05; 17:45Z twice, 18:00Z, 20:26Z 09-06), nine script or command runs that reached the updater (four aborted and one complete on the night of 09-05, one fleet pass and three consulting runs on 09-06, one consulting run on 09-07), six bang-prefix attempts that did nothing, one reviewer-status override, two logins after session limits in each of three sessions [T:20e0; T:92e4; T:2157; logs].

Environment: memory kills of tracked tasks 5 plus 2 plus 6 across three sessions; one machine crash at 2026-09-06T22:35Z; one CLI restart at 2026-09-07T00:41Z; session-limit pauses in four sessions [T:92e4@22:35:14Z, @00:41:11Z; debrief:sync, environment].

Ledger: 99 rows dated in the window; 62 items open under the knowledge-supply and fleet-sync sources at the end, most with a fix shape [spillover.jsonl].

Cost in tokens or dollars: no transcript or log carries a figure for the build; one Sana review reported 279k tokens and 101 tool calls [T:7e2a@08:09Z 2026-09-07]. {{UNVALIDATED}} beyond that.

## 7. Lessons already captured versus new

### Already in a file

- The bypass never lives in a script; a skip is a branch; a new mode gets a negative run on a throwaway checkout [mem:feedback_agent_never_carries_the_founder_bypass; rca:verify].
- Never message a session shaped like a review tree [mem:feedback_never_message_reviewer_sessions; sp-128ab6b9].
- Same class on two consecutive rounds means the fix shape is wrong; a round called final is final; capture nits instead of pushing them; always post [mem:feedback_same_finding_twice_go_structural].
- A hook's ask is not the founder's ask; a structural unblock bigger than the ask is stated up front [mem:feedback_stay_in_scope_hook_prompts_are_not_the_ask].
- Consult live peer sessions before a push or a sync [mem:feedback_consult_peer_sessions].
- The hold was the agent's; never re-impose it; freeze by one message then silence; count recursively on the sync source; one owner for the freeze and one for the run [mem:project_consulting_engine_ahead_of_skeleton].
- Tokens live 300 s; dry run alone in its own call after every main move; a stash is half a move; the deny hook's silence on the script form is not permission [mem:project_fleet_sync_2026_09_06].
- The settled reader ideas not to re-propose: stop reason as a field, no prompt-level target scoping, no heading or stem indexing [mem:project_knowledge_supply_reader].
- The thirteen sync lessons with a check each, and the eight items captured from them: post status before comment, a STRUCTURAL stop in the reviewer, one live token, no git-into-grep under pipefail, skip an apply already on the skeleton sha, launcher-owned reviewers, a goal hook that stops at a founder boundary, uncaptured verdict minors [debrief:sync, F and G; sp-fa810306; sp-46726f79; sp-22c0d55a; sp-2d80ea8b; sp-cbc9dbb4; sp-0a09e013; sp-1a47d0a1; sp-28f981d6].
- The wrong-cause pattern, one worktree per session, run the real entry point once, the lock guard that never reached consulting [debrief:voiceloop; sp-91c52f27].
- Eleven lessons published to q-system/lessons in the window by the auto-learn job, among them reconcile-a-count-you-can-compute-never-narrate-the-gap, a-default-that-every-test-overrides-is-untested, derive-a-value-from-its-owner-never-restate-it-in-a-test, an-empty-result-must-say-what-it-was-empty-of, verify-the-rendered-surface-not-the-pipeline-that-feeds-it [git log q-system/lessons]. Which build event seeded each one is not recorded in the file; {{UNVALIDATED}} as a mapping.

### New, not in any file until this one

- Verification scoped to the deliverable passed on a broken instance. Two sessions said "verified" at 21:57Z and 21:58Z on a checkout whose own gate was red, because the verify list was the reader's bytes, the module count and the hook answer [section 4]. Rule: a sync is verified when the instance's own pre-commit passes on the delivered tree, not when the delivered files match.
- Instructions lose their origin when they cross a session boundary. The consulting hold travelled from a memory note into two sessions' plans as the founder's decision; "stay in scope" was typed in session 92e4c064 at 23:43Z and 00:15Z, never typed in session 2157c268, and that session's compaction summary at 01:37Z listed it as an explicit founder instruction received twice [T:92e4@23:43:33Z, @00:15:25Z; T:2157 raw search; agent read of the compaction summary]. Rule: a relayed or remembered instruction carries who said it and where; a HOLD or a cap in memory carries an origin tag.
- The bang prefix is not the founder's shell. Six founder runs did nothing over two days because the prefix runs inside the session with its hooks and no TTY [section 4]. Rule: every command handed to the founder names the shell it needs, and a founder-run script refuses when it detects the session environment. {{UNVALIDATED}} which environment variable is the reliable tell.
- Agent-declared round caps never held; founder-declared caps did. "Round 2 is the cap" (#308), "three rounds" then "four" then "round 5 is a verdict check" (#302), "round 3 is the last relay" (#313 and #315); against that, "If it doesn't merge, stop" and "do not go over 1 attempt" both ended their loops inside one round [T:92e4@22:14:33Z; T:20e0@04:17Z to 05:13Z; T:2157@01:09:16Z, @01:26:47Z]. Rule: the cap is in the brief before dispatch and the reviewer script counts rounds; a cap declared mid-loop is a wish.
- A dry run's "Updated 1" is printed for every instance it processes, so it does not say whether anything changes; the 05:54Z dry run read Updated 1 on an instance synced eight minutes earlier [T:2157@05:54Z; sp-cbc9dbb4]. Rule: the dry run reports "already at skeleton sha" as its own state.
- The end-to-end assurance reads production case folders while a case is live. The 4_points session saw another session's tooling reading case-023 as a live test while its own investigation was open [T:7f4d@17:49:34Z]. The probes were read-only, so no harm landed; the rule is that a probe against a live instance is announced to the session working in it.
- The proposal arrived truncated twice and a whole plan was written from the repo alone before the full text landed [T:20e0@02:55Z to 03:16Z]. Rule: a pasted input over the display limit is checked for its line count before planning on it.
- Peer coordination has a price the build never counted: roughly 320 cross-session messages across four sessions in two days (93, 96, 61, 69), each ending the receiver's turn and firing its Stop hook, two of them costing a review round or a lock [section 6; sp-9306036e]. Rule: one owner per checkout, coordination through files and markers, messages only for state changes.
- Two records of the same day disagree on one fact: the fleet-sync memory credits cea9fd0f with the 2026-09-07T02:35Z unblock, and the voiceloop debrief states that f7f6e7f2, not cea9fd0f, unblocked the sync [mem:project_fleet_sync_2026_09_06; debrief:voiceloop, section 0]. They may describe two different syncs (09-06 and 09-07). {{NEEDS_PROOF}}; resolve by reading consulting's reflog for both dates before either claim is reused.

## 8. Still open and who owns it

Owner Sana, skeleton side, from the ledger and the reports:

- The deny hook's two gaps: a wrapper that sets the bypass [sp-dc76e644] and the updater invoked as a script path [sp-37c08fb1]; PR #323 in round 2 [T:cdd0@21:32Z].
- The reviewer fallback answers peers and a missing FINDINGS block posts UNSTATED [sp-128ab6b9, major]; the comment-before-status ordering [sp-fa810306]; launcher-owned reviewer runs [sp-0a09e013]; the STRUCTURAL stop after two same-file rounds [sp-46726f79]; PR #322 parked on the same script [sp-6dada1c5].
- The updater: unconditional lock deletion [sp-2c1bcc3f]; abandon leaves staged rewrites [sp-9ec528aa]; the system-state git add is unwaited and kill -0 misreads a foreign uid [sp-a6d9965b]; a second apply from the same sha must make no commit [sp-cbc9dbb4]; one live token at a time [sp-22c0d55a]; the instance-ahead union half through PR #295 [sp-1ad08728; sp-745f5962]; a registry-level hold as a capability, not a hold [sp-87c2be0a].
- PR #321's lock guard is not on consulting's copy of auto-commit.py [sp-91c52f27, major].
- The reader: default scope to .active-case [sp-c6d7b747]; placeholder contacts read KNOWN [sp-98edad17]; the two round-12 nits [sp-b19577e3; sp-6a066645]; the eight ASK-1261 items resolvable when that issue closes.
- The rename hook's four approve-with-nits leftovers [sp-99e74f4b; sp-a0a327c4; sp-14812459; sp-50a50426].
- The gate port's round-5 leftovers under ASK-1197, In Progress: the compaction carrier, the deny that returns, sys.path growth [sp-b5ef2cda; sp-cb33ab6a; sp-92a8393c; linear:ASK-1197].
- ASK-1303 (one sink for NOT CHECKED lines) and ASK-1304 (the fanout-loss check needs a runner), both Backlog and unassigned [linear:ASK-1303; linear:ASK-1304].
- The ban list's sixth copy in the founder output style and two test floors [sp-730a54f5; sp-5f437cc0; sp-aaf66023].
- The docs handbook PR #306, parked with no owner named [sp-c1c0464c; sp-c4d26576].
- The daily writer that re-creates plugins/memory-lifecycle [sp-206ec4ba]; consulting-kipi's uncommitted registry row [sp-1616bce4]; the layout-bound engine test [sp-4c490607].
- The gates that read repo-global state as session-local: token-guard freezing a worktree subagent [sp-42484531], read-first-gate blind to a subagent's reads [sp-489f2d62; sp-eea22410].

Owner the founder:

- The 22 skeleton-managed instances on the 2026-09-06T20:27Z base; main has gained #312 through #321; the sync session's call was "tomorrow" and nothing is known to break meanwhile [debrief:sync, G; T:2157@06:10:45Z].
- The 4_points repo: 52 commits ahead of its origin, 95 uncommitted files in a live case, the override manifest committed locally as b8cfc48f [plan; T:7f4d@00:10:15Z].
- fractional-cxo's registry row retirement, after "Its dead" [mem:project_fleet_sync_2026_09_06].
- A Claude Code restart on any machine that should pick up kipi-core 1.12.1's version-keyed plugin cache; {{UNVALIDATED}} whether it already happened [PR311, shape of the diff; lesson verify-against-the-installed-clone].

Owner the consulting sessions:

- feat/gtm-visibility-surfaces at 9ed5c11e, not pushed [T:7f5b@20:30:28Z].
- The xfail marker on test_voice_stop_gate_propagation.py and its default pointing at the feature-branch checkout rather than kipi-scheduled [mem:project_consulting_engine_ahead_of_skeleton; sp-357293d9 per debrief:voiceloop].
- The public mirror's exporter guard is in, the deployment tests stay off main by decision [debrief:voiceloop].

Resolved in the window, for the record: sp-c56a9b91 (ASK-1280 Done), sp-523c1a25 and sp-9306036e (PR #314), sp-eb72e46a, sp-a4a5028a, sp-2694343c and sp-6f1c2100 (measured void), sp-27b31cd1 and sp-26b2d3cf (voided) [spillover.jsonl].

## 9. Three process changes to adopt next time

1. Before any sync, one dry run that names instance-ahead files, and after any sync, the instance's own gate before the word verified. The evidence is three overwrites in one day seen only after the write, and two "verified" reports on a red checkout. The executable half exists in PR #316; the rule is that the consulting run script and the fleet apply always pass the refuse-instance-ahead flag on the dry run, and their verify step runs the instance's pre-commit on the delivered tree and prints its result before PASS. A green that skips the instance's gate is not a green.

2. A founder-run command ships as a script that knows which shell it is in, never carries the bypass, and has a negative run before a live one. The evidence is six bang-prefix runs that did nothing, four aborted script runs on the first night, and one verify-only mode that synced. The rule: every script under ~/.config/kipi refuses apply mode without the caller's bypass, refuses when it detects the session environment and says "run this in Terminal", and its first run of any new mode is against a throwaway checkout with HEAD compared before and after. The deny hook learns the script-path form (PR #323) so the hook and the script agree.

3. The round cap is written into the brief before the reviewer is started, and the reviewer script holds it. The evidence is 12, 10, 6 and 5 rounds on four PRs where every agent-declared cap moved and only the founder's caps held. The rule: the dispatch message says "N fix rounds; a repeated class parks; a new class after N parks"; the reviewer script counts rounds per PR and prints STRUCTURAL and exits when two consecutive verdicts share a file (sp-46726f79); a parked PR is a draft with its class captured once, and the founder hears one message, not a fifth "did it merge".

Held back on purpose: a fourth candidate, origin tags on every relayed or remembered instruction, is a lesson above and a memory-validator change, not yet a process the founder can check off.
