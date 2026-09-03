<!-- voice-lint-skip -->
<!-- prompt-only-enforcement-skip: this is an audit REPORT under q-system/output/, not a rule file. Every line the guard flags is a quotation of existing or proposed rule text being audited (R-1, R-2, R-6, R-17, S-1, S-7, X-1 and the Part B table). It ships no enforcement of its own; finding R-25 is where unbacked ENFORCED labels are reported rather than created. -->
# Prompt audit, kipi-system, 2026-09-02

Produced by `/claude-api prompt-audit`. Two deliverables: Part A is the report (every finding with location, evidence, pattern, why it is obsolete for the target model, provenance, confidence, action). Part B is the proposed diff, one hunk per finding, indexed by file. Nothing was applied.

## Assumptions (correct by re-running with a narrower request)

- **Scope:** the whole repo's prompt surface. 83 files read in full: `CLAUDE.md`, `q-system/CLAUDE.md`, 38 files in `.claude/rules/`, 5 in `.claude/agents/`, 2 in `.claude/output-styles/`, 15 `SKILL.md` (plus the references each says to read first), 22 plugin command prompts, every context-injecting hook script wired in `.claude/settings.json`, 16 real headless `claude -p` call sites, the 73 tool descriptions in `plugins/kipi-core/kipi-mcp/src/kipi_mcp/server.py`, and the `com.kipi.*` launchd plists (read only). The founder's global `~/.claude/CLAUDE.md` is outside the repo and is cited only where an in-repo rule disagrees with it.
- **Target model:** interactive surfaces run on Claude Fable 5.1 (the model running this session). Headless `claude -p` jobs are pinned to `claude-opus-5` by fleet rule. `.claude/agents/*.md` pin per `model-allocation.md`; those pins are validated policy and were not flagged.
- **No Anthropic SDK code exists.** All model calls go through the `claude` CLI. Non-Anthropic markers found only in the OpenAI TTS script (`say-last-response.py`) and Codex review fixtures, both outside the prompt surface.
- **Verification method:** four read lanes produced findings; every High-confidence claim was then re-checked independently by existence tests (`verify_highs.py`, 17 checks, 16 pass). The one failure downgraded R-4 from High to Medium (details there).

## Summary

| Group | High | Medium | Low / flag |
|---|---|---|---|
| 1 Dated prompt text (rules, styles, commands, agents, injectors) | 6 | 22 | 14 |
| 2 Brittle skill files | 3 | 11 | 4 |
| 3 Tool descriptions | 1 | 5 | 0 |
| 4 Request config and architecture | 2 | 11 | 4 |
| **Raw lane total** | **12** | **49** | **22** |
| **Distinct findings** | **12** | **48** | **20** |

**80 distinct findings, not 83.** The group rows above are the raw per-lane attribution, and three defects were found by two lanes each: R-3 is C-15, R-13 is X-3, R-24 is X-15. Each is written once below under the first id, with the second noted. The enumerated ids are the count that matters; the status ledger at `prompt-audit-2026-09-02-ledger.json` carries all 80 with a status field.

Greppable signals came back clean: zero "think step by step" or scratchpad scaffolds, zero anti-formatting rules, zero identity stubs, low caps-emphasis density. The findings are structural, not stylistic. Three shapes account for most of the High and Medium items:

1. **Text that outlived its consumer.** The 9-phase `/q-morning` agent pipeline was retired 2026-08-30 (decisions.md RULE-2026-08-30-A). A whole rule file (`morning-pipeline.md`), four cross-references in other rules, the PostCompact injector, the MCP server's tool descriptions, the five `.claude/agents/`, and 60% of the `audhd-executive-function` skill body still instruct the model to run or serve it. Fable 5.1 follows skill text literally, so it reconciles "retired" against "run it" on every trigger.
2. **Rules that disagree with each other.** Four pre-action rituals fire on the same trigger with different thresholds and waits (R-6). `founder.md` tells drafts to open with "I", the measured global rule says the opposite (R-7). `fable-escalation.md` says the cap pages the founder; `slack-notify.sh` files a Sana ticket (R-2). The design gate is "a gate" in one rule and "advisory" in another (R-17).
3. **Skills whose scripts do not exist.** `deck-ai` runs a Slidev pipeline whose three scripts were never committed; the `design` router sends work to seven skills installed nowhere; `ui-ux-pro-max`'s workflow hardcodes a React Native project and a root-relative path this repo does not have (S-1, S-2, S-3).

Two Fable 5.1 specific items: the migration guide documents that this model asks permission it does not need on long runs and over-plans when told to plan before acting. `audhd.md:23` explicitly instructs converting "I'll go ahead and..." into "Want me to...?" (R-9), and `token-discipline.md:37` plus `CLAUDE.md:16` mandate a wait-for-OK on every multi-file task (R-6). Both reproduce the documented failure. And two headless jobs (`linear-triage.py`, `granola-voice-synthesize.py`) are unpinned and ride the interactive model against the fleet's own pin rule (C-1, C-2).

---

# Part A: findings

Prefix by lane: R = rules/CLAUDE.md/output-styles, S = skills, X = commands/agents/injectors, C = code and tool descriptions. Ordered High, then Medium, then Low within each lane. Cross-lane duplicates are merged and noted.

## High

### R-1 morning-pipeline.md instructs a retired pipeline; four rules point at it as live
- Location: `.claude/rules/morning-pipeline.md:8-59`; `.claude/rules/sycophancy.md:24-25`; `.claude/rules/wiring-check.md:13-14`; `.claude/rules/loop-exits.md:127`; `.claude/rules/folder-structure.md:234`; `q-system/CLAUDE.md:25`
- Evidence: "**Before every `/q-morning` run, read `.q-system/preflight.md` FIRST.**" / "Read `.q-system/agent-pipeline/agents/step-orchestrator.md` for the full phase plan."
- Pattern: 1d Fossils, text that outlived its consumer; cross-file disagreement
- Why obsolete: `CLAUDE.md:21` and decisions.md RULE-2026-08-30-A say the agent pipeline is RETIRED and `morning-brief.py` replaced it. The paths-scoped rule still prescribes preflight, a Phase 6 sycophancy audit, verify-bus diagnosis and a 3-attempt phase retry loop.
- Provenance: 7fce31fb 2026-04-02; retired 2026-08-30
- Confidence: High
- Action: remove (or reduce to three lines) + rewrite the four cross-references
- Proposed edit: delete `morning-pipeline.md` or replace its body with: "`/q-morning` is `q-system/.q-system/scripts/morning-brief.py` (launchd `com.kipi.morning-brief`, 07:00; deadman `com.kipi.morning-brief-deadman`). A section that could not be read says COULD NOT READ. The agent pipeline under `.q-system/agent-pipeline/` is retired (decisions.md RULE-2026-08-30-A) and is not run by hand." sycophancy.md: delete lines 24-25. wiring-check.md:13-14 -> "- Any new agent has a current model ID (model-allocation.md) and explicit tool allowlist, and something invokes it (a command, a hook, or a launchd job)". loop-exits.md:127: replace `morning-pipeline.md (the reference multi-phase loop binding these)` with `open-loops-heartbeat.sh (the reference autonomous loop)`. folder-structure.md:234: delete the "New agent?" line. q-system/CLAUDE.md:25: see R-13.

### R-2 fable-escalation.md says the cap pages the founder; the script files a Sana ticket
- Location: `.claude/rules/fable-escalation.md:120-136,152`; `.claude/rules/loop-exits.md:64,126`
- Evidence: "2 escalations per actor per session, then `slack-notify.sh` is asked to page once" / "`founder-notifications.md` (the one ping channel)"
- Pattern: 1d Fossils, near-duplicate rules that disagree
- Why obsolete: `founder-notifications.md:5-7` (founder-directed 2026-08-10) and the script header: `slack-notify.sh` files a Linear ticket for Sana and pages nobody. This is the exact stale-description shape the 2026-08-18 scar records.
- Provenance: 715895ea 2026-08-03; contradicting directive 2026-08-10
- Confidence: High
- Action: rewrite
- Proposed edit: fable-escalation.md:120 -> "| 2 escalations per actor per session, then `slack-notify.sh` files one Linear ticket in Sana's triage | `FABLE_CAP`, `notify_cap()` |". Lines 126-128 -> "Cross-model is a step before a human, never instead of one. At the cap the script stops calling and files one ticket for Sana (`founder-notifications.md`). The test `test_escalations_stop_at_the_cap_and_page_once` pins both halves." Line 130 -> "**A ticket is attempted, not guaranteed, and the row says which.**" Line 152 -> "`founder-notifications.md` (the fleet alert sink: a Linear ticket for Sana, never a founder page)". loop-exits.md:126 -> "`founder-notifications.md` (where exit 8 alerts land: Sana's Linear triage)".

### R-3 / C-15 Fable escalation's "different model" premise inverted
- Location: `.claude/rules/fable-escalation.md:11,21-23`; `q-system/.q-system/scripts/fable-escalate.py:2-5,62`
- Evidence: "# Fable Escalation: when Opus is stuck, a different model triages" / `FABLE_MODEL = "claude-fable-5"`
- Pattern: 1d Fossils, model-version workaround whose premise moved
- Why obsolete: The rule's rationale is cross-model complementarity. The interactive session now runs Fable 5.1, so the escalation hands a Fable 5.1 session to Fable 5, same family one release back. The property the script actually engineers (lines 305-308) is "a fresh context with no repo rules loaded".
- Provenance: 715895ea 2026-08-03
- Confidence: High (rule text); Medium (script pin, superseded not retired)
- Action: rewrite
- Proposed edit: fable-escalation.md:11 -> "# Cross-model escalation: when the session model is stuck, a different model triages (ASK-311)". Lines 21-23 -> "The session model keeps the work. The triage runs in a fresh `claude -p` session on a model from a different family than the one running the session (`fable-escalate.py` picks it from `CLAUDE_MODEL`/`ANTHROPIC_MODEL`: an Opus session escalates to Fable, a Fable session escalates to `claude-opus-5`); it never implements." Paired script edit: replace the `FABLE_MODEL` constant with that selection and rewrite the docstring premise.

### R-7 founder.md tells drafts to open with "I"; the measured rule says the opposite
- Location: `.claude/output-styles/founder.md:28`
- Evidence: "- DMs/emails start with "I" not the person's name"
- Pattern: 1d Fossils, near-duplicate rules that disagree; volatile claim superseded by a measurement
- Why obsolete: Global rule (measured 2026-08-19 over 30 sent emails): cold outreach leads with their pain, no greeting; client emails open "Hey"/"Hi" 43%, "I" 10%; a line that is only "I" measured 0%. The output style is always active, so every draft reconciles two opposite openers.
- Provenance: 7fce31fb 2026-04-02
- Confidence: High
- Action: rewrite
- Proposed edit: "- Cold DMs and cold outreach: lead with their pain; no greeting, no 'Name,' opener. Client emails (someone the founder knows): open the way the founder does, usually 'Hey'/'Hi'; never a line that is only a name or only 'I'."

### S-1 deck-ai SKILL runs a pipeline whose scripts do not exist
- Location: `plugins/kipi-core/skills/deck-ai/SKILL.md:26,48,57,65-74,153-165`; `references/layout-catalog.md` "Layout pick rules (v1)"
- Evidence: "bash <skill>/scripts/setup.sh ./deck-workspace" / "bash <skill>/scripts/render.sh ..." / "Do NOT invoke if the user wants a PPTX specifically (use `python-pptx` instead)."
- Pattern: 2 Brittle skill files, volatile specifics
- Why obsolete: `scripts/` holds only `check_env.sh`, `fetch_images.py`, `render_pptx.py`; `setup.sh`, `generate.py`, `render.sh` never existed in git. The shipped pipeline is python-pptx to PPTX, and `check_env.sh` checks for python-pptx, not Node/Slidev. Every run following the SKILL fails at step 1; the SKILL refuses the one output the scripts produce.
- Provenance: 933b2425 2026-04-19 (SKILL and real scripts in the same commit)
- Confidence: High
- Action: rewrite
- Proposed edit: replace lines 20-75 and 151-166 with the real contract: "## When to invoke ... Output is an editable PPTX (python-pptx). ## Setup: `python3 -m pip install python-pptx`; `UNSPLASH_ACCESS_KEY` in `./.env`. ## Workflow: 1. `bash <skill>/scripts/check_env.sh` 2. Read `<input.md>`, write `./decisions.json` (schema below) 3. `python3 <skill>/scripts/render_pptx.py <input.md> ./decisions.json ./deck.pptx`." Delete the Node/pnpm prerequisites, Slidev theme section, PDF limitations, pnpm/Chromium troubleshooting rows. In `layout-catalog.md` delete the v1 rules section and its `generate.py` sentence.

### S-2 design router sends work to seven skills installed nowhere
- Location: `plugins/kipi-design/skills/design/SKILL.md:30-32,134,141-142,219,225-232,301-302`; `references/design-routing.md:7-15`
- Evidence: "| shadcn/ui, Tailwind, code | `ui-styling` | External skill |" / "`/ckm:brand` -> `/ckm:design-system` -> randomly invoke `/ck:ui-ux-pro-max` OR `/ck:frontend-design`" / "Invoke `assets-organizing` skill"
- Pattern: 2 Brittle skill files, volatile specifics
- Why obsolete: `ui-styling`, `ai-artist`, `ai-multimodal`, `project-management`, `assets-organizing` exist in no marketplace, plugin or user skill dir (verified). `/ckm:` and `/ck:` are claudekit namespaces. `ui-ux-pro-max/SKILL.md:77` says ui-styling was merged into it. `plans/reports/` is a claudekit output path.
- Provenance: 7fce31fb 2026-04-02 (bulk claudekit import)
- Confidence: High
- Action: rewrite
- Proposed edit: lines 30-32 -> "| Brand identity, voice, assets | `brand` | `../brand/SKILL.md` |" and "| Tokens, shadcn/ui, Tailwind | `ui-ux-pro-max` | `../ui-ux-pro-max/SKILL.md` |" (drop `design-system`, `ui-styling`). Line 134 -> "Uses `frontend-design` (marketplace) and `chrome-devtools` for export." Line 142 -> "3. **Design**: create the HTML/CSS banner with `frontend-design`; generate visuals with `scripts/logo/generate.py` if imagery is needed". Line 219 -> "Uses `ui-ux-pro-max`, `brand`, `chrome-devtools`." Lines 225-232 -> "1. Analyze the prompt: subject, platforms, style, brand context. 2. Ideate 2-4 concepts; present them with the pick marked. 3. Design with `brand` then `ui-ux-pro-max`; one HTML file per concept x size. 4. Export via `chrome-devtools` screenshot at exact px (2x deviceScaleFactor). 5. Verify the PNGs visually; fix and re-export. 6. Report design decisions to `q-system/output/`." Delete line 301 and `ai-multimodal` on 302. Fold `references/design-routing.md`'s table into the SKILL's routing table.

### S-3 ui-ux-pro-max workflow hardcodes React Native and a root-relative path
- Location: `plugins/kipi-design/skills/ui-ux-pro-max/references/workflow.md:60,71,80,104,124,140,148`; `references/checklist.md:9,12`; `references/examples.md:14-26`
- Evidence: "- **Stack**: React Native (this project's only tech stack)" / "python3 skills/ui-ux-pro-max/scripts/search.py ..."
- Pattern: 2 Brittle skill files, SKILL vs reference disagreement; volatile hardcoded path
- Why obsolete: SKILL says 10 stacks; `data/stacks/` holds 16; the reference says one, React Native, from the project it was copied from. `skills/` does not exist at this repo root, so every command in the workflow fails as written. The sibling `design` skill already uses `${CLAUDE_SKILL_DIR}`.
- Provenance: 7fce31fb 2026-04-02
- Confidence: High
- Action: rewrite
- Proposed edit: line 60 -> "- **Stack**: the project's stack (see Available Stacks below); ask if it is not evident from the repo". Line 140 -> "### Step 4: Stack Guidelines". Replace every `python3 skills/ui-ux-pro-max/scripts/search.py` in workflow.md, checklist.md, examples.md with `python3 ${CLAUDE_SKILL_DIR}/scripts/search.py`. Available Stacks table: list the 16 CSVs in `data/stacks/`.

### X-1 preflight agent allowlists two MCP tools that were renamed
- Location: `.claude/agents/preflight.md:5`
- Evidence: `allowed-tools: "Read Grep mcp__claude_ai_Google_Calendar__gcal_list_events mcp__claude_ai_Gmail__gmail_search_messages mcp__claude_ai_Notion__notion-search"`
- Pattern: Group 3 contract mismatch; Group 2 volatile specifics
- Why obsolete: Both tools were renamed (decisions.md:266-267 records this as what killed the pipeline). Live names: `mcp__claude_ai_Google_Calendar__list_events`, `mcp__claude_ai_Gmail__search_threads`. An allowlist naming nonexistent tools is a path no prompt text can fix.
- Provenance: 7fce31fba 2026-04-02
- Confidence: High
- Action: rewrite (see also X-16, the roster question)
- Proposed edit: `allowed-tools: "Read Grep mcp__claude_ai_Google_Calendar__list_events mcp__claude_ai_Gmail__search_threads mcp__claude_ai_Notion__notion-search"`

### X-2 PostCompact injector re-steers toward retired pipeline phases on every compaction
- Location: `q-system/hooks/post-compact.sh:37-61`
- Evidence: `echo "Phase 6 complete. Next: Phase 7 (synthesis script)"` ... `echo "Phase 0 complete. Next: Phase 1 (data ingest)"`
- Pattern: 1d Fossils, retired workflow re-injected on a cadence
- Why obsolete: RULE-2026-08-30-A. This block infers a next phase from bus files and tells the model to continue a workflow that no longer exists, after every compaction.
- Provenance: 1a7640b39 2026-04-05
- Confidence: High
- Action: remove
- Proposed edit: delete lines 37-61.

### C-1 linear-triage.py is unpinned at every layer
- Location: `q-system/.q-system/scripts/linear-triage.py:378-380`
- Evidence: `res = subprocess.run([binary, "-p", prompt], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)`
- Pattern: 4 Request config, unpinned headless model call
- Why obsolete: Fleet rule pins every headless `claude -p` to `claude-opus-5` (unpinned jobs rode Fable and burned budget, 2026-08-01). No `--model`, no env, no wrapper in `kipi` or any plist. A 116-issue batch rides Fable 5.1 pricing.
- Provenance: c621530ea 2026-07-27
- Confidence: High
- Action: rewrite
- Proposed edit: `res = subprocess.run([binary, "-p", "--model", os.environ.get("KIPI_TRIAGE_MODEL", "claude-opus-5"), prompt], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)`

### C-2 granola-voice-synthesize.py defaults to the CLI's model
- Location: `q-system/.q-system/scripts/granola-voice-synthesize.py:34,42-43`
- Evidence: `MODEL = os.environ.get("VOICE_SYNTH_MODEL", "")  # empty = CLI default; set to pin` / `if MODEL: cmd += ["--model", MODEL]`
- Pattern: 4 Request config, unpinned headless model call
- Why obsolete: Same rule as C-1; this sends the largest prompt in the fleet (a full meeting corpus) to the interactive default.
- Provenance: c24b06e0f 2026-07-04
- Confidence: High
- Action: rewrite
- Proposed edit: `MODEL = os.environ.get("VOICE_SYNTH_MODEL", "claude-opus-5")  # fleet rule: headless jobs pin opus-5`; always pass `--model`, drop the `if MODEL:` guard.

### C-3 MCP tool family described in terms of the retired pipeline
- Location: `plugins/kipi-core/kipi-mcp/src/kipi_mcp/server.py:307-420,651-700,1481-1500,1585-1687` (about 20 tools: `log_*`, `kipi_verify_bus`, `kipi_verify_orchestrator`, `kipi_bus_to_log`, `kipi_queue_notion_write`, `kipi_preflight`, `kipi_session_bootstrap`, `kipi_canonical_digest`, `kipi_morning_init`, `kipi_gate_check`, `kipi_deliverables_check`)
- Evidence: "THE one call that replaces phases 0-0.7 of the old orchestrator." (1633) / "Call this before Phases 6, 7, or 8." (1652) / "Replaces the 00-preflight agent" (1585) / "Called by 09-notion-push" (1481)
- Pattern: 3 Tool descriptions, contract mismatch; 1d migration-relative phrasing
- Why obsolete: RULE-2026-08-30-A. Descriptions tell the model when to call tools in a workflow that no longer runs; always-loading a dead family is the Group 3 structural row.
- Provenance: pipeline retirement 2026-08-30
- Confidence: High
- Action: flag the family (retire or keep is a product call) + rewrite the migration-relative sentences on survivors
- Proposed edit: per survivor delete the "Replaces the NN-agent" / "Call before Phase N" / "Called by NN-notion-push" sentence and state the current trigger. Example `kipi_preflight`: "Check system readiness: required canonical files exist and the instance is configured. Returns per-file existence and an overall `ready` flag. Use it at session start or before any job that reads canonical files; it does not repair anything." If the family is retired, remove the registrations.

## Medium

### R-4 dev-skills-auto-invoke names skills the skeleton does not ship
- Location: `.claude/rules/dev-skills-auto-invoke.md:20-23,27`
- Evidence: "| Creating or editing a skill | `skill-creator` |" / "`mcp-builder`" / "`hook-development`"; "Always invoke the skill first"
- Pattern: Group 2 volatile specifics; Group 3 tool names in prose
- Why obsolete: Corrected after the lane's claim: the three skills DO exist on this machine, at `~/.claude/skills/` (user-level) and `skill-creator` as an official plugin. None of them appear in this session's loaded skill roster, and `kipi update` ships this rule to instances that have neither. A fleet rule cannot depend on a user-level install. `developing-claude-code-plugins` and `working-with-claude-code` exist under the `superpowers-developing-for-claude-code:` namespace.
- Provenance: b03d6eef 2026-04-03
- Confidence: Medium (was High; downgraded on independent check)
- Action: rewrite
- Proposed edit: table -> "| Creating or editing a skill, hook, plugin manifest, or agent | `superpowers-developing-for-claude-code:developing-claude-code-plugins` |", "| Working with Claude Code config or features | `superpowers-developing-for-claude-code:working-with-claude-code` |", "| Code that imports `anthropic`, `@anthropic-ai/sdk`, or `claude_agent_sdk` | `claude-api` |". Line 27 -> "Load the matching skill before writing, so the code follows its current reference rather than memory."

### R-5 token-discipline Layer 2 counters reproduce prior-model choreography
- Location: `.claude/rules/token-discipline.md:19-26`
- Evidence: "After 10 tool calls, pause and check ... If not, stop and tell the founder." / "If you've read 5+ files without writing anything, stop and tell the founder" / "Before spawning any Agent, ask: 'Is this worth 50K+ tokens?' If the answer is 'maybe,' use direct tools instead."
- Pattern: 1b "every N tool calls" cadence; 1d delegation suppression written for prior models
- Why obsolete: Migration guide: delete-and-re-baseline cadences; use sub-agents "instead of suppressing delegation (a common prior-model guardrail)". Hard caps already live in `token-guard.py`. The prose counters fire on legitimate read-only work (this audit tripped the 15-read warning; `fable-escalation.md:65-67` admits the stall detector fires on audits). "Never hold large API responses in context" is unexecutable (loop-exits.md:104-107 already says so).
- Provenance: 8f52e5e6 2026-04-04
- Confidence: Medium
- Action: rewrite
- Proposed edit: replace lines 19-26 with: "Self-monitoring (Layer 2, judgment the hook cannot see):\n- A failed tool call is diagnosed, not retried as-is. Change the approach.\n- Delegate independent subtasks to sub-agents when the work is parallel or would flood your own context; use Grep/Glob/Read directly for a single lookup. Intervene if a sub-agent drifts.\n- Read-only work (audits, reviews) legitimately runs long without a write; say what you are looking for if the founder asks, and otherwise keep going.\n- When blocked, change approach or ask; do not brute-force."

### R-6 four stacked pre-action rituals with different thresholds and waits
- Location: `.claude/rules/token-discipline.md:37-40`; `CLAUDE.md:16`; `.claude/rules/quick-plan.md`; `.claude/rules/fable-discipline-auto-invoke.md:5-13`
- Evidence: "echo the plan in 2-3 bullets and wait for OK. No exceptions for 'small' tasks."
- Pattern: 1b plan-before-acting; near-duplicate rules that disagree
- Why obsolete: Same trigger, four rituals: echo + wait (token-discipline), state approach + wait on >1 file (CLAUDE.md:16, different threshold), write a dated plan file (quick-plan), load the fable-discipline checklist. "No exceptions" disagrees with the same section's `/q-morning` carve-out and the founder's autonomy contract. The guide names "asks permission it doesn't need" as Fable 5.1's early-stopping failure; four rituals reinforce it. The collision with the global `~/.claude/CLAUDE.md` ("wait for OK" vs "Never ask permission to continue") is the same defect one level up, outside this repo's scope.
- Provenance: 3297fb00 2026-04-09; CLAUDE.md:16 526feff9 2026-08-19
- Confidence: Medium
- Action: rewrite
- Proposed edit: token-discipline.md:37-40 -> "## Pre-Action Echo\n\nIn an interactive session, a task that touches more than one file gets its approach stated before the first Edit/Write (the plan file from `quick-plan.md` is that statement; 2-3 bullets in chat is enough when no plan file is warranted). Under the autonomy contract or any unattended `claude -p` run, write the plan and proceed; there is no user turn to wait for." CLAUDE.md:16 -> "For a task touching more than one file, state the approach first (`quick-plan.md`); in interactive sessions wait for OK, in autonomous runs proceed. When fixing identified issues, fix exactly what was flagged."

### R-8 founder.md declares voice rules always active; voice-enforcement.md scopes them
- Location: `.claude/output-styles/founder.md:7` vs `.claude/rules/voice-enforcement.md:14-18`
- Evidence: "# Voice Rules (Always Active)" vs "Do NOT apply voice rules to: Conversational responses to the founder ..."
- Pattern: 1d near-duplicate rules that disagree
- Why obsolete: Fable 5.1 follows explicit style sections closely; the "Always Active" header pushes chat replies into published-post register.
- Provenance: 7fce31fb 2026-04-02
- Confidence: Medium
- Action: rewrite
- Proposed edit: founder.md:7 -> "# Voice Rules (for text another person will read; chat with the founder follows the AUDHD interaction rules)".

### R-9 audhd.md converts a decided action into a permission question
- Location: `.claude/output-styles/audhd.md:23,159`
- Evidence: `- "I'll go ahead and..." -> "Want me to...?"`
- Pattern: 1d near-duplicate rules that disagree; Fable 5.1 early-stopping
- Why obsolete: The autonomy contract names "Want me to...?" as the forbidden shape (confirmed 2026-05-08, 2026-05-10); the guide documents it as the failure to suppress. The PDA intent survives in the declarative-option form on lines 19-24.
- Provenance: e1df59fd 2026-08-19
- Confidence: Medium
- Action: rewrite
- Proposed edit: line 23 -> `- "I'll go ahead and..." -> in an interactive turn where the founder is choosing: state the option and the tradeoff, "My call: X"; under the autonomy contract: do it and report it. Never "Want me to...?" as a way to end a turn.` Line 159 example -> `"Shipped the command. Remote divergence untouched, separate decision: merge now or park it?"`

### R-10 coding-audhd forbids naming alternatives; four other rules require it
- Location: `.claude/rules/coding-audhd.md:71`
- Evidence: `- One approach. Not "you could use X or Y." Override if you want.`
- Pattern: 1d rules that disagree
- Why obsolete: `audhd.md:86,89`, `quick-plan.md` name-options, and the global "name the options, don't pick silently" all require alternatives surfaced.
- Provenance: 817e7c52 2026-04-09
- Confidence: Medium
- Action: rewrite
- Proposed edit: `- One recommendation, as a line: "My call: X." When real alternatives exist, name them with the tradeoff (audhd.md rule 5); do not pick silently.`

### R-11 md-hygiene tells the model to do by hand what md-prune.py does
- Location: `.claude/rules/md-hygiene.md:13,62-63`
- Evidence: "Before appending content to any of these files, check its current line count. If adding your content would push the file over budget, archive older sections first."
- Pattern: 1d manual instruction for a behavior since enforced in code
- Why obsolete: `md-prune.py` runs at SessionStart (settings.json:87, settings-template.json:98) and does exactly this. Rules 3-5 (dedupe, merge, MEMORY.md cap) are judgment and stay.
- Provenance: 7c4657fc 2026-04-04
- Confidence: Medium
- Action: rewrite
- Proposed edit: line 13 -> "Every canonical and my-project markdown file has a line budget (table below). `md-prune.py` (SessionStart) archives the oldest unpinned `##` sections when a file is over budget; when you write, prefer replacing or merging an existing entry over appending a new one." Lines 62-63 -> "1. **Prefer replacement:** near a budget, consolidate existing entries rather than appending.\n2. **Archiving is the script's job:** `md-prune.py` moves over-budget sections to `q-system/memory/archives/<file>-YYYY-MM-DD.md`; do it by hand only when the file has no `##` structure and the script warned."

### R-12 founder-notifications narrates its own revision history
- Location: `.claude/rules/founder-notifications.md:9-13`
- Evidence: "This file previously described slack-notify.sh as the founder-ping channel. That was true before 2026-08-10 and STALE afterward ... The rule doc now matches the script."
- Pattern: 1d migration-relative phrasing
- Provenance: 2026-08-10/18
- Confidence: Medium
- Action: rewrite
- Proposed edit: "Scar 2026-08-18: a feature shipped believing this script paged the founder, and its 'founder page' landed in Sana's queue. Any rule or script that says slack-notify.sh reaches the founder is wrong."

### R-13 / X-3 PostCompact re-injects rules that reload anyway
- Location: `q-system/CLAUDE.md:25`; `q-system/hooks/post-compact.sh:78-84`
- Evidence: "PostCompact hook re-injects mode, loops, and voice reminders." / `echo "ACTIVE RULES:"` / `echo "- All written output must use founder voice ..."`
- Pattern: 1d instruction re-insertion on a cadence
- Why obsolete: Every rule in the block is in an auto-loaded rule file that reloads after compaction; Fable 5.1 retains a once-stated instruction. Mode, loops and product snapshot are state and stay.
- Provenance: ad4bb346 2026-04-12; 035f4f73c 2026-04-03
- Confidence: Medium
- Action: rewrite + remove
- Proposed edit: q-system/CLAUDE.md:25 -> "PostCompact hook re-injects current mode and open-loop counts (state only; rules reload with the system prompt)." post-compact.sh: delete lines 78-84 (with X-2's 37-61).

### R-14 memory-confidence narrates its diff and defines the enum twice
- Location: `.claude/rules/memory-confidence.md:24,32-39,72-77,111,118,123,161-164`
- Evidence: "The old convention was "delete memories that turn out to be wrong"." / "### Deletion is now narrow" / "The `provenance` enum is NOT defined here in prose." (while 32-39 define it)
- Pattern: 1d migration-relative phrasing; Group 2 duplicates that disagree (file counts 32 vs ~70)
- Provenance: 197dcfc7 2026-08-19; 5bed187b 2026-07-28
- Confidence: Medium
- Action: rewrite
- Proposed edit: 72-77 -> "A corrected memory is SUPERSEDED, not deleted, because the reversal (that this was once believed, and what replaced it) is the most useful thing in the file." 111 -> "### Deletion is narrow". 118: delete "which is strictly worse than the deletion this replaces". 32-39 -> "### Provenance values\nThe accepted values and their ranks live in `q-system/.q-system/scripts/provenance-vocabulary.json` (run `python3 provenance_vocabulary.py` to print them). `inferred` and `observed` surface at recall regardless of the confidence number." Drop both file counts (24, 123).

### R-15 folder-structure tree and naming table are stale and self-contradicting
- Location: `.claude/rules/folder-structure.md:5-222,77,234,250-252,274`
- Evidence: "(16 files: ..." (38 exist) / two Python-script rows: "snake_case or kebab-case.py" and "kebab-case.py" / "Never modify `canonical/` files without council check" vs auto-detection.md:26-29
- Pattern: Group 2 volatile specifics; rules that disagree
- Provenance: 7fce31fb 2026-04-02
- Confidence: Medium
- Action: rewrite
- Proposed edit: replace the hand-drawn tree with "Run `tree -L 3 -I 'output|bus|node_modules'` for the current layout; `validate-separation.py` (`kipi check`) enforces placement." Keep Placement Rules, QROOT Resolution, Forbidden Patterns. One naming row: "| Python scripts | snake_case.py for importable modules, kebab-case.py for CLI scripts | `provenance_vocabulary.py`, `canonical-digest.py` |" and align coding-standards.md:16. Line 274 -> "- Canonical edits that change positioning, strategy, or messaging get a council check first (auto-detection.md); minor edits do not". Delete line 234.

### R-16 automated-filer-marking narrates its own revision
- Location: `.claude/rules/automated-filer-marking.md:21-26`
- Evidence: "A gate now exists here ... The original text said no hook could inspect ... That reasoning was right and the gate does not overturn it"
- Pattern: 1d migration-relative phrasing
- Provenance: 40a8fdae 2026-08-16
- Confidence: Medium
- Action: rewrite
- Proposed edit: "The gate is narrow on purpose: deciding statically whether a call site creates a Linear issue without a human is a judgment a regex loses, so it splits the question along `skill-hook-pairing.md`'s decision rule:"

### R-17 design pass is "a gate" in one rule and "advisory" in the other
- Location: `.claude/rules/dogfood-gate.md:25-28` vs `.claude/rules/design-auto-invoke.md:20-31`
- Evidence: "A website is not done until design-room passes" vs "running design-room there is advisory, strongly wanted and not machine-required"
- Pattern: 1d rules that disagree
- Provenance: c7a111d9 2026-07-06; 3d910775 2026-08-02
- Confidence: Medium
- Action: rewrite
- Proposed edit: dogfood-gate.md:25 -> "2. **Design + UX read (required by this rule, not by a hook).** Run the `design-room` skill on the page before deploy. Nothing machine-checks that it ran (`design-auto-invoke.md`); a public page is not done until it has, or the founder signs off on an exception." design-auto-invoke.md:20-31 -> "Read ENFORCED narrowly: `dogfood_gate.py` blocks only on a detected tell or a missing interactive element; `publish_gate.py` requires a design-room receipt only under a `design-room/` directory. The design-room pass on an ordinary public page is required by `dogfood-gate.md`, not by a hook."

### R-18 design-auto-invoke repeats its scoping sentence above the title
- Location: `.claude/rules/design-auto-invoke.md:1-3` (duplicate of 8-11)
- Pattern: 1c scattered duplication within one file
- Confidence: Medium
- Action: remove
- Proposed edit: delete lines 1-3.

### R-24 / X-15 content review runs four LLM passes where three are script work
- Location: `.claude/rules/morning-pipeline.md:57`; `.claude/agents/content-reviewer.md:12-16`
- Evidence: "`/q-market-review` runs 4 Sonnet passes via the content-reviewer agent." / "Run 4 sequential review passes, each checking one dimension."
- Pattern: Group 4, model calls whose inputs determine outputs; 1c choreography
- Why obsolete: Voice and anti-AI patterns have deterministic checkers (`voice-lint.py`, `voice-substance-lint.py`, `content-lint.py`, `compliance-check.py`); guardrails is a file-match. The one adaptive call is substance/actionability.
- Provenance: 7fce31fb 2026-04-02; a7d336b3c 2026-04-03
- Confidence: Medium
- Action: rewrite
- Proposed edit: rule line -> "**Content review:** `/q-market-review` runs the deterministic linters first (`voice-lint.py`, `voice-substance-lint.py`, `content-lint.py`, `compliance-check.py`) and one content-reviewer pass for substance and actionability on what survives." content-reviewer.md:14 -> "Review on four dimensions and return a verdict for each." (or collapse to the single judgment pass if the linters run first).

### S-4 audhd-executive-function skill is 60% spec for a retired HTML producer
- Location: `plugins/kipi-core/skills/audhd-executive-function/SKILL.md:8-14,28-48,53-72,118-123,160-178,182-192,268,278-291`
- Evidence: "This skill governs how ALL daily outputs are structured, especially the daily schedule HTML." / "The temperature dashboard in the FYI section must be WIRED to actions"
- Pattern: 1d text that outlived its consumer; Group 2 volatile specifics
- Why obsolete: Applied to every founder-facing output, yet A1-A7 copy-button mechanics, Section Order, Crack Detection, Temperature Dashboard Wiring, Visual Design and the 10-point HTML check are the daily-schedule spec retired by RULE-2026-08-30-A (last artifact 148 days old). Fable 5.1 follows skill text literally, pushing chat answers toward copy-boxes and dashboard rows with no surface. "Never Present Options" (118-123, 268) contradicts the name-options rule.
- Provenance: ae8f9f1d 2026-03-12
- Confidence: Medium
- Action: move
- Proposed edit: move the HTML-only sections to `references/daily-schedule-html-spec.md` with header "Applies only when producing a daily schedule HTML; dormant since RULE-2026-08-30-A." Line 8 -> "You are building an external executive-function layer for a user with AUDHD (ADHD + Autism). It governs every output the founder acts on: chat answers, task lists, drafts, Slack briefs." Lines 118-123 -> "Present one recommended action, ready to use. When a real choice exists, name the options and mark the pick; never hand back an open question as the deliverable." Delete line 268.

### S-5 linkedin-brand voice-check.md disagrees with the SKILL, the linter, and the global rule
- Location: `plugins/kipi-core/skills/linkedin-brand/references/voice-check.md:34-70,104-111`
- Evidence: "DMs, emails, and comments start with "I," never the recipient's name." / "BAD: Hey Sarah, loved your post about..." / memory-based PASS/FIX/REWRITE scoring
- Pattern: Group 2 duplicates that disagree
- Why obsolete: Global measured rule is the opposite for known contacts (R-7). SKILL.md:49 says patterns are enforced by `kipi_voice_lint`, no memory self-check; the reference's banned list has five words (`facilitate`, `harness`, `drive`, `unleash`, `I think`) absent from `draft_scanner.py`.
- Provenance: 340b46a44 / 261c05df9 2026-04-14
- Confidence: Medium
- Action: rewrite
- Proposed edit: delete lines 104-111. Replace the banned-phrase list with: "The banned-word and banned-phrase lists live in `plugins/kipi-core/kipi-mcp/src/kipi_mcp/draft_scanner.py` and are applied by `kipi_voice_lint`; this file does not duplicate them." Replace Scoring with: "Judgment-only checks the linter cannot see: does the opener anchor in a real experience; does it read as one specific person; is any triplet an abstract-quality list rather than concrete nouns." Keep the em-dash and rule-of-three examples.

### S-6 founder-voice names an enforcer that exists only in the consulting repo
- Location: `plugins/kipi-core/skills/founder-voice/SKILL.md:47-54`
- Evidence: "This REVERSES the old line ... Enforced by `ending_gate._closing_question_signals` in the content engine, not by this bullet."
- Pattern: 1d migration-relative phrasing; Group 2 volatile specifics
- Why obsolete: `closing_question` exists only at `~/projects/consulting/q-consult/pipeline/ending_gate.py`; a skeleton skill shipped fleet-wide points at code one instance has.
- Provenance: 3327c36be 2026-08-06
- Confidence: Medium
- Action: rewrite
- Proposed edit: "- Social posts (LinkedIn, X, Substack): end on a verdict, never a question. Founder-directed 2026-08-06; his corpus that day: 1 of 27 samples ends on a question, and that one is a quoted line, not a closer. The consulting content engine gates this in code (`ending_gate.py`); elsewhere it is a judgment check."

### S-7 design SKILL: three bolded imperatives, one of them a mandatory permission prompt
- Location: `plugins/kipi-design/skills/design/SKILL.md:60,67,69`
- Evidence: "**IMPORTANT:** When scripts fail, try to fix them directly." / "After generation, **ALWAYS** ask user about HTML preview via `AskUserQuestion`."
- Pattern: 1a pressure language without a because; 1c strategy coaching
- Why obsolete: "Fix scripts directly" contradicts the scope rules and the guide's "state boundaries" section; "ALWAYS ask via AskUserQuestion" is a mandated permission prompt the autonomy contract forbids.
- Provenance: 7fce31fb 2026-04-02
- Confidence: Medium
- Action: rewrite
- Proposed edit: line 60 -> "Generate logo images on a white background (the CIP mockup scripts composite the logo onto backgrounds and need a clean plate)." Delete 67. Line 69 -> "After generation, offer an HTML gallery preview (`ui-ux-pro-max`) as a follow-up; build it only if the founder asks."

### S-8 brand SKILL routes to two reference files that do not exist
- Location: `plugins/kipi-design/skills/brand/SKILL.md:4,27-49,82-85,93-97`
- Evidence: `argument-hint: "[update|review|create] [args]"` / "2. Load corresponding `references/{subcommand}.md`" (only `update.md` exists)
- Pattern: Group 2 volatile specifics
- Provenance: 7fce31fb 2026-04-02
- Confidence: Medium
- Action: rewrite
- Proposed edit: line 4 -> `argument-hint: "[update] [args]"`. Lines 93-97 -> "## Routing\n\n`update` loads `references/update.md`. Any other argument is a plain brand question: answer from the references table above." Prefix every `node scripts/` with `${CLAUDE_SKILL_DIR}/`.

### S-9 prd-os ships a frozen v1 copy of fable-discipline that disagrees with the live skill
- Location: `plugins/prd-os/skills/prd-os/references/fable-discipline-v1.md`
- Evidence: v1 "never the live one" vs live SKILL "never the live one, unless the resource is disposable by design"
- Pattern: Group 2 duplicates that disagree
- Why obsolete: Kept for a one-time `diff -q` acceptance check (issue closed 2026-07-03); nothing loads it; it lacks four carve-outs the live skill has. A model that opens it applies stricter rules than the ones in force.
- Provenance: 0eb685bd 2026-07-03
- Confidence: Medium
- Action: remove
- Proposed edit: delete the file; the merge rationale lives in the plugin CHANGELOG and the closed issue.

### S-10 prd-os SKILL describes what an earlier version wrongly claimed
- Location: `plugins/prd-os/skills/prd-os/SKILL.md:26,30`
- Evidence: "It does NOT register hooks -- that claim shipped through 0.17.0 with no code behind it (ASK-402)." / "There is no `/prd-revise` command."
- Pattern: 1d migration-relative phrasing
- Provenance: 86f4ff63a 2026-08-05
- Confidence: Medium
- Action: rewrite
- Proposed edit: line 26 -> "A PRD returns to `draft` after triage via `prd_runner.py advance draft`." Line 30 -> "Bootstrap: `/prd-os-init` (runs once per repo to scaffold `.prd-os/`, write `config.json`, and add the runtime state dir to `.gitignore`). Hooks come from this plugin's `hooks/hooks.json` when the plugin is enabled, not from init."

### S-11 ui-ux-pro-max description is an inventory, not a trigger
- Location: `plugins/kipi-design/skills/ui-ux-pro-max/SKILL.md:3`
- Evidence: `description: "UI/UX design intelligence with 50+ styles, 161 palettes, 57 font pairings, 99 UX guidelines, and 25 chart types. ..."`
- Pattern: Group 3 under-described routing text (the Must Use / Skip rules are in the body, read only after triggering)
- Provenance: 7fce31fb 2026-04-02
- Confidence: Medium
- Action: add
- Proposed edit: `description: "UI/UX design intelligence: a searchable database of styles, palettes, font pairings, UX guidelines and chart types with priority-based recommendations. Use when designing or reviewing a public-facing page, component, layout, colour or typography system, or when a UI 'looks unprofessional' and the reason is unclear. Skip for backend, API, infra, or internal founder-only dashboards."`

### S-12 research-mode says "WebSearch is deprecated" and routes login walls to Apify
- Location: `plugins/kipi-core/skills/research-mode/SKILL.md:57,76`
- Evidence: "- WebSearch is deprecated in this skill. Use Perplexity for breadth, Jina for depth." / "pages behind login walls (use Apify)"
- Pattern: 1d migration-relative phrasing; SKILL vs CLAUDE.md disagreement (CLAUDE.md routes signed-in surfaces to `browser_session.py` and Reddit to `reddit_read.py`)
- Provenance: 59a3d691e 2026-06-19; ac825ee63 2026-04-14
- Confidence: Medium
- Action: rewrite
- Proposed edit: 76 -> "- WebSearch is not part of this cascade: Perplexity covers breadth, Jina covers depth." 57 -> "- Bad for: pages behind a sign-in (use `q-system/.q-system/scripts/browser_session.py fetch <profile> <url>`; Reddit goes to `reddit_read.py thread|listing`), and JS-rendered SPAs (escalate to 3c)".

### S-13 two skills restate the banned-word list the linter owns
- Location: `plugins/kipi-core/skills/founder-voice/SKILL.md:66`; `plugins/kipi-core/skills/linkedin-brand/SKILL.md:53-55`
- Evidence: "Banned words and phrases enforced by `kipi_voice_lint` include: delve, comprehensive, crucial, pivotal, robust, ... and more."
- Pattern: 1b inline lookup table the tool already owns
- Why obsolete: Both say the list is enforced deterministically and must not be relied on from memory, then reproduce ~45 words inline in two files; S-5 shows the copy already drifted.
- Provenance: a5f3369cf / 261c05df9 2026-04-14
- Confidence: Medium
- Action: rewrite
- Proposed edit: founder-voice:66 -> "The banned word and phrase lists live in `plugins/kipi-core/kipi-mcp/src/kipi_mcp/draft_scanner.py` and are applied by `kipi_voice_lint`; do not restate them here. If a pattern keeps slipping past, extend the linter." linkedin-brand:53-55 -> "- Banned words and phrases: `draft_scanner.py` (`TIER1_WORDS / TIER1_VERBS / TIER1_ADVERBS`, `BANNED_PHRASES`), applied by `kipi_voice_lint`."

### S-14 fable-discipline L1.1 and L1.3 overlap Fable 5.1's native behavior
- Location: `plugins/prd-os/skills/fable-discipline/SKILL.md:45-49,56-60`
- Evidence: "1. **Stage before you act.** Write the stage plan first." / "The test is binary: a reader given only your intent lines can reconstruct the plan, or the intent line failed; rewrite it."
- Pattern: 1b plan-before-acting; 1c grader vocabulary
- Why obsolete: Most of the skill is repo contract and stays (L1.2 failable verification, which the guide says to keep on 5.1; L1.4 done-criteria; L1.5 ground-before-diagnose; all of Layer 2). L1.1's "before you act" choreography is the guide's stated over-planning risk (`quick-plan.md` owns the plan artifact); L1.3's binary self-test grades narration.
- Provenance: e619bbb4f 2026-06-15; caf80b050 2026-07-03
- Confidence: Medium
- Action: rewrite, then A/B per the guide's "De-prescribe migrated prompts and skills"
- Proposed edit: L1.1 -> "1. **Stage the work in the plan file.** `quick-plan.md` owns the plan artifact; in it, name the one checkable artifact each stage produces and merge any stage that produces nothing checkable. The map is living, not a contract; update it when what you learn invalidates it." L1.3 -> "3. **Say, then batch.** State the one-line intent, then fire the burst of actions that executes it; a reader given only your intent lines should be able to reconstruct the plan. It keeps you from drifting mid-burst."

### X-4 token-guard renders a countdown and a "you may be stuck" nudge into context
- Location: `q-system/.q-system/token-guard.py:443,537`
- Evidence: "You have {remaining} remaining before hard stop. Committing finished work resets the counter; otherwise focus on producing output." / "You may be stuck. Summarize what you've tried and what's blocking you."
- Pattern: Group 4 budget countdown rendered into context; 1d update-suppressor shape
- Why obsolete: The guide names remaining-budget countdowns as the trigger for premature wrap-up on Fable 5.1. Reproduced live: "15 remaining before hard stop" fired during this read-only audit where nothing can be committed. The hard cap is code and stays.
- Provenance: 5f4d5471a 2026-07-02; 6a5a37163 2026-04-04
- Confidence: Medium
- Action: rewrite
- Proposed edit: 443 -> `f"Tool-call volume guard: {calls} calls this turn. Commit or checkpoint finished work when there is some; the guard blocks at {limit}."` 537 -> `f"{minutes} minutes and {calls} tool calls since your last write."`

### X-5 issue-review inlines a gap-class catalog that drifts from the template
- Location: `plugins/kipi-dsse/commands/issue-review.md:68`; `plugins/prd-os/templates/gap-classes.md`
- Evidence: "Recurring gap classes: within the scope filter above, also check the diff for these shapes ..." (1 of 4 distinctive inline phrases appears in the template)
- Pattern: Group 2 duplicates that disagree
- Provenance: ef3cce97b 2026-06-19
- Confidence: Medium
- Action: move
- Proposed edit: line 68 -> "Recurring gap classes: read `${CLAUDE_PLUGIN_ROOT}/../prd-os/templates/gap-classes.md` (or the installed prd-os copy) and check the diff, within the scope filter, for the shapes it lists. Report only those the diff actually introduces." Merge the inline-only classes (health endpoint 500 on one bad row; hand-listed guard targets; separate stable lock file for compaction; symmetric env teardown in tests) into `gap-classes.md`.

### X-6 preflight and data-ingest carry numeric token ceilings plus prohibition runs
- Location: `.claude/agents/preflight.md:16`; `.claude/agents/data-ingest.md:19`
- Evidence: "**Budget:** Under 2K tokens. Do not analyze. Do not summarize. Just check and report." / "**Budget:** Under 2K tokens per source. Extract and move on."
- Pattern: 1f output-shaping choreography
- Provenance: 7fce31fba 2026-04-02
- Confidence: Medium (Haiku-pinned agents, smaller harm)
- Action: rewrite
- Proposed edit: preflight:16 -> "**Output discipline:** the deliverable is preflight.json. Report availability flags and the ready boolean; the consumer needs no narrative." data-ingest:19 -> "**Output discipline:** raw structured data only, one JSON file per source; the analysis agents downstream do the interpretation."

### X-7 all five agent descriptions are one sentence with no boundary
- Location: `.claude/agents/{content-reviewer,data-ingest,engagement-hitlist,preflight,synthesizer}.md:4`
- Evidence: `description: "Review content for voice, guardrails, anti-AI patterns, and actionability."`
- Pattern: Group 3 under-described
- Provenance: 7fce31fba 2026-04-02; a7d336b3c 2026-04-03
- Confidence: Medium
- Action: add (subject to X-16, whether the roster survives)
- Proposed edit: content-reviewer: "Reviews a finished draft against founder voice, positioning guardrails, anti-AI patterns, and actionability, returning a per-dimension PASS/FAIL with line-level notes. Use after a draft exists and before it is sent or published. Not a drafting agent: it never rewrites the text, and it does not check facts against canonical files beyond positioning rules." data-ingest: "Pulls raw calendar, Gmail, and Notion records into bus JSON files for the morning pipeline. Use only when a pipeline phase needs fresh source data written to the bus directory. Not for analysis, summarization, or answering questions about the data; it writes files and returns nothing else." engagement-hitlist: "Builds hitlist.json: ranked engagement actions with copy-paste draft text, from the pipeline's temperature, leads, LinkedIn, follow-up, loop, and Notion bus files. Use when all Phase 1-4 bus files for today exist. Not for ad-hoc single replies (use /q-engage) and it does not send anything." preflight: "Checks that the calendar, Gmail, and Notion MCP tools respond and that required files exist, then writes preflight.json with per-tool flags and a ready boolean. Use once, before the morning pipeline starts. Not a data pull: it makes one probe call per tool and reports availability only." synthesizer: "Assembles today's bus JSON into schedule-data-YYYY-MM-DD.json and runs build-schedule.py to produce the daily HTML. Use as the final pipeline step after hitlist.json exists. Not for partial days: if bus files are missing it should report which, not synthesize around them."

### X-8 prd-personas describes its own grader
- Location: `plugins/prd-os/commands/prd-personas.md:64-66`
- Evidence: "## Codex review note / This command file is itself reviewed by Codex when the issue executes. The review checks: scope adherence..."
- Pattern: 1c grader vocabulary
- Provenance: 00ecd8f12 2026-05-14
- Confidence: Medium
- Action: remove
- Proposed edit: delete lines 64-66.

### X-9 kipi-dsse commands narrate a "v2 rewrite topology"
- Location: `plugins/kipi-dsse/commands/issue-approve.md:5`; `plugins/kipi-dsse/commands/issue-start.md:14,22`
- Evidence: "In the v2 rewrite topology, plan approvals route to the **advisor** (main session), not to the founder."
- Pattern: 1d migration-relative phrasing
- Provenance: 2c03d437b 2026-04-26
- Confidence: Medium
- Action: rewrite
- Proposed edit: issue-approve:5 -> "Plan approvals route to the advisor (main session), not to the founder." issue-start:14 -> "Present a plan to the advisor (main session) via the channel:". issue-start:22 -> "wait for the advisor (main session) to approve the plan or redirect."

### X-10 voice-dna-loader shouts on every matching prompt and narrates retired copies
- Location: `q-system/.q-system/scripts/voice-dna-loader.py:117-124,183-185`
- Evidence: "You MUST apply the founder's voice DNA below before drafting any text another person will read. Do not paraphrase the rules." / "the founder-voice/references copies are retired and are no longer loaded."
- Pattern: 1a pressure language on a per-prompt cadence; 1d migration-relative phrasing
- Why obsolete: Fires on every prompt matching a broad regex (`text`, `send`, `edit`, `post`, `offer`, `hook`); the caps register bleeds into output; "retired / no longer loaded" narrates history. Identity, corrections and exemplar rows are context and stay.
- Provenance: 4670bdab5 2026-05-28; 9dde7db57 2026-08-13
- Confidence: Medium
- Action: rewrite
- Proposed edit: 117-124 -> `"[voice-dna-loader] Writing request detected. Apply the founder's voice DNA below before drafting text another person will read: witness lines, namer pattern, tester pattern, the 4-beat declarative with specifics. Shape without substance (no scar, named thing, test, or evidence) reads as AI cadence; voice-lint catches part of that, the rest is judgment."` 183-185 -> `"[voice-dna-loader] Writing request detected. The voice corpus is {voice_dir}; this hook reads only that corpus.\n\n"`.

### X-11 wiring-check points at an auto-memory file for model IDs
- Location: `plugins/kipi-core/commands/wiring-check.md:79`
- Evidence: "Frontmatter names a concrete model ID (per `memory/reference_agent_models.md` ...)"
- Pattern: Group 2 duplicates that disagree (model-allocation.md is the declared single source)
- Provenance: 443febb14 2026-04-20
- Confidence: Medium
- Action: rewrite
- Proposed edit: "- [ ] Frontmatter model ID matches the tier table in .claude/rules/model-allocation.md (validate-separation.py Gate 1.1b enforces it)"

### X-16 the five .claude/agents/ have no live caller
- Location: `.claude/agents/*.md`
- Evidence: "Read the full preflight instructions from `q-system/.q-system/agent-pipeline/agents/00-preflight.md` and execute them."
- Pattern: Group 4 roster surface; 1d unenforced
- Why obsolete: All five serve the retired pipeline; grep of `q-system/`, `plugins/`, `CLAUDE.md` finds no non-output caller. They are not redundant with each other, so no fold; the question is whether the roster should exist, which touches `validate-separation.py`'s input.
- Provenance: 7fce31fba 2026-04-02
- Confidence: Medium
- Action: flag (founder/Sana decision)

### C-4 MCP server `instructions` string shadows the tool list and is already stale
- Location: `plugins/kipi-core/kipi-mcp/src/kipi_mcp/server.py:38-52`
- Evidence: "kipi_build_schedule / kipi_create_template (content). kipi_voice_lint / kipi_copy_edit_lint / kipi_validate_* ..."
- Pattern: 3 tool names in system-prompt prose
- Why obsolete: Omits `kipi_browser_*`, `kipi_reddit_*`, `kipi_linkedin_*`, `kipi_harvest*`; enabling or disabling a tool leaves a dangling reference.
- Confidence: Medium
- Action: rewrite
- Proposed edit: `instructions=("Kipi founder OS server. Tool prefixes: kipi_* (instance, validation, linting, scoring, harvest, research reads), log_* (morning log), loop_* (follow-up loops). Resources: kipi://paths, kipi://status, kipi://instances, kipi://loops/open, kipi://loops/stats, kipi://backups. Read kipi://paths first for resolved directory paths.")`

### C-5 to C-12 JSON-forcing prose plus regex parsers, six scripts
The CLI exposes `--json-schema <schema>` with `--output-format json` (confirmed via `claude --help`), so "Output ONLY valid JSON, no fences" instructions and the bracket-slice / regex / retry parsers around them are the 1b scaffold row. One hunk each; keep every fail-closed `except` branch. Confirm the envelope field name with one probe before shipping.
- **C-5** `granola-voice-synthesize.py:39-52,74,93`: `cmd = ["claude", "-p", "--model", MODEL, "--output-format", "json", "--json-schema", json.dumps(SCHEMA)]`; delete the bracket slice (48-52) and the "no prose, no fences" sentences. Provenance c24b06e0f 2026-07-04. Medium.
- **C-6** `lessons-distill.py:101-110,124-128`: schema `{"type":"object","properties":{"title":{"type":"string"},"body":{"type":"string"},"kind":{"enum":["pattern","methodology"]}},"required":["title","body","kind"]}`; verify call schema `{"type":"object","properties":{"verdict":{"enum":["CLEAN","HELD"]}},"required":["verdict"]}` (replaces `startswith("CLEAN")`, which passes "CLEAN, although..."). Provenance a4bb77d03 2026-06-30. Medium.
- **C-7** `morning-brief.py:130-152,159-163,189-195`: `["claude", "-p", prompt, "--allowedTools", *tools, "--output-format", "json", "--json-schema", schema]` per section; the `{"error": ...}` shape becomes a `oneOf` so COULD-NOT-READ survives; `_parse_json_block` shrinks to envelope + key check. Provenance 3abbe15a9 2026-08-30. Medium.
- **C-9** `plugins/prd-os/scripts/judgment_compiler.py:2128-2161,2171`: `_judge_argv` returns `["claude", "-p", "--model", model, "--tools", "", "--output-format", "json", "--json-schema", JUDGE_SCHEMA]` with the three enum lists moved into the schema; the 3-attempt loop then covers transport only. Note `JUDGE_PROMPT_SHA256` is a receipt field, so this is a documented calibration discontinuity. Provenance eaf80475f 2026-08-05. Medium.
- **C-10** `judgment_compiler.py:2155-2161` grader vocabulary ("Refs are resolved by the resolve_evidence_refs function, which OPENS each one ... A fabricated citation therefore cannot pass; it only costs you the case.") -> "Cite only refs that appear in the packet. An empty list is the correct answer when you cannot cite one." Medium.
- **C-11** `linear-triage.py` PROMPT OUTPUT block (~303-309) and 383-397: add `--output-format json --json-schema` with `verdicts[]` of `{id, category enum [do-now, needs-scope, batch, not-planned, founder-decision], why, action}` to the C-1 argv; keep the hallucinated-id and empty-`why` filters (judgment, not parse repair); the silent `continue` on a bad line goes away. Provenance c621530ea 2026-07-27. Medium.
- **C-12** `linear-dor-drafter.py:246-259,730-745`: `DOR_SCHEMA` with `outcome, files, check, blast_radius, not_doing, energy (enum Quick Win|Deep Focus|People|Admin), time_est`; render the `- **Outcome:** ...` lines in Python; delete the "Write ONLY the body... no code fences" sentences and the three repair steps (fence strip, preamble cut, Energy-line check). Provenance 896dc4bd5 2026-07-26. Medium.

### C-13 open-loops-heartbeat caps its only artifact at 3-5 lines
- Location: `q-system/.q-system/scripts/open-loops-heartbeat.sh:56,63`
- Evidence: "Be terse; act only on what is actionable." / "5. Report what you did in 3-5 lines."
- Pattern: 1f numeric output ceiling + "be terse"
- Why obsolete: The report is the only thing the run leaves in the log; the cap starves the one thing the operator reads.
- Provenance: 55c954739 2026-06-20
- Confidence: Medium
- Action: rewrite
- Proposed edit: 56 -> "Autonomous open-loops heartbeat for THIS instance. Act only on what is actionable." 63 -> "5. Close with a recap that stands on its own: per loop, what you did, what changed (URL or file), and what is still open. Do not invent new work beyond the open loops."

### C-14 open-loops-heartbeat has no headless-autonomy clause
- Location: `q-system/.q-system/scripts/open-loops-heartbeat.sh:55-64`
- Evidence: (absent) vs `pr-review-agent.sh:503-518` "This run is HEADLESS: no human is reading your output... Do not state a plan and wait for approval"
- Pattern: keep-list #11 re-baselining add; documented failure (2026-08-04, PR #97: reviewer asked for an OK and produced nothing)
- Why obsolete: The agent loads each instance's CLAUDE.md, whose wait-for-OK rule (R-6) is interactive-only.
- Confidence: Medium
- Action: add
- Proposed edit: insert after line 56: "This run is headless. Nobody reads your output while it happens and nothing you write can be answered, so do not state a plan and wait for approval and do not ask which loop to start with. For reversible actions that follow from a loop's next_action, proceed. The hard limits in step 3 are the only stops."

### C-16 kipi_browser_fetch shouts and scolds a rival tool
- Location: `plugins/kipi-core/kipi-mcp/src/kipi_mcp/server.py:1691-1700`
- Evidence: "USE THIS ONLY FOR SURFACES THAT DEFEAT AN HTTP CLIENT." ... "DO NOT USE THIS FOR REDDIT."
- Pattern: 3 MUST/NEVER steering and scolding cross-reference in a description
- Confidence: Medium
- Action: rewrite
- Proposed edit: "Use this only for surfaces that refuse an HTTP client. The category is narrow and measured: NodeSeek is the proven member (403 to curl and to headless Chrome, loads only headful). Reddit is not in it; it returns 200 to any ordinary User-Agent, so kipi_reddit_thread and kipi_reddit_listing cover it without a Chrome launch."

### C-17 kipi_reddit_thread carries a conversational rule in its contract
- Location: `server.py:1746-1755`
- Evidence: "ALWAYS REPORT THE COVERAGE." ... "If the result is truncated, say so to the user rather than presenting it as the thread."
- Pattern: 3 behavior-smuggling
- Confidence: Medium
- Action: rewrite
- Proposed edit: "The first key of the result is coverage_summary, e.g. "536 of 1190 comments (45.0%), 74 unexpanded stubs, TRUNCATED". One request does not return a whole large thread: measured, 224 declared came back 97.3% complete and 1190 came back 45.0%, so the comment list is not the thread unless coverage says so. HTTP 429 or 403 is returned as a refusal, never as an empty thread."

### C-18 ten MCP tools say nothing about what comes back or how they fail
- Location: `server.py` `kipi_get_notion_queue` 1498, `kipi_init_db` 746, `log_init` 307, `log_deliver_cards` 358, `loop_touch` 493, `loop_prune` 507, `kipi_agent_metrics` 1548, `kipi_monthly_learnings` 897, `kipi_harvest_status` 1387, `kipi_harvest_summary` 1407
- Evidence: `"""Get all pending Notion writes awaiting retry."""`
- Pattern: 3 under-described (all 73 name their parameters; these ten omit return shape and failure mode). Several are in the C-3 family; resolve C-3 first.
- Confidence: Medium
- Action: add
- Proposed edit (one worked example, same shape for the rest, return fields to confirm against each backend): `kipi_get_notion_queue`: "Return every Notion write queued by kipi_queue_notion_write that has not yet been retried, oldest first, as a JSON array of {action, source_agent, queued_at}. Returns [] when the queue is empty; that is a real empty, not an error. Read-only: it does not retry or dequeue anything."

## Low / flag

- **R-19** `fable-discipline-auto-invoke.md:5-10,22,25`: the 2026-07-04 merge stated three times; "distilled from the Fable 5 model" is a pinned name. Rewrite to the behavior; drop the dates. Low.
- **R-20** `memory-freshness.md:41-46`: four numbered steps restating the one-line rule at 22. Rewrite: "Before acting on a `fast` memory, verify the time-bound fact against the current tool state or surface it to the founder. If verification fails, update the memory to the new state, then act on the new state." Low.
- **R-21** `concurrent-session-worktrees.md:15-19`, `fable-escalation.md:13-19`: frontmatter drafting history with two different stale budget line counts (576 vs 601). Rewrite to "Paths-scoped on purpose ..." Low.
- **R-22** `auto-detection.md:11` bare "MANDATORY." Rewrite with its reason ("this is where a conversation turns into pipeline"). Low.
- **R-23** `evidence-ledger.md:94-99` "Open decision (founder) ... until it is decided" parked in a rule since 2026-07-28; belongs in the spillover ledger. Flag.
- **R-25** ENFORCED labels naming no executable: `anti-misclassification.md:9`, `dev-skills-auto-invoke.md:14`, `audhd-interaction.md:5,13` (real pairing `audhd-lint` exists, unnamed), `folder-structure.md:1`, `coding-standards.md:19`, `morning-pipeline.md:55`. All pre-date `prompt-only-enforcement-guard.py`. Flag.
- **S-15** `linkedin-brand/SKILL.md:8,41-42,72`: platform-ranking percentages (29%, 32%, 2.6x) with no capture date; `headline-engineering/references/research-receipts.md:5` shows the fleet convention ("Captured 2026-05-20 ..."). Flag.
- **S-16** `council/workflows/quick.md:38`, `debate.md:56`: "30-50 words" / "50-150 words" caps in persona prompts. Flag (format-sensitive table argues for a qualitative shape).
- **S-17** `headline-engineering/SKILL.md:10,62,67-72,83`, `references/platform-hooks.md:465`: hard-codes `[[assaf-voice]]`, a user-level personal skill, in a skeleton file shipped fleet-wide. Rewrite to `founder-voice`. Low.
- **S-18** `research-mode/SKILL.md:28-29`: quotes-first extraction applied to every document; the source reference scopes it to >20k-token documents. Idiom-dating only. Flag.
- **X-12** `q-system/hooks/session-start.py:160` "Must act, park, or kill today." Urgency with no consequence; contradicts audhd-interaction. Rewrite: "These loops are 14+ days old: act, park, or kill each one." Low.
- **X-13** `memory-freshness-check.py:83` "MUST verify before acting" (sibling `memory-confidence-surface.py:99` says it at normal volume). Low.
- **X-14** `lessons-inject.py:207-210` re-injects the 2026-08-29 scar text on every engineering prompt; the scar is in the docstring. Rewrite header to the selection caveat only. Low.
- **X-17** `prd-personas.md:8-18` documents itself as dead code "until Phase 0 has been measured". Roster decision. Flag.
- **X-18** `plugins/kipi-core/hooks.json` rca-notify fires on every non-zero Bash exit including expected ones (fired three times during this read-only audit). Advisory. Flag.
- **C-8** `morning-brief.py:159-182` calendar call: listing today's events and reformatting them is fully determined by the tool result; the model is transport. The mail call is the judgment call that stays. Fix is a direct Calendar API client, outside this diff. Flag.
- **C-19** `skill-trigger-eval.py:41` unpinned, `audhd-output-eval.py:186` pins opus-5: both measure interactive-surface behavior that runs on Fable 5.1, and neither report names the model it ran. Flag.
- **C-20** `lessons-distill.py:108,127`, `linear-dor-drafter.py:737`: pin lives only in the wrapper; a hand run is unpinned. Flag.
- **C-21** `~/Library/LaunchAgents/com.kipi.pr86-review.plist:11-12` pins `ANTHROPIC_MODEL` for a job with zero `claude -p` calls. Outside repo. Flag.
- **C-22** `pr-review-agent.sh:497-620` caps density; every capitalised rule carries its reason and scar, and the headless section is the guide's recommended re-baseline. Idiom-dating only. Flag.

## Clean (read fully, no finding)

Rules: `no-orphan-findings`, `rca-mode`, `remote-coverage`, `repair-first-generation`, `security`, `self-healing-retry`, `skill-hook-pairing`, `social-reaction-gate`, `sycophancy-core`, `voice-enforcement`, `model-allocation`, `linear-first`, `marketing-system`, `content-output`, `quick-plan` (apart from R-6 overlap), `evidence-ledger` (apart from R-23), `coding-standards` (apart from R-25), `audhd-interaction` (apart from R-25), `anti-misclassification` (apart from R-25). Root `CLAUDE.md` apart from line 16.

Skills: `architecture-review`, `rca`, `learn-from-correction`, `council/SKILL.md`, `fable-discipline` references, `founder-voice` references, `audhd-executive-function` references, `headline-engineering/references/platform-hooks.md`, `linkedin-brand/references/playbook.md`.

Commands: `linear-drain`, `rca-check`, `rca-start`, `say`, `voice-refresh`, `q-research`, `issue-amend`, `issue-closeout`, `issue-verify`, `prd-approve`, `prd-archive`, `prd-map`, `prd-os-init`, `prd-review`, `prd-split`, `prd-start`, `prd-triage`, `wiring-check` apart from X-11. Injectors clean of dated text: `git-health-check.sh`, `md-prune.py`, `lessons-index.py`, `auto-update.sh`, `open-loops.py`, `fleet-board-refresh.py`, `memory-confidence-surface.py`, `memory-scores-surface.py`, `sycophancy-monthly-check.py`, `voice-stop-gate.py`, `code_claim_grounding_guard.py`, `blocked-claim-evidence-lint.py`, `kb-graph-guard.py`.

Code: `plugin.json`, `.mcp.json`, `probe_hook_envelope.py`, `lessons-daily.sh`, `linear-worker.sh` Sana prompt (fragile git/PR steps with scars, keep list #3), `fable-escalate.py` ASK block, `morning-brief.py` mail prompt, `kipi-dispatch*.sh`, `kipi:125-145`, thirteen launchd plists, and 63 of 73 MCP tool descriptions (all 73 name every parameter; none carry worked examples or fake dialogue).

---

# Part B: proposed diff, by file

One hunk per finding. Old text is quoted in the finding; new text is the "Proposed edit" there. Take hunks selectively. Apply path: anything under `.claude/` goes through `apply-claude-changes.sh` (the path guard refuses direct writes, and read-only commands that mention `.claude/` in a pipeline). Everything else is a normal edit plus the paired test where one exists.

| File | Hunks (finding IDs) | Confidence |
|---|---|---|
| `.claude/rules/morning-pipeline.md` | R-1 (delete or reduce), R-24 | High, Medium |
| `.claude/rules/sycophancy.md` | R-1 | High |
| `.claude/rules/wiring-check.md` | R-1 | High |
| `.claude/rules/loop-exits.md` | R-1, R-2 | High |
| `.claude/rules/folder-structure.md` | R-1, R-15 | High, Medium |
| `.claude/rules/fable-escalation.md` | R-2, R-3, R-21 | High, High, Low |
| `.claude/output-styles/founder.md` | R-7, R-8 | High, Medium |
| `.claude/output-styles/audhd.md` | R-9 | Medium |
| `.claude/rules/dev-skills-auto-invoke.md` | R-4 | Medium |
| `.claude/rules/token-discipline.md` | R-5, R-6 | Medium |
| `CLAUDE.md` | R-6 | Medium |
| `q-system/CLAUDE.md` | R-13 | Medium |
| `.claude/rules/coding-audhd.md` | R-10 | Medium |
| `.claude/rules/md-hygiene.md` | R-11 | Medium |
| `.claude/rules/founder-notifications.md` | R-12 | Medium |
| `.claude/rules/memory-confidence.md` | R-14 | Medium |
| `.claude/rules/automated-filer-marking.md` | R-16 | Medium |
| `.claude/rules/dogfood-gate.md`, `.claude/rules/design-auto-invoke.md` | R-17, R-18 | Medium |
| `.claude/agents/preflight.md` | X-1, X-6, X-7 | High, Medium, Medium |
| `.claude/agents/data-ingest.md` | X-6, X-7 | Medium |
| `.claude/agents/content-reviewer.md` | R-24/X-15, X-7 | Medium |
| `.claude/agents/engagement-hitlist.md`, `synthesizer.md` | X-7 | Medium |
| `q-system/hooks/post-compact.sh` | X-2 (37-61), R-13/X-3 (78-84) | High, Medium |
| `q-system/.q-system/token-guard.py` | X-4 | Medium |
| `q-system/.q-system/scripts/voice-dna-loader.py` | X-10 | Medium |
| `plugins/kipi-dsse/commands/issue-review.md`, `plugins/prd-os/templates/gap-classes.md` | X-5 | Medium |
| `plugins/kipi-dsse/commands/issue-approve.md`, `issue-start.md` | X-9 | Medium |
| `plugins/prd-os/commands/prd-personas.md` | X-8 | Medium |
| `plugins/kipi-core/commands/wiring-check.md` | X-11 | Medium |
| `plugins/kipi-core/skills/deck-ai/SKILL.md`, `references/layout-catalog.md` | S-1 | High |
| `plugins/kipi-design/skills/design/SKILL.md`, `references/design-routing.md` | S-2, S-7 | High, Medium |
| `plugins/kipi-design/skills/ui-ux-pro-max/references/{workflow,checklist,examples}.md` | S-3 | High |
| `plugins/kipi-design/skills/ui-ux-pro-max/SKILL.md` | S-11 | Medium |
| `plugins/kipi-design/skills/brand/SKILL.md` | S-8 | Medium |
| `plugins/kipi-core/skills/audhd-executive-function/SKILL.md` (+ new `references/daily-schedule-html-spec.md`) | S-4 | Medium |
| `plugins/kipi-core/skills/linkedin-brand/references/voice-check.md` | S-5 | Medium |
| `plugins/kipi-core/skills/linkedin-brand/SKILL.md` | S-13 | Medium |
| `plugins/kipi-core/skills/founder-voice/SKILL.md` | S-6, S-13 | Medium |
| `plugins/prd-os/skills/prd-os/references/fable-discipline-v1.md` | S-9 (delete) | Medium |
| `plugins/prd-os/skills/prd-os/SKILL.md` | S-10 | Medium |
| `plugins/kipi-core/skills/research-mode/SKILL.md` | S-12 | Medium |
| `plugins/prd-os/skills/fable-discipline/SKILL.md` | S-14 (then A/B) | Medium |
| `q-system/.q-system/scripts/linear-triage.py` | C-1, C-11 | High, Medium |
| `q-system/.q-system/scripts/granola-voice-synthesize.py` | C-2, C-5 | High, Medium |
| `plugins/kipi-core/kipi-mcp/src/kipi_mcp/server.py` | C-3 (flag + rewrite), C-4, C-16, C-17, C-18 | High, Medium |
| `q-system/.q-system/scripts/fable-escalate.py` | R-3/C-15 | Medium |
| `q-system/.q-system/scripts/lessons-distill.py` | C-6 | Medium |
| `q-system/.q-system/scripts/morning-brief.py` | C-7 | Medium |
| `plugins/prd-os/scripts/judgment_compiler.py` | C-9, C-10 | Medium |
| `q-system/.q-system/scripts/linear-dor-drafter.py` | C-12 | Medium |
| `q-system/.q-system/scripts/open-loops-heartbeat.sh` | C-13, C-14 | Medium |

Removal completeness (guide Step 6): before landing R-1 grep for `morning-pipeline.md`, `step-orchestrator`, `agent-pipeline/` across rules, tests and `settings-template.json`; before C-5 to C-12 rewrite the tests that assert the old prompt text or the regex parsers (`test_linear_triage*`, `test_judgment_compiler*`, `test_morning_brief*`, `test_lessons_distill*` where present); before X-1 re-run `validate-separation.py` Gate 1.1b.

# Verify (guide Step 7)

- Removal is a hypothesis. For R-5, R-6, R-9, S-14 (the Fable 5.1 behavioral items) run `skill-trigger-eval.py` and `audhd-output-eval.py` before and after on a scratch copy, one change at a time; note C-19 first, both harnesses currently measure the wrong model.
- For C-5 to C-12, one probe per script against a copy with `--json-schema` to confirm the envelope field name, then the existing tests.
- Out-of-band dependencies: `voice-stop-gate.py`, `code_claim_grounding_guard.py` and the pr-verdict fixtures match on prompt strings; grep them for any string a hunk deletes.
- Re-audit at the next model release; each new section in the migration guide is the trigger.

# Not audited

The founder's global `~/.claude/CLAUDE.md` (outside the repo). Its "state your planned approach ... and wait for OK" line and its "Never ask permission to continue" section are the R-6 collision one level up; the repo cannot fix that, only mirror it.
