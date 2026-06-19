# Canonical Brief: Harvesting claudesidian for kipi

**Status:** Living document. kipi-system-local (not synced to instances, lives in `output/` so untracked by default).
**Created:** 2026-06-19
**Source repo:** https://github.com/heyitsnoah/claudesidian (heyitsnoah / Alephic / Noah Brier, MIT, featured on Every.to)
**Companion:** `q-system/output/plans/claudesidian-impact-2026-06-19.md` (the raw 6-dimension analysis this brief distills).

---

## 0. Why this brief exists (the compounding contract)

The goal is not a one-time read of one repo. The goal is a repeatable way to mine ANY external Claude-Code / agent repo for kipi improvements, where each pass leaves a durable, honest record that the next pass builds on. This file is harvest entry #001. The method below is reusable for entry #002 onward.

**Three rules that make it compound instead of rot:**

1. **Verify before you claim.** Every "kipi should add X" must be checked against kipi's actual files, not assumed. The first version of this analysis claimed kipi had "zero update safety net." False. kipi already brackets every instance update with two git commits and excludes the high-value dirs from `--delete`. An adversarial verify pass caught it. No item enters this ledger as "adopt" until someone opened the kipi file and confirmed the gap is real.
2. **Tag every claim by who verified it.** `[VERIFIED-direct]` = a human/founder opened the file and confirmed. `[agent-reported]` = came from a subagent, treat line numbers as approximate, re-verify before implementing. This single tag is why the ledger does not accumulate plausible-but-wrong facts.
3. **Track status to closure.** Each item moves PROPOSED -> IN-PROGRESS -> ADOPTED / REJECTED / CONTRIBUTED-UPSTREAM. A harvested idea that is never closed out is noise. The brief is the running record of what was actually done.

---

## 1. The reusable harvest method (for the next repo)

When mining the next external repo, run this:

1. **Clone + scope.** Clone to `/tmp`, list the tree, read README + package manifest + the config/settings + 2-3 representative skill/hook files. Build the work-list of subsystems.
2. **Pick comparison dimensions.** Map the repo's subsystems onto kipi's (skills, propagation/update, eval, memory/knowledge, voice/anti-AI, integrations, OSS-fit). One dimension per agent.
3. **Fan out compare-then-verify.** Each dimension agent reads BOTH repos and produces a structured compare. Then an adversarial verifier checks every adopt/OSS claim against the real kipi repo and kills the ones kipi already covers. (This is the `Workflow` pipeline pattern; the claudesidian run used 13 agents.)
4. **Founder spot-check the top claims.** The founder challenges the highest-leverage 1-2 items directly against the files. This is where the #1 overstatement got caught. Do not skip it.
5. **Append a ledger entry here** with the add/change spec, the skip list, the OSS-contribution direction, conflicts, and the verification log.

### Ledger entry schema (copy for entry #002+)

```
## Entry NNN: <repo>
- Source / license / why-relevant
- Direction of value (kipi <- repo  vs  kipi -> repo)
- ADD / CHANGE spec (table: ID | area | change | lands-in | effort | status | verify-tag)
- kipi already has (skip list)
- OSS contribution opportunities (kipi -> repo)
- Conflicts / risks
- Verification log (what was checked against actual files, incl. anything corrected)
```

---

## 2. Entry #001: claudesidian

**What it is:** An Obsidian PARA "second-brain" starter vault for Claude Code. Skills are markdown verbs over a notes vault (`.agents/skills/<name>/SKILL.md` canonical, symlinked into `.claude/` and `.pi/`). It bundles Anthropic's skill-creator (with an eval/benchmark/grader loop), a `/upgrade` system, Gemini-vision MCP, and Firecrawl scrape scripts.

**Direction of value:** Mostly **kipi -> claudesidian**. kipi out-covers it on voice enforcement, fleet propagation, memory, and Obsidian export. claudesidian surfaces exactly one capability kipi lacks (skill-trigger measurement) and a few small hardening + detector top-ups. It is a strong OSS contribution target, not a capability source.

---

### 2A. ADD / CHANGE spec (the full list)

Master table first, detail blocks below. Effort tags: Quick Win (<2h) / Deep Focus (half-day+) / Admin.

| ID | Area | Add / Change | Lands in | Effort | Status | Verify |
|----|------|--------------|----------|--------|--------|--------|
| H1 | Skill measurement | Build a skill-TRIGGER eval harness (does the skill fire when it should) | `q-system/.q-system/scripts/skill-trigger-eval.py` + fixtures `q-system/.q-system/skill-evals/<skill>.json` | Deep Focus (~1 day) | PROPOSED | VERIFIED-direct (absence confirmed) |
| H2 | Propagation safety | Guard untracked files before the destructive `--delete` sync | `kipi-update.sh` (before line 111) | Quick Win (~1h) | PROPOSED | VERIFIED-direct |
| H3 | Propagation safety | `kipi update --rollback [instance]` convenience verb | `kipi` dispatcher + `kipi-update.sh` | Quick Win (~1h) | PROPOSED | VERIFIED-direct |
| H4 | Propagation UX | Real `--dry` diff (replace file-count heuristic with `rsync -ain --delete`) | `kipi-update.sh` lines 133-145 | Quick Win (~45m) | PROPOSED | VERIFIED-direct |
| H5 | Propagation UX | Version-skew NUDGE at session start (wire the unwired `auto-update.sh`) | `q-system/hooks/auto-update.sh` + `settings-template.json` | Quick Win (~45m) | PROPOSED | agent-reported |
| H6 | Propagation safety | Resumable per-run manifest (skip instances already PASS on re-run) | `kipi-update.sh` | Deep Focus (~1.5h) | PROPOSED | agent-reported |
| H7 | Integrations | Firecrawl scrape-to-file lane (the one integration kipi lacks) | `q-system/.q-system/scripts/firecrawl-scrape.py` + `.mcp.json` env key; wire into q-research | Quick Win (~1-2h) | PROPOSED | agent-reported |
| H8 | Voice-lint | Emphasis-opener detector ("it's worth mentioning", "Importantly,", "Notably,") | `q-system/.q-system/scripts/voice-lint.py` | Quick Win (~20-30m) | PROPOSED | agent-reported |
| H9 | Voice-lint | Rhetorical-question-then-answer detector (WARN class) | `q-system/.q-system/scripts/voice-lint.py` | Deep Focus (~1h) | PROPOSED | agent-reported |
| H10 | Voice substance | Tighten the OR-of-three anchor logic that passes on one generic proper noun | `q-system/.q-system/scripts/voice-substance-lint.py` (~lines 151-156) | Quick Win (~1h) | PROPOSED | agent-reported |
| H11 | Skill discovery | Keyword-gated "what skills do I have" hook, rewired to scan `plugins/*/skills/` | `plugins/kipi-core/hooks/skill-discovery.sh` + `hooks.json` | Quick Win (~45-60m) | PROPOSED | agent-reported |
| H12 | Skill measurement | with-skill-vs-without benchmark delta (one-time proof skills earn their cost) | `q-system/.q-system/scripts/` -> `q-system/output/skill-benchmarks/` | Deep Focus (1 day+) | PROPOSED, depends on H1 | agent-reported |
| H13 | Wiring | Register H1 trigger-eval as a pairing + wiring-check bullet (advisory, not blocking) | `.claude/rules/skill-hook-pairing.md` + `.claude/rules/wiring-check.md` | Quick Win (~1-2h) | PROPOSED, depends on H1 | agent-reported |
| H14 | Investigations (cross-repo) | Obsidian Bases (.base) export over existing frontmatter | `kipi-investigations/.../export/bases.py` | Deep Focus (~3-4h) | PROPOSED, confirm cross-repo first | agent-reported |
| H15 | Investigations (cross-repo) | Obsidian callouts for threat/confidence tiers | `kipi-investigations/.../export/obsidian.py` | Quick Win (~1h) | PROPOSED, confirm cross-repo first | agent-reported |

**Killed during verify (do NOT build):** a symlink-sync repair script (kipi uses `cp -R`, no symlinks, the failure mode cannot occur); a from-scratch "PARA inbox" (q-system/memory/working/ + debrief routing already cover capture).

---

### Detail blocks

**H1 — Skill-trigger eval harness (the one real capability gap).**
- **Gap (VERIFIED-direct):** Grepped the whole repo for `should_trigger / run_eval / trigger_rate / skill-eval / trigger.accuracy`. Zero kipi-authored hits. Every existing harness (`sycophancy-harness.py`, `voice-lint.py`, `validate-separation.py`, `instruction-budget-audit.py`) validates OUTPUT or STRUCTURE after the model already chose to act. Nothing measures whether an auto-invoked skill fires when it should. founder-voice, audhd-executive-function, rca, fable-discipline all bet on description-based triggering with no proof it works.
- **Change:** Port the CORE of claudesidian's `run_eval.py` (in `.agents/skills/skill-creator/scripts/`): a single-pass check that, for a tiny fixture set of prompts labeled `should_trigger: true/false`, shells `claude -p` and records whether the target skill loaded. Report trigger_rate. On-demand only, NOT a hook (each run costs real Opus calls).
- **Acceptance:** `skill-trigger-eval.py founder-voice` runs the fixtures and prints a trigger_rate; a deliberately off-topic prompt scores false; an obvious on-topic prompt scores true.
- **Risk:** `run_loop.py` (the auto-improve fan-out) is the expensive part. Adopt only the single-pass check, skip the loop. Strips `CLAUDECODE` to nest sessions, which can trip kipi's token-guard / voice-stop-gate. Run evals OUTSIDE a live session.

**H2 — Untracked-file guard (the CORRECTED propagation gap).**
- **What kipi ALREADY has (VERIFIED-direct, this was the #1 overstatement):** `kipi-update.sh` line 71-72 commits the instance's tracked changes BEFORE sync (`chore: auto-commit before kipi update`). Line 111-116 rsync `--delete` EXCLUDES `my-project/`, `canonical/`, `memory/`, `output/`, `.q-system/agent-pipeline/bus/`. Line 119-122 commits the synced changes after. So tracked files + all high-value instance state are recoverable via `git revert`. There is NO "clobber the instance" scar here.
- **The narrow REAL gap:** line 72 is `git add -u` (tracked-only). A NEW untracked file inside a synced dir (e.g. something dropped in `.q-system/` or `marketing/`) is not committed, then `--delete` removes it, with no recovery.
- **Change:** before the rsync at line 111, `git -C "$path" stash push -u` (or snapshot untracked to the backup dir), restore/clear after a clean sync. Small.
- **Acceptance:** a test drops an untracked file into a synced dir, runs the update, asserts the file survives or is in the stash.

**H3 — `--rollback` verb.** Lower value than first rated, because manual `cd <instance> && git revert <sync-commit>` already works (the bracket commits make it possible). This is convenience only: a verb that finds the last `chore: sync q-system from skeleton` commit per instance and reverts it. Add to the `case` block in the `kipi` dispatcher (currently: update/new/dev/sync-skills/push/check/migrate/cluster/list/home/help, NO rollback).

**H4 — Real `--dry` diff.** Current dry-run (lines 133-145) compares `SKEL_COUNT` vs `INST_COUNT` file counts, a coarse heuristic. Replace with `rsync -ain --delete <src> <dst>` (the `n` = dry-run, `i` = itemize) so `kipi update --dry` lists the actual changed and deleted files per instance.

**H5 — Version-skew nudge.** `q-system/hooks/auto-update.sh` exists but is unwired and (per agent) silently does `git subtree pull`. Convert to a nudge: detect skew, print "run kipi update", exit 0. Register in `settings-template.json` SessionStart so new instances inherit it. [agent-reported: confirm auto-update.sh contents + that it is unwired before changing.]

**H7 — Firecrawl scrape-to-file.** The one integration kipi genuinely lacks (kipi already has apify, reddit, playwright, perplexity, NotebookLM in `.mcp.json`). claudesidian's `.scripts/firecrawl-scrape.sh` saves FULL article markdown to a file instead of summarizing into context. Port as `firecrawl-scrape.py` (curl + jq, `onlyMainContent`, fail-closed on empty body, CJK-safe filenames), env-var key only, wire into `/q-research`. [agent-reported: confirm `.mcp.json` does not already have a firecrawl entry.]

**H8 / H9 / H10 — Voice-lint top-ups.** kipi's `voice-lint.py` already blocks (exit 2) every word/phrase de-ai-ify names (utilize/leverage/optimize/furthermore/moreover, "in today's"/"let's dive in"/"it's important to note", em-dash, rule-of-three, comma-triplets). The only net-new detectors worth lifting: emphasis-openers (H8), rhetorical-question-then-answer as WARN (H9), and tightening voice-substance's anchor logic that currently passes on a single generic proper noun (H10). [agent-reported: all three line numbers and the "already in scan-draft.py not voice-lint.py" claim need a 5-min re-check before editing. No voice-lint test file exists; one must be created.]

**H14 / H15 — Investigations Obsidian (CROSS-REPO).** These land in `~/projects/kipi-investigations`, a SEPARATE repo with its own `.prd-os`. Per the founder's handoff caveat and the cross-instance preflight rule, confirm the target path + get explicit OK before editing there. The investigations exporter already ships `export/obsidian.py` and `export/canvas.py` but no `bases.py` (agent confirmed the missing file). Bases (.base) gives a zero-backend filtered view over frontmatter the exporter already writes; callouts color threat/confidence tiers.

---

### 2B. kipi already has this (skip list)

claudesidian is thinner on every one. Do not rebuild.

- **Voice / anti-AI enforcement.** `voice-lint.py` exit-2 blocks on every Edit/Write and catches every pattern de-ai-ify names by word, plus identity voice (`voice-dna.md`) and substance checks de-ai-ify has no notion of. de-ai-ify is prose-only, zero detectors.
- **Fleet propagation.** `kipi update` fans one skeleton to 18 instances with a deterministic Python settings.json union + self-healing git hygiene. claudesidian updates one vault and picks a whole-file winner.
- **Update safety (PARTIAL, corrected).** Bracket commits + `--delete` excludes already protect tracked files and key state. Only untracked-loss (H2) + rollback verb (H3) are missing.
- **Rule-based semantic auto-invoke.** kipi's `*-auto-invoke.md` rules fire on meaning. claudesidian's `skill-discovery.sh` fires only when you literally type "skill".
- **Memory + debrief.** /q-debrief (12 lenses + canonical routing + graph extraction), decay-aware memory, md-prune auto-archival, /q-handoff RESUME. claudesidian's thinking-partner / daily-review / weekly-synthesis are thinner, no decay, no auto-prune. Do NOT port.
- **Obsidian export.** kipi-investigations already ships `export/obsidian.py` + `export/canvas.py` (FAANG-bar JSON Canvas). claudesidian's json-canvas / obsidian-markdown skills are spec docs for output kipi already generates programmatically.
- **Web/social scraping.** apify, reddit, playwright, perplexity, NotebookLM already wired. Only Firecrawl's scrape-to-file lane (H7) is net-new.

---

### 2C. OSS contribution opportunities (kipi -> claudesidian)

claudesidian is a strong SECONDARY target for the OSS-contribution mission (MIT, active, skills-native, README explicitly solicits new skills + scripts, faster feedback than anthropics/skills). Aligns with `q-system/output/plans/oss-contribution-mission-2026-06-16.md`. Ranked by fit + likely acceptance.

1. **AUDHD executive-function skill (best fit).** claudesidian has ZERO neurodivergent layer; a notes vault is exactly where executive-function accommodations land. Same skill model. Contribute only A1-A7 + language rules as `.agents/skills/neurodivergent/SKILL.md` + the two symlinks; strip the kipi schedule/CRM/pipeline coupling. Log claudesidian as a SECOND home, not a substitution for the anthropics/skills target.
2. **de-ai-ify deterministic-lint upgrade.** Their de-ai-ify is ~90 lines of prose, no hook. kipi has the battle-tested stdlib-only detector with the Assaf-identity rules cleanly isolated so they can be stripped. Ship the generic detectors ADVISORY (not exit-2). This is the literal "skills generate, hooks validate" signature pattern from the mission.
3. **JSON Canvas generator (`export/canvas.py`)** into their json-canvas skill, as a worked example (not a drop-in; it reads OSINT from SQLite).
4. **settings.json deterministic union** (from `kipi-update.sh`) into their `/upgrade` skill, as an OPTIONAL non-interactive merge mode. Their upgrade loses user-added hooks when upstream also touches settings.json. Must be opt-in (their design rule is "always wait for input").

**Anti-recommendations (confirmed):** do NOT route prd-os closeout-receipts or capability-token to claudesidian. A notes vault has no findings-gate or destructive-agent-op surface; the mission already routes those to rhuss/cc-spex and dwarvesf/claude-guardrails. And contribute "skill + paired runtime lint hook" now; add evals only after H1 ships a harness to run them.

---

### 2D. Conflicts / risks

- **HARD architecture conflict on the symlink scheme.** `folder-structure.md` (ENFORCED) BANS `.claude/skills/`; claudesidian's whole portability layer depends on it. kipi uses `cp -R` plugin propagation, no symlinks. Adopting the symlink convention wholesale would violate kipi's placement rule. (This is why the symlink-sync script was killed.)
- **Cross-tool portability is theoretical even in claudesidian:** only `.claude` and `.pi` dirs exist; OpenCode/Codex/Cursor have no wiring (README overstates it). Re-confirms the Opencode-parked decision (2026-05-14). Gives kipi no turnkey cross-tool path.
- **Token/cost blowup on the eval loop.** Adopt only the single-pass trigger check (H1) with a tiny fixture set; skip the auto-improve loop. Run evals outside a live session.
- **Description auto-rewrite is a voice-drift hazard.** claudesidian's `improve_description.py` LLM-rewrites skill descriptions; kipi's descriptions are load-bearing trigger phrasing ("ALWAYS USE"). Keep description changes human-in-the-loop, never auto-commit. Do NOT port this script.
- **Path mismatch in `instance-registry.json`** (`/Users/assafkip/` vs this checkout `/Users/assafkipnis/`). Several registered instances will not resolve; H2/H3/H6 backup+rollback must no-op safely on SKIP, not error.
- **Cross-instance boundary:** H14/H15 land in `~/projects/kipi-investigations` (separate repo, own .prd-os). Confirm before editing there.

---

### 2E. Verification log (what was actually checked)

- **[VERIFIED-direct] H1 absence:** `grep -rniE 'should_trigger|trigger_rate|run_eval|skill.?eval|did.?fire|trigger.?accuracy'` across repo (minus venv) = no kipi-authored harness. Confirmed.
- **[VERIFIED-direct] H2/H3 propagation:** read `kipi-update.sh` lines 95-154 and the `kipi` dispatcher in full. Confirmed bracket commits (71-72, 119-122), `--delete` excludes (112-116), and NO rollback verb in the dispatcher case block. **CORRECTED the original "zero safety net" claim** to "partial coverage, narrow untracked-file gap."
- **[agent-reported, re-verify before implementing]** All voice-lint / voice-substance line numbers (H8-H10), the firecrawl `.mcp.json` absence (H7), the `auto-update.sh` unwired state (H5), and the investigations `bases.py` absence (H14). High confidence, but the agents overstated #1 once; open the file and confirm before editing.

---

## 3. Recommended execution order

1. **H1 (Deep Focus, ~1 day)** — the trigger-eval harness. The single real capability gap; everything else is hardening or polish.
2. **H2 (Quick Win, ~1h)** — untracked-file guard. Closes the one genuine propagation hole.
3. **OSS #1 (Admin, ~2h)** — AUDHD-skill PR to claudesidian. On-mission, highest acceptance odds, async. Start: `gh repo fork heyitsnoah/claudesidian --clone`.
4. Batch the remaining Quick Wins (H3/H4/H7/H8) in one propagation-and-voice session.

---

## 4. Next harvest candidates (compound forward)

When ready to mine the next repo, append Entry #002 using the schema in section 1. Candidates implied by this analysis:
- Anthropic's `skill-creator` directly (claudesidian only bundles it) for the eval methodology behind H1/H12.
- The OSS-mission targets already in flight (rhuss/cc-spex, dwarvesf/claude-guardrails) for reverse-harvest (what THEY do that kipi could adopt).

---

# Addendum A: System-wide learning + Obsidian-live (founder challenge 2026-06-19)

## The founder's two intuitions, judged

Two things raised:
1. **Cross-instance learning** is the highest-leverage missing piece: a lesson learned in one of the ~20 kipi instances should reach the other 17-19.
2. **"Make kipi live in Obsidian"** (the way claudesidian does) is how you get that.

Verdict, split cleanly:
- **Intuition 1 is correct.** It is the new top item, above H1. Nothing else in the brief compounds across the fleet. The brief's own skip-list already concedes the gap (siloed auto-memory, empty rollup stubs, bridge carries state not learning).
- **Intuition 2 is a misread of what claudesidian does.** Claudesidian does NOT do cross-instance learning. It is ONE vault per user. Its weekly synthesis is cross-FOLDER synthesis inside that single vault, not cross-repo. "Live in Obsidian" there means file SYNC of that one vault (iCloud / git / paid Obsidian Sync), nothing more. It cannot manufacture edges between notes in two confidential repos because, in claudesidian's world, there is only ever one repo.

So the cross-instance gap is real, but it is **kipi's native frontier** (inspired by claudesidian's synthesis idea, not copied from a capability it has). Obsidian is a viewer. The engine has to be built either way.

## The real gap

kipi learns inside each instance and never across the ~20. Siloed today, per instance: per-project auto-memory (`~/.claude/projects/<instance>/memory/MEMORY.md`), debrief outputs, RCAs (`q-system/output/rca/`), scars/corrections, the memory store itself (`q-system/memory/`, with `weekly/` + `monthly/` rollups confirmed still `.gitkeep` stubs, so the corpus is currently thin).

Rails that exist, and why none carry learning:
- **`kipi update` (down):** skeleton -> instances, structure only. `rsync -a --delete` excluding my-project/, canonical/, memory/, output/, bus/ (lines 111-116). No instance-originated learning.
- **`kipi push` (up):** instance -> skeleton, generic code only. Its safety scanner exists to keep instance-specific content OUT of the skeleton.
- **KTLYST bridge (`~/.ktlyst/bridge/`):** cross-instance STATE (5 files across 5 same-company instances). No accumulated learning, and does not reach the consulting/client instances.

The producers (rca, learn-from-correction) exist. The consumer does not. That is the whole gap.

## Confidentiality: the thing Noah never faces (the make-or-break)

Noah's claudesidian is one vault for one user. There is no other client to leak to. kipi has mutually-confidential clients in separate repos. The stress-test found a concrete A-to-B leak in the FIRST design:

A consulting instance writes an RCA scar. A scar only earns promotion because of the specific that made it sting, so the body names a client's investigation target ("...correlating the burner across the <client-target> case..."). The first design gated promotion with `kipi-push-upstream.sh`'s existing scanner (line 26):
```
grep -ril "KTLYST\|ktlyst\|CISO\|re-breach\|Assaf\|/Users/" ... | head -5
```
Six KTLYST-flavored tokens, `head -5` truncation. ZERO consulting-client names, zero target/case codenames, zero PII regex. The client target matches none of the six tokens, scanner exits 0, the lesson lands in the skeleton, then `rsync -a --delete` (no `lessons/` exclude) fans it verbatim into every instance including competing clients, with no per-instance veto. Client A's target is now in client B's working context.

**Blocking.** Structural, not an edge case. The ranking + both architects claimed the gate "fail-closed rejects on any client token." False on inspection (neither read what the scanner matches). The fix is not a better scrubber.

## Recommended architecture (re-architected after the stress-test rejected v1)

Confidentiality model, enforced deterministically at the WRITE step, fail-closed:
- **Shareable = HOW.** Reusable patterns (single-writer chokepoint, verify-against-a-copy), process methodology, RCA root-cause *types*.
- **Unshareable = WHAT.** Any client name, target/case codename, `/Users/` path, deliverable content, debrief/canonical body, dollar figure, PII.
- If the shared store never contains client data, there is nothing to leak at read time.

The safe design:
1. **Promotion rule is v1, not v2:** a lesson is eligible to go fleet-wide only when the same pattern independently recurs in **2+ unrelated instances**. A pattern common to two unrelated clients is de-identified by construction. This is the one structurally-sound control.
2. **Only `kind=pattern` and `kind=methodology` are eligible.** `kind=scar` and `kind=rca` are FORBIDDEN from the shared folder. The specific that makes a scar worth promoting IS the WHAT you cannot share. Raw scars stay instance-local in `q-system/memory/` (already update-excluded).
3. **Promotion is a human-authored net-new abstracted restatement** you write by hand, never an auto-scrub of an existing scar.
4. **Keep the clever fan-out:** one committed `q-system/lessons/` folder NOT in the `kipi update` exclude list rides the existing daily rail into every instance for free. No 19th repo.
5. **Single-writer fix:** `lessons/` is written by ONE path. Promotion writes to the skeleton via a separate curated step, not a subtree push that collides with the down-rsync (a two-writer collision would violate fable-discipline's own single-writer rule).
6. **The 6-token scanner is a backstop only,** and only after it gains real coverage (email/currency regex + a client/target/case-codename roster kept OUTSIDE the synced skeleton).

`{{UNVALIDATED}}`: the false-negative rate of any future content scanner is unmeasurable until a real corpus exists. The safe path does not depend on the scanner being perfect. That is the point.

## Obsidian-live: verdict

What it actually means: file SYNC of ONE vault (iCloud / git / paid Obsidian Sync). Not a server, not a shared brain.

What kipi already uses (confirmed): `q-system/.obsidian-starter/` (committed config, pre-enables Dataview), `q-system/CRM-Dashboard.md` (working Dataview, its footer says "No sync, no API, no database. Same files, visual view."), `q-system/.q-system/onboarding/guides/connect-obsidian.md`, and the investigations `export/obsidian.py` + `export/canvas.py`.

**Orthogonal, not load-bearing.** Obsidian is a viewer (graph / backlinks / Dataview / canvas) plus mobile + sync. It does not create cross-instance learning. A graph cannot draw edges between notes that were never gathered. Build the aggregator first; Obsidian renders it later. Options: (A) status quo 18 vaults, Quick Win; (B) the sanitizing aggregator on the `lessons/` rail, Deep Focus; (C) a unified meta-vault, which REQUIRES B first, multi-day.

## Ranking vs the brief

- **System-wide learning = H0. Outranks H1.** Every brief item is single-instance; none move a lesson from A to B. H0 is the only item whose value compounds across the fleet, and it gives the per-instance producers (rca, learn-from-correction) their first consumer.
- The cheap fan-out spine can ship near the Quick Wins, but the confidentiality engine is Deep Focus and must precede any push. The safe version is the actual product, not "one focused session."
- **Obsidian-live = optional v3 bolt-on,** alongside H14/H15, below H0 and H1/H2. A viewer, never a blocker.

## Next action

**Normalize `instance-registry.json`** path spellings from `/Users/assafkip/...` to the canonical `/Users/assafkipnis/...`.

CORRECTED (direct recon 2026-06-19): `/Users/assafkip` is a root-owned SYMLINK to `/Users/assafkipnis` (same inode confirmed on 4_points_consulting and kipi-system; same git HEAD). There are NO duplicate on-disk trees, and every registry path already resolves through the symlink. The earlier "duplicate physical copies / fix-first blocker / lesson written to a tree nobody is watching" claim was an AGENT OVERSTATEMENT (the second this session, after "zero update safety net" on H2). Lesson for the harvest method: an agent reporting "two paths both exist" is not evidence of duplication until someone checks the inode / symlink. Ground before you diagnose.

The real issue is minor and non-destructive: 14 instance entries + the skeleton + the standalone use the symlink alias, so they break ONLY if that root-owned symlink is ever removed; and 4 Desktop entries (VC_Reachout already marked merged, car-research, q-education, q-investigate-osint-bot) point at dirs gone from disk. **[Admin, ~20m, LOW priority]** This is hygiene that hardens against a symlink removal, NOT a blocker for H0. H0 (cross-instance learning) can proceed independently.
