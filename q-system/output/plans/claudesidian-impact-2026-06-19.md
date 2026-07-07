# Claudesidian → kipi-system impact analysis

**Date:** 2026-06-19
**Source:** https://github.com/heyitsnoah/claudesidian (heyitsnoah / Alephic / Noah Brier, MIT)
**Method:** 6-dimension workflow (13 agents), each deep-read both repos, adversarial verify on every adopt/OSS claim, then synthesis.

## TL;DR

- claudesidian is an Obsidian PARA "second-brain" starter vault for Claude Code. Skills are markdown verbs over a notes vault; it bundles Anthropic's skill-creator.
- Highest-leverage change for kipi: it exposes one real blind spot kipi has zero coverage on. kipi never measures whether its auto-invoked skills actually fire. Every voice/fable/rca skill bets on description-based triggering, and nothing proves the trigger works. claudesidian's `run_eval.py` (trigger-rate vs should_trigger) is the tool to close that gap.
- Net direction of value is mostly kipi → claudesidian. kipi out-covers it on voice enforcement, propagation, memory, and Obsidian export. It is a strong secondary OSS target, not a source of capabilities.
- Two verifier kills you should not chase: the symlink-repair script (kipi uses `cp -R`, not symlinks, so the failure mode cannot occur) and the "AUDHD skill ships with an eval-set end-to-end" framing (no eval-set exists yet).

## Adopt into kipi

Ranked by leverage. Killed claims (symlink-sync script) are not listed.

| # | What | Lands in | Energy | Time |
|---|------|----------|--------|------|
| 1 | CORRECTED (founder challenge 2026-06-19): kipi already brackets each update with two instance git commits (lines 71-72 pre, 119-122 post) and `--delete` already EXCLUDES my-project/, canonical/, memory/, output/, bus/. So tracked files + key state are recoverable via `git revert`. The REAL gap is narrower: untracked files inside synced dirs get wiped (line 72 is `git add -u`, tracked-only, then `--delete` removes them, no recovery). Fix: `git stash -u`/snapshot untracked before the rsync. | `kipi-update.sh` | Quick Win | ~1h |
| 2 | `kipi update --rollback [instance]` verb. Lower value than originally rated since manual `git revert` of the sync commit already works per-instance; this is just the one-command convenience. | `kipi` (dispatcher) + `kipi-update.sh` | Quick Win | ~1h |
| 3 | Trigger-eval harness: stripped `run_eval.py` core measuring trigger_rate vs should_trigger for founder-voice, audhd-executive-function, rca, fable-discipline. On-demand only (shells `claude -p`, real Opus cost), NOT a hook. | `q-system/.q-system/scripts/skill-trigger-eval.py` + fixtures `q-system/.q-system/skill-evals/<skill>.json` | Deep Focus | 1-1.5 days |
| 4 | Real `--dry` diff: replace the SKEL_COUNT vs INST_COUNT file-count heuristic (lines 136-143) with `rsync -ain --delete` so dry-run lists actual changed/deleted files. | `kipi-update.sh` (else branch, lines 133-145) | Quick Win | 45-60m |
| 5 | Wire the version-skew NUDGE: convert unwired `auto-update.sh` from silent `git subtree pull` (line 61) to a nudge (print "run kipi update", exit 0), register in `settings-template.json` SessionStart so it propagates. | `q-system/hooks/auto-update.sh` + `settings-template.json` | Quick Win | 45m |
| 6 | Resumable per-run JSON manifest (`output/.kipi-update-<date>.json`, PASS/FAIL per instance + skeleton SHA); on re-run skip instances already PASS so a fan-out that dies at instance 11 does not re-clobber the first 10. | `kipi-update.sh` | Deep Focus | 1.5h |
| 7 | Firecrawl scrape-to-file lane (curl + jq, onlyMainContent markdown, fail-closed on empty, CJK-safe filenames). The one integration kipi genuinely lacks. Env-var key only. | `q-system/.q-system/scripts/firecrawl-scrape.py` + `.mcp.json` FIRECRAWL_API_KEY; wire into q-research | Quick Win | 1-2h |
| 8 | Keyword-gated "what skills do I have" discovery hook (pure bash, `\bskills?\b` gate). REWIRE scan target from `.claude/skills/` to `plugins/{kipi-core,kipi-ops,kipi-design}/skills/`. | `plugins/kipi-core/hooks/skill-discovery.sh` + register UserPromptSubmit in `hooks.json` | Quick Win | 45-60m |
| 9 | with-skill-vs-without benchmark delta as one-time proof fable-discipline + prd-os earn their cost. NOTE: `aggregate_benchmark.py` only aggregates, needs an executor + grader.md loop. Not a drop-in. | `q-system/.q-system/scripts/` + outputs to `q-system/output/skill-benchmarks/` | Deep Focus | 1 day+ |
| 10 | Register trigger-eval as a pairing in `skill-hook-pairing.md` + wiring-check bullet. Contingent on #3. Advisory/periodic, NOT a blocking exit-2 bullet. | `.claude/rules/skill-hook-pairing.md` + `.claude/rules/wiring-check.md` | Quick Win | 1-2h |
| 11 | Obsidian Bases (.base) export layer over frontmatter the exporter already writes (`entities.base` + `iocs.base`). | `kipi-investigations/investigations/export/bases.py` + wire into invctl `export-vault` | Deep Focus | 3-4h |
| 12 | Obsidian callouts (`> [!danger]` high threat, `> [!warning]` low-confidence). NOTE: `_render_entity_md` does not currently receive threat_score/confidence, so this also requires passing those in. | `kipi-investigations/investigations/export/obsidian.py` | Quick Win | 1h |
| 13 | Eval-critique lens on `voice-substance-lint.py`: the OR-of-three anchor logic (lines 151-156) passes on one generic proper noun, so a hallucinated draft satisfies it. One-time manual audit. | `q-system/.q-system/scripts/voice-substance-lint.py` | Quick Win | 1h |
| 14 | Emphasis-opener detector in `voice-lint.py`: add "it's worth mentioning" + bare adverb openers "Importantly,/Notably,". NOTE: "it's worth noting" is already in scan-draft.py, just not voice-lint.py. No voice-lint test file exists, must create one. | `q-system/.q-system/scripts/voice-lint.py` | Quick Win | 20-30m |
| 15 | Rhetorical-question-then-answer detector in `voice-lint.py` as WARN-class (not block). Reproducer in a new test file. | `q-system/.q-system/scripts/voice-lint.py` | Deep Focus | 45-60m |

## kipi already has this (skip)

claudesidian is thinner on every one.

- **Voice / anti-AI enforcement.** `voice-lint.py` (exit-2 blocking on every Edit/Write) already catches every pattern de-ai-ify names by word (utilize/leverage/optimize/furthermore/moreover, "in today's"/"let's dive in"/"it's important to note", em-dash, rule-of-three, comma-triplets). de-ai-ify is prose-only with zero detectors. Plus kipi has identity voice (voice-dna.md) + substance enforcement de-ai-ify has no notion of.
- **Fleet propagation.** `kipi update` fans one skeleton to 18 instances with a deterministic Python settings.json union + self-healing git hygiene. claudesidian updates one vault, picks a whole-file winner.
- **Update safety (PARTIAL, corrected).** kipi already brackets each instance update with two git commits (pre + post) and excludes my-project/canonical/memory/output/bus from `--delete`, so tracked files and key state are revertable. Only untracked-file loss + a one-command rollback verb are missing. claudesidian's backup-to-.backup/ + rollback is more explicit but covers a gap kipi mostly already covers.
- **Rule-based semantic auto-invoke.** kipi's `*-auto-invoke.md` rules fire on meaning. claudesidian's skill-discovery.sh fires only when you literally type "skill".
- **Memory + debrief.** /q-debrief (12 lenses + canonical routing + graph.jsonl), decay-aware memory, md-prune auto-archival, /q-handoff RESUME. claudesidian's thinking-partner/daily-review/weekly-synthesis are thinner, no decay, no auto-prune. Do NOT port them.
- **Obsidian export.** kipi-investigations already ships `export/obsidian.py` + `export/canvas.py` (FAANG-bar JSON Canvas). claudesidian's json-canvas/obsidian-markdown skills are spec docs for output kipi already generates programmatically.
- **Web/social scraping.** apify, reddit, playwright, perplexity, NotebookLM already in `.mcp.json`. Only Firecrawl's scrape-to-file lane (#7) is net-new.

## OSS contribution opportunity

claudesidian is a strong secondary target (MIT, active, skills-native, README solicits new skills + scripts, faster feedback than anthropics/skills). Ranked by fit + likely acceptance.

1. **AUDHD executive-function skill (best fit).** claudesidian has ZERO neurodivergent layer and a notes vault is exactly where executive-function accommodations land. Same skill model. Contribute only A1-A7 + language rules; strip the kipi schedule/CRM/pipeline coupling. Mission already aims this at anthropics/skills, so log claudesidian as a second home, not a substitution.
2. **de-ai-ify deterministic lint upgrade.** Their de-ai-ify is 90 lines of prose, no hook. kipi has the battle-tested stdlib-only detector with Assaf-identity rules cleanly isolated (stats-ban line 121, slash-ban line 133) so they can be stripped. Ship generic detectors ADVISORY, not exit-2. This is the literal "skills generate, hooks validate" pattern.
3. **JSON Canvas generator (`export/canvas.py`) into their json-canvas skill.** Theirs is pure spec; canvas.py is a working generator. Contribute as a worked example, not a drop-in (reads OSINT from SQLite).
4. **settings.json deterministic union into their `/upgrade` skill, as an OPTIONAL non-interactive merge mode.** Their upgrade loses user-added hooks when upstream also touches settings.json. Must be opt-in (their design rule is "always wait for input").

**Anti-recommendations (confirmed):** do NOT route prd-os closeout-receipts or capability-token here (a notes vault has no findings-gate or destructive-agent-op surface; mission already routes those to rhuss/cc-spex and dwarvesf/claude-guardrails). And contribute "skill + paired runtime lint hook" now, add evals only after adopt #3 ships a harness.

## Conflicts / risks

- **HARD architecture conflict on the symlink scheme.** folder-structure.md (ENFORCED) bans `.claude/skills/`; claudesidian's whole portability layer depends on it. kipi uses `cp -R`, no symlinks. Adopting the symlink convention wholesale would violate kipi's placement rule.
- **Cross-tool portability is theoretical even in claudesidian:** only `.claude` and `.pi` dirs exist; OpenCode/Codex/Cursor have no wiring. Re-confirms the Opencode-parked decision (2026-05-14).
- **Token/cost blowup on the eval loop.** `run_loop.py` fans out many real `claude -p` subprocesses. Adopt only the single-pass trigger check with a tiny eval-set; skip the auto-improve loop. Run evals OUTSIDE a live session.
- **Description auto-rewrite is a voice-drift hazard.** `improve_description.py` LLM-rewrites skill descriptions; kipi's descriptions are load-bearing trigger phrasing. Keep human-in-the-loop.
- **Backup placement.** `output/` is NOT blanket-gitignored, so adopt #1 must add an explicit `.gitignore` entry.
- **Path mismatch in instance-registry.json** (`/Users/assafkip/` vs this checkout `/Users/assafkipnis/`). Backup/rollback must no-op safely on SKIP.
- **Cross-instance boundary:** #11/#12 land in `~/projects/kipi-investigations` (separate repo, own .prd-os). Confirm before editing there.

## Next actions

1. Close the narrow propagation gap (Quick Win, ~1h, CORRECTED): kipi already protects tracked files + key dirs via git-bracket commits and `--delete` excludes. Only missing piece is untracked-file loss on sync. Fix: `git stash -u` (or snapshot untracked) before the rsync at `kipi-update.sh:111`, optional `--rollback` convenience verb. NOT the 3h Deep Focus originally rated. Start: `code kipi-update.sh`
2. Build the trigger-eval harness for the 4 high-stakes skills (Deep Focus, ~1 day): on-demand, tiny eval-set, no hook. Closes the one gap the deterministic lint layer structurally cannot see. Start: create `q-system/.q-system/scripts/skill-trigger-eval.py`
3. Open the AUDHD-skill PR to heyitsnoah/claudesidian (Admin, ~2h): de-claudified A1-A7 + language subset as `.agents/skills/neurodivergent/SKILL.md`. Best-fit, highest-acceptance, on-mission. Start: `gh repo fork heyitsnoah/claudesidian --clone`
