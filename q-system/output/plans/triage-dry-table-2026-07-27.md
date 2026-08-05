# Triage dry pass, 115 issues, kipi-system

> **Recovered work-product — a point-in-time snapshot, not current documentation.**
> This file existed only in a dirty checkout and was recovered on 2026-08-05
> (PR #106, ASK-363). Every claim about system state was true at this document's
> own date and may not be true now. In particular, "wired" here means *merged in
> this repository*; whether the RUNNING copy loads it is a separate question that
> `q-system/.q-system/scripts/runtime-plugin-freshness.py` answers, because the
> two came apart for a full day during this very build. Read it as a record of
> what was decided and why, and verify current state against the code.

Dry run. **Nothing was written to Linear.** Ran 2026-07-27.

ASK-210 was skipped automatically: PR #23 already owns it.


## The buckets

| count | bucket | what --apply would do |
|---|---|---|
| 57 | `batch` | nothing yet, groups them for one change |
| 38 | `not-planned` | **comment with the reason, then close as not planned** |
| 9 | `needs-scope` | comment asking for a Files line |
| 7 | `do-now` | nothing, eligible for dispatch |
| 4 | `founder-decision` | comment, leave open for you |

The only destructive bucket is `not-planned`. Reopening restores it, and the reason stays on the closed issue.


## founder-decision (4)

| issue | why | next |
|---|---|---|
| ASK-149 | Its own Definition of Ready makes the outcome contingent on the founder explicitly choosing 'radar runs daily again' vs 'stays off until the Linear mi | Put one question to the founder: resume com.cole.reddit-radar-daily now, or leav |
| ASK-91 | The body states the blocker itself: open-loops-heartbeat.sh (q-system/.q-system/scripts/) merges its own PRs under the autonomy contract, so there is  | Put three options to the founder: (a) founder-approves-merge on a sampled slice  |
| ASK-77 | Code is merged (PR #7, 5-issue gated flow, 3 tests) and the only remaining step is releasing the deliberately HELD kipi update on 4_points, which arms | Ask the founder one question: release the held kipi update on 4_points now, or k |
| ASK-59 | The blocker is a risk and cost call, not a scoping one: 11684 Gate 1.3b findings can only be cleared by narrowing the classifier or target list (accep | Sample 100 random findings, report the leak-vs-noise rate and the cost of each p |

## do-now (7)

| issue | why | next |
|---|---|---|
| ASK-214 | Real and scoped: issue_runner.py:747 is the only receipt writer and is reachable only from cmd_close, cmd_load:423 calls _require_marker unconditional | Add a from-Linear-DoR subcommand to plugins/prd-os/scripts/prd_split.py that emi |
| ASK-212 | Concrete single-file defect with a live observation: rework_gate at pr-verdict-lib.sh:77, called from linear-worker.sh:187-205, decides dispatch from  | After ASK-211 merges, cut a fresh worktree from the new main, add a mergeability |
| ASK-189 | Real durability hole with two same-day measurements (worker-1785159359-39569 and worker-1785160167-43978 held the claim with zero live processes): con | Record the long-lived worker shell pid in the claim record and consult _pid_aliv |
| ASK-187 | Both target files exist and the issue already proves the change is safe: every Write() deny pattern has an identical working Edit() twin in both .clau | Delete the 5 Write() entries from permissions.deny in .claude/settings.json and  |
| ASK-150 | Implementation is done and PR #11 has validate=SUCCESS; the only remaining work is one named merge conflict in q-system/.q-system/scripts/fleet-health | In the sana/ask-150 worktree: git merge origin/main, keep both detect_cron_shell |
| ASK-117 | Real and confirmed on disk but half-stale: instance-registry.json lines 157 to 164 already record reddit-build-radar as type standalone with subtree_p | Add a registered-instance-zero-propagation check to the kipi-update.sh preflight |
| ASK-116 | Three divergent hashes (79aec127bf30 / e9f11c1fb928 / 1a1b1e2674b2) were verified by direct hashing across 4_points_consulting, investigations, and Al | Diff the three evidence-capture-protocol.md versions, reconcile into one file at |

## needs-scope (9)

| issue | why | next |
|---|---|---|
| ASK-213 | The issue names its own detector signatures as 'candidate, to be confirmed' and sets no false-positive budget for a repo-wide scan of exit 0 branches, | Pin the detector spec against the three known instances (linear-worker.sh fetch  |
| ASK-154 | Unlike its five siblings this is a long-running Flask/HTTP server (fleet-venv python3 gtm/dashboard/server.py, schedule 'on demand / at load'), so the | Rewrite the Outcome and Check for a KeepAlive daemon: define liveness as a succe |
| ASK-148 | The title says 77 open items and its own check block says 127 (111 minor, 5 medium, 4 low, 3 major, 3 high, 1 blocker), and the DoR admits the code fi | Run python3 plugins/prd-os/scripts/prd_runner.py spillover list --open from ~/pr |
| ASK-105 | Real gap named in the body (plugins/kipi-notebooklm v0.1.0 has no paired tests in the capability manifest, no commands dir) but the issue has no Files | Rewrite as: add plugins/kipi-notebooklm test script + one line in the capability |
| ASK-90 | .claude/rules/loop-exits.md exists and the audit is honest that exits 3 (budget) and 4 (wall clock) run on proxies, but the issue names no file to cha | Split out one scoped issue for exit 4: define the in-session deadline for unatte |
| ASK-72 | Unlike its LIVE siblings this one names a real open defect in its own body -- voice-lint v1 misses within-sentence comma triplets and cross-paragraph  | Split the detector gap into its own issue with a failing fixture for each missed |
| ASK-58 | Real and already measured (validate-separation.py 5 gives 170 PASS, 3 FAIL, 1 WARN, exit 1) but not actionable as written: the one KTLYST-referencing  | Run python3 validate-separation.py 5, paste the Gate 1.2 and Phase 1 offending f |
| ASK-57 | Flagged no-Files-line and the two paths that would define the work (settings.json, test-settings-merge.sh) are MISSING on disk, so as written this is  | Resolve where the settings-merge test actually lives (grep the capability manife |
| ASK-52 | The entry-point list names update-preservation-manifest.py as a dependency of the propagation path but that file is MISSING while kipi-update.sh and k | Grep kipi-update.sh for update-preservation-manifest.py to determine whether the |

## not-planned (38)

| issue | why | next |
|---|---|---|
| ASK-208 | Superseded: PR #22 closed unmerged at the round cap and its four bundled fixes are being re-filed one per issue (fix 1 as ASK-211, fix 2 as ASK-212),  | Confirm sp-fd76af2f and sp-1aae7516 each have a re-filed issue, then close ASK-2 |
| ASK-147 | Duplicate of ASK-149 action item 1 — same script (cole-gtm/projects/reddit-build-radar/scripts/run_daily.sh), same two schedulers, same fix (drop the  | Close as duplicate, linked to ASK-149; add the daily.log no-op evidence line to  |
| ASK-137 | The evidence is factually wrong: rca-mode.md:20-23 names both the rca-notify and rca-lint hooks, both scripts exist at plugins/kipi-core/skills/rca/sc | Close as already-true-on-disk with those four paths pasted in, and file one fix  |
| ASK-112 | The issue body is its own completion receipt: linear-issue-ref-check.py, .claude/rules/linear-first.md, lefthook.yml and the auto-commit `[no-issue: a | Close as done; if fleet-wide rollout beyond kipi-system is wanted, file that as  |
| ASK-111 | Status is LIVE and the entry point .claude/rules/quick-plan.md exists on disk with the described contract (read memory + prior plans first, checkboxed | Close as documentation-of-shipped-state; the one MISSING path (methodology/anti- |
| ASK-110 | Status is LIVE, q-system/memory/last-handoff.md exists, and the three MISSING entries (session-start.py, post-compact.sh, md-prune.py) are bare filena | Close as documentation-of-shipped-state; if the hook wiring genuinely needs re-v |
| ASK-109 | Status is LIVE, CLAUDE.md and q-system/CLAUDE.md exist, and the body's own evidence is a count (`ls .claude/rules/ / wc -l` = 31) plus the already-wir | Close as documentation-of-shipped-state; the rule-count number will drift, so re |
| ASK-108 | Status is LIVE and the sole named path q-system/.q-system/scripts/slack-notify.sh exists with the described silent-no-op behavior and the open-loops h | Close as documentation-of-shipped-state; auditing whether other emitters still u |
| ASK-106 | Body says Status: LIVE (kipi-ops v1.2.0, skills/council/) and the only named path canonical/decisions.md is MISSING from this repo because decisions.m | Close as not-planned; the council auto-trigger rules already live in .claude/rul |
| ASK-104 | All three named scripts (granola-voice-harvest.py, granola-voice-fingerprint.py, granola-voice-synthesize.py) are MISSING from this repo per the struc | Close as not-planned; if the harvest chain is actually wanted in kipi-system, fi |
| ASK-103 | Status LIVE inventory card: 5 of 6 named paths are MISSING and the one that exists (q-system/methodology/anti-hallucination.md) needs no change; the o | Close as not-planned; the Reddit .rss workaround is already recorded and reddit- |
| ASK-102 | Both scars are already resolved and recorded: the AppleEvents/`open -a Terminal` constraint is documented in the /say entry in CLAUDE.md, and the vani | Close as not-planned; /say behavior and its two constraints are documented in CL |
| ASK-101 | Duplicates the open-loops ledger entry for the capability-token PR (dwarvesf/claude-guardrails issue #14, filed 2026-06-20), which already carries the | Close as duplicate of the open-loops entry in q-system/memory/open-loops.json; a |
| ASK-99 | The one path it names (`.claude-plugin/marketplace.json`) exists, the 6 plugin versions were verified 2026-07-26, and the body requests no change; it  | Close as not-planned; if the version table is wanted as living state it belongs  |
| ASK-97 | `.claude/rules/model-allocation.md` exists, the 5 agent definitions and validator Gate 1.1b are recorded as passing on 2026-07-26, and the body asks f | Close as not-planned; tier drift is already owned by `kipi check` Gate 1.1b, whi |
| ASK-88 | Description self-declares Status: LIVE with 2026-07-26 evidence (7 loops in q-system/memory/open-loops.json, test-open-loops.sh present) and the Sessi | Close as not-planned; if the inventory is worth keeping, move the L8 card to a d |
| ASK-87 | Same machine-filed inventory shape as ASK-88: Status LIVE, all 6 com.kipi.* jobs verified loaded with last-exit 0 via launchctl on 2026-07-26, watchdo | Close as not-planned; the launchd job table belongs in AUTONOMOUS-SYSTEMS.md, no |
| ASK-86 | Status LIVE and already true on disk: .prd-os/spillover.jsonl plus prd_runner.py spillover add/resolve are the mechanism .claude/rules/no-orphan-findi | Close as not-planned; no code change implied. |
| ASK-85 | Status LIVE and the described merge already happened -- fable-discipline moved into plugins/prd-os on 2026-07-04 with the lint hook wired in prd-os's  | Close as not-planned; no diff to write. |
| ASK-84 | Status LIVE (v0.2.1) with all 6 commands shipped and /issue-amend behavior verified 2026-07-26; the one live constraint it names (Codex out of credits | Close as not-planned; if the reviewer substitution needs hardening, file that as |
| ASK-82 | Status LIVE (v0.6.0) with 9 commands and gates run shipped as the registered no-bypass re-proof (commit 53f2eeb separated gate lifecycle); prd_runner. | Close as not-planned; no work item remains. |
| ASK-81 | Already true on disk: the com.kipi.lessons-daily launchd job is loaded with last exit 0 and 6 dedicated tests cover validator, propagation, distill, s | Close as documented-live and leave the provenance-ledger entry in open-loops.jso |
| ASK-76 | Already shipped and deliberately terminal: skill-trigger-eval.py plus test-skill-trigger-eval.sh exist and the advisory-not-a-gate design is a settled | Close as documented-live; if trigger confidence is wanted, run skill-trigger-eva |
| ASK-75 | Description says Status: LIVE with 2026-07-26 evidence that both batch-uniformity-lint.py and format-lint.py are already wired in settings.json and se | Close as not-planned; if the inventory needs to persist, move it to a doc rather |
| ASK-74 | Same inventory shape as ASK-75: Status LIVE, and skill-hook-pairing.md (which exists on disk) already lists headline-engineering -> headline-lint and  | Close as not-planned; the pairing table in .claude/rules/skill-hook-pairing.md i |
| ASK-73 | Status: LIVE with the skill plus paired audhd-lint hook already shipped, and the same content is already enforced as a rule in .claude/rules/audhd-int | Close as not-planned; no diff is implied by the body. |
| ASK-71 | Status: LIVE with 2026-07-26 evidence that auto-commit.py and stop-logger.sh are wired in settings.json and settings-template.json; the only forward-l | Close as not-planned; file worktree-per-session separately if it is to be built. |
| ASK-70 | Status: LIVE and the body cites the shipping commit 48adb50 for the grounding-guard Stop hook plus the voice-stop-gate `// true` fix, so the work is a | Close as not-planned, referencing commit 48adb50 as the receipt. |
| ASK-69 | Description says Status: LIVE and the only thing needing a change is the issue's own claim of a `wiring-check.py` hook, which does not exist on disk w | Close as not-planned; if the map's entry-point line is wrong, correct `wiring-ch |
| ASK-68 | Status: LIVE with self-reported evidence that the guard blocked the very write that produced these issues; the three named paths are MISSING only beca | Close as not-planned; no code change. |
| ASK-67 | Status: LIVE, `q-system/.q-system/token-guard.py` exists on disk with the six detectors and constants already verified 2026-07-26, and the one gap nam | Close as not-planned; no code change. |
| ASK-66 | Pure inventory card for the hook runtime: both named paths (`.claude/settings.json`, `settings-template.json`) exist and the body is a wiring table re | Close as not-planned; no code change. |
| ASK-65 | Status: LIVE (fleet-only) with RULE-2026-06-30-A wired in `settings-template.json`, and the MISSING paths are bare filenames for a fleet-only guard th | Close as not-planned; no code change. |
| ASK-64 | Status: LIVE, both settings files exist and the check is wired PostToolUse plus `kipi update` preflight; the stated 34-local-entries vs 32-template-sc | Close as not-planned; no code change. |
| ASK-63 | The gate is already shipped and green: validate-separation.py and .claude/rules/model-allocation.md both exist on disk and the 2026-07-26 evidence lin | Close as a shipped-status record; if the L2 inventory needs to persist, fold it  |
| ASK-54 | Every path named exists (kipi-new-instance.sh, settings-template.json), the described behavior is already true on disk, and the evidence is four insta | Close as documentation-only; if the L1 card has archival value, move it to the c |
| ASK-53 | instance-registry.json and validate-separation.py both exist and Phase 0 already asserts all 24 registered instance paths PASS with 0 FAIL, so the cap | Close as already-true; the validator Phase 0 run is the standing check, no new w |
| ASK-51 | Description says 'Status: LIVE' with a 2026-07-26 evidence line citing kipi:83,86, and all five named scripts (kipi-update.sh, kipi-new-instance.sh, k | Close as not-planned; if the L1 inventory needs a permanent home, move the capab |

## batch (57)

| issue | why | next |
|---|---|---|
| ASK-186 | Identical machine-filed job-migration template (kipi-key job-migration/*) as ASK-185/180/179/178/177 -- same four bars, same launchd-health-check.py - | Work all job-migration/* issues as one change: write the migration harness (plis |
| ASK-185 | Same job-migration template as ASK-186/180/179/178/177 -- only the plist name (com.personal.story-podcast) and the wrapped script differ; the Definiti | Fold into the single job-migration batch; per-job work is one run of run_daily.s |
| ASK-180 | Sibling of the same job-migration template; shares both shape and fix with ASK-179 in particular (same fractional-cxo automation/.q-system/scripts/ di | Fold into the job-migration batch; do the two fractional-cxo jobs (ASK-180 + ASK |
| ASK-179 | Sibling of ASK-180 -- same fractional-cxo automation/.q-system/scripts/ directory, same template, same check; migrating one and not the other would le | Fold into the job-migration batch, paired with ASK-180. |
| ASK-178 | Same job-migration template; notable as the only one whose script lives in this repo (q-system/.q-system/scripts/fleet-health-daily.py), so it is the  | Do this one first inside the job-migration batch -- it is the in-repo script, so |
| ASK-177 | Same job-migration template, wrapping /Users/assafkipnis/.claude/audit/rotate.sh; a log-rotation job differs from the others only in what its output m | Fold into the job-migration batch; if the rotate job turns out to be obsolete, s |
| ASK-176 | One of six identical `job-migration/com-cole-*` issues (ASK-171 through ASK-176) filed by the same scanner with a byte-identical Definition of Ready,  | Open one parent issue 'Migrate the 6 paused com.cole.* jobs to Linear-tracked ex |
| ASK-175 | Same shape and same fix as ASK-171/172/173/174/176: paused com.cole.* launchd job, identical DoR template, identical watchdog check, differing only in | Fold into the single com.cole.* migration change; per-job work here is one plist |
| ASK-174 | Sibling of the same six-issue com.cole.* migration set; the only per-issue deltas are the label, the 3600s interval and `substack_worker/run_worker.sh | Fold into the single com.cole.* migration change; per-job work is one plist + on |
| ASK-173 | Sibling of the same six-issue com.cole.* migration set (identical DoR, identical check block); deltas are the label, the twice-weekly 06:00 schedule a | Fold into the single com.cole.* migration change; pair it with ASK-174 since bot |
| ASK-172 | Sibling of the same six-issue com.cole.* migration set; the 300s poll interval and `slack_listener/run_poll.sh` are the only deltas, and its Linear-re | Fold into the single com.cole.* migration change; per-job work is one plist + on |
| ASK-171 | Sixth sibling of the identical com.cole.* migration set (ASK-171 through ASK-176), differing only in label, 00:07 daily schedule and `reply_sweep/run_ | Fold into the single com.cole.* migration change; per-job work is one plist + on |
| ASK-170 | Identical shape to ASK-169/168/167/166/165 (same kipi-key namespace job-migration/, same four-bars DoR, same launchd-health-check.py --dry-run check); | Fold into one batch issue 'migrate the 6 com.cole.* paused jobs to Linear-tracke |
| ASK-169 | Sibling of ASK-170/168/167/166/165 under the same job-migration kipi-key with a byte-identical Definition of Ready; only the label com.cole.reddit-pro | Merge into the single com.cole.* migration batch; no separate work item. |
| ASK-168 | Third of six machine-filed job-migration issues sharing one fix shape (plist verify + pause-ledger state + launchd-health-check visibility); reddit-pa | Merge into the com.cole.* migration batch; migrate reddit_worker jobs (producer  |
| ASK-167 | Same job-migration template as ASK-170/169/168/166/165; autobuild lives in the same reddit-build-radar repo as ASK-170's radar-daily and both feed the | Merge into the com.cole.* migration batch; migrate reddit-build-radar jobs (rada |
| ASK-166 | Same machine-filed job-migration template and same four-bars check as its five siblings; prospect-feed differs only in label, 07:00 schedule and prosp | Merge into the com.cole.* migration batch; no standalone issue. |
| ASK-165 | Last of six identical job-migration issues; the weekly (weekday 5) schedule is a plist value, not a different fix, so podcast-weekly-report rides the  | Merge into the com.cole.* migration batch; note the weekly cadence as a per-job  |
| ASK-164 | One of six identical job-migration siblings (ASK-159..164) sharing the kipi-key prefix job-migration/, the same Definition of Ready text, the same che | Batch with ASK-159..163: build the migrate-and-verify runner once (plist templat |
| ASK-163 | Same shape and same fix as ASK-159..164: kipi-key job-migration/com-cole-job-liveness, identical Definition of Ready and identical verification comman | Batch with ASK-159..164: after the shared runner exists, migrate com.cole.job-li |
| ASK-162 | Identical sibling in the job-migration/ series: same paused-pending-migration state, same four-bars section, same out-of-repo plist path, same pass cr | Batch with ASK-159..164: migrate com.cole.fleet-env-health (09:15 daily) using t |
| ASK-161 | Same job-migration/ template as ASK-159..164 down to the Blast radius and Not-doing wording; the interval trigger (every 14400s) instead of a wall-clo | Batch with ASK-159..164: migrate com.cole.delivery-watch with StartInterval 1440 |
| ASK-160 | Sixth instance of the same machine-filed job-migration/ template (identical Outcome, Files, Check and Not-doing text as ASK-159..164), varying only by | Batch with ASK-159..164: migrate com.cole.daily-x-work (08:00 daily) via the sha |
| ASK-159 | Same job-migration/ sibling set as ASK-160..164: identical Definition of Ready, identical verification pair (launchd-health-check.py --dry-run grep pl | Batch with ASK-160..164: migrate com.cole.daily-social (09:00 daily) via the sha |
| ASK-158 | One of six identical job-migration issues (ASK-153..158) filed by the same job-migration scanner with the same kipi-key namespace, same Definition of  | Work ASK-153..158 as one change: build the launchd Linear-reporting wrapper once |
| ASK-157 | Sibling of ASK-153..158 with byte-identical structure aside from job name, schedule (06:00) and the run_daily.sh path; same watchdog check, same pause | Fold into the ASK-153..158 batch; no separate work item. |
| ASK-156 | Sibling of ASK-153..158, and it shares its runner script (gtm/cloud-brain/run_brain.sh) verbatim with ASK-155, so treating it as an independent job wo | Fold into the ASK-153..158 batch; handle the shared run_brain.sh once for both A |
| ASK-155 | Sibling of ASK-153..158 invoking the identical script as ASK-156 (gtm/cloud-brain/run_brain.sh) on an every-1800s interval rather than a weekday-1 06: | Fold into the ASK-153..158 batch; confirm the catchup interval and the 06:40 tri |
| ASK-153 | Sibling of ASK-153..158 (10:00 daily, gtm/scripts/auto_build/run_autobuild.sh) with the same Definition of Ready, same watchdog check and same pause-l | Fold into the ASK-153..158 batch; run run_autobuild.sh once by hand as part of t |
| ASK-152 | Byte-identical template to ASK-151 (same four bars, same DoR, same launchd-health-check.py --dry-run check) differing only in job name, plist path and | Work as one pass with ASK-151 and the remaining job-migration siblings: apply th |
| ASK-151 | Same job-migration template as ASK-152 and ASK-181, same check block (launchd-health-check.py --dry-run / grep <label>, ./kipi health), same 'never DA | Include in the ASK-152 batch pass; do not open a separate branch for this job. |
| ASK-140 | The rule's enforcement already exists and is wired (voice-lint.py at .claude/settings.json:181, voice-substance-lint.py at :216, plus voice-stop-gate. | Work as one change with ASK-139: add an 'Enforced by: <script> (settings.json:<l |
| ASK-139 | token-discipline.md:9 already names the token-guard hook and token-guard.py is wired three times (.claude/settings.json:132,149,161), so 'names NO exe | Same change as ASK-140: name token-guard.py at the top of the file, and for line |
| ASK-138 | The gate fires on a model judgment ('founder shares someone else's content'), which skill-hook-pairing.md explicitly classes as un-hookable and routes | Work as one change with ASK-136 and ASK-135: add q-system/.q-system/skill-evals/ |
| ASK-136 | quick-plan.md:3 self-describes as 'a lightweight, non-gated planning reflex', so the defect is the contradicting ENFORCED header rather than a missing | Fold into the interpretive batch with ASK-138 and ASK-135: drop ENFORCED from th |
| ASK-135 | It is an auto-invoke table whose trigger is a model decision, the exact class skill-hook-pairing.md already lists as 'correctly interpretive (no hook) | Same interpretive batch: one q-system/.q-system/skill-evals/<rule>.json per rule |
| ASK-134 | One of five identical CAP-XX issues (ASK-130/131/132/133/134) minted from the same detector string 'claims ENFORCED but names NO executable'; design-a | Fold into one batch issue: write a rule-enforcement auditor over .claude/rules/* |
| ASK-133 | Same detector string and same fix as ASK-130/131/132/134, and the evidence is partly wrong: coding-standards.md's Python/JS/Shell/JSON style clauses a | In the batch pass, add the format-lint.py citation to .claude/rules/coding-stand |
| ASK-132 | Fifth sibling of the same CAP-XX detector; coding-audhd.md is path-scoped frontmatter (**/*.py, **/*.sh) whose communication and emotional-scaffolding | Handle in the same batch pass: split coding-audhd.md's clauses into the structur |
| ASK-131 | The 'names NO executable' evidence is a false negative here: audhd-lint.py exists in q-system/.q-system/scripts/ and is wired as a hook in .claude/set | In the batch pass, cite audhd-lint.py (and its scope) inside .claude/rules/audhd |
| ASK-130 | Same CAP-XX detector as its four siblings, and in the skeleton anti-misclassification.md is unfilled template ({{YOUR_PRODUCT}}, {{MISCLASSIFICATION_1 | In the batch pass, treat anti-misclassification.md as instance-fill: add a place |
| ASK-100 | Machine-filed inventory card with no Files line; its only actionable content is the 2026-07-26 claim that `test-kipi-update-build-artifacts.sh` covers | Batch with ASK-98/96/95: one pass resolving each cited bare filename to a repo-r |
| ASK-98 | Same shape as ASK-100/96/95: a LIVE inventory card whose cited `dogfood_gate.py` is written as a bare filename that does not resolve, while the hook a | Include in the path-qualification batch: rewrite `dogfood_gate.py` to its plugin |
| ASK-96 | Only `.claude/rules/self-healing-retry.md` resolves; `morning-pipeline.md`, `run-step-audit.py` and `token-guard.py` are cited as bare filenames that  | Include in the path-qualification batch: rewrite to `.claude/rules/morning-pipel |
| ASK-95 | All 10 cited paths (4 bus files, 5 verification harnesses, step-orchestrator.md) are bare filenames that fail to resolve even though the description i | Take this one first in the path-qualification batch since it has the most refere |
| ASK-94 | All three 'MISSING' paths exist as q-system/.q-system/scripts/correction_outcome.py, route-overrides-to-learn.py and test_correction_outcome.py, plus  | Fix the L8/L9 inventory generator to emit repo-relative paths, re-emit the ASK-9 |
| ASK-93 | plugins/kipi-core/skills/rca/ exists and the hooks file is plugins/kipi-core/hooks/hooks.json, not a repo-root hooks.json — the MISSING flag is the ba | Same one-change fix as ASK-94: generator emits repo-relative paths (plugins/kipi |
| ASK-92 | sycophancy-harness.py resolves to q-system/.q-system/sycophancy-harness.py, sycophancy-monthly-check.py and decision-origin-tag-lint.py to q-system/.q | Same one-change fix as ASK-94; this issue contributes the four corrected path st |
| ASK-89 | fleet-loop-board.py and fleet-board-refresh.py both exist at q-system/.q-system/scripts/ — this session's SessionStart hook invokes them by exactly th | Same one-change fix as ASK-94; board staleness is a separate item and does not r |
| ASK-80 | Same 2026-07-26 machine sweep and identical shape to ASK-78 and ASK-79: a LIVE L5 memory capability, tests already present (test_memory_outcomes/refle | Work as one change with ASK-78 and ASK-79: add the L5 memory scripts to the capa |
| ASK-79 | Same sweep and same shape as ASK-78 and ASK-80: memory-freshness-check.py is verifiably live (its SessionStart warning fired in this session) and wire | Work as one change with ASK-78 and ASK-80: one manifest entry per script, then c |
| ASK-78 | Same sweep and same shape as ASK-79 and ASK-80: validator (PostToolUse) and surface (SessionStart) are both wired in settings.json and settings-templa | Work as one change with ASK-79 and ASK-80: one manifest entry per script, then c |
| ASK-62 | Same shape and same fix as ASK-61 and ASK-60: an L2 record asserting LIVE while its declared artifacts (plugin-version-bump-check.py, test_plugin_vers | none |
| ASK-61 | Second sibling of the same declared-vs-actual defect: the record claims ARMED and cites a 29-entry baseline with a classifier_sha256 pin, but state/pr | Include in the ASK-62 batch pass, plus one extra check specific to this record:  |
| ASK-60 | Third sibling of the same defect and the narrowest instance of it: capability-gate.py and fleet-capability-verify.py both resolve, only capability-man | Fix in the same ASK-62 batch pass: resolve the manifest's real path and correct  |
| ASK-56 | Same shape as ASK-57/ASK-55: a LIVE L1 capability card citing test files (test-kipi-rollback.sh, test-kipi-rollback-matrix.sh) as manifest-declared ev | Work ASK-57/56/55 as one change: run the capability-gate verifier over the manif |
| ASK-55 | Third instance of the same declared-test-missing shape (test-lessons-push-guard.sh MISSING while cited as evidence), and it shares a fix with ASK-56/A | Include in the ASK-57/56/55 manifest reconciliation batch; no separate work item |
