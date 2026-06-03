# AI Usage Pain Points + Article Series Spine — v4

Source material for article series: **build your own AI structure** (stack → memory → agents).
Audience mix: mainstream personal users, knowledge workers, founder-operators.

**Revision history:**
- v1 — vendor-heavy. Killed.
- v2 — Reddit-anchored, vendor demoted.
- v3 — added Pew, SHRM, SO Dev Survey, r/Nurses, r/Mommit, r/ParentingADHD.
- **v4 (current)** — anchored on the founder's actual running systems across kipi-system, KTLYST strategy, Pure Spectrum, 4 Points Consulting. The articles are no longer theory. They're a case study.

---

## 0. The case-study spine

The founder runs **4 different businesses on one shared skeleton** (`kipi-system`). Each instance carries the same primitives but a different topology. This is the spine the articles are built on:

| Instance | Business type | Topology | Memory shape | Killer pattern |
|----------|---------------|----------|--------------|----------------|
| **kipi-system** | The skeleton itself | Source of truth | canonical/ + ripple-graph + bus-file pipeline | 9-phase resumable agent pipeline |
| **KTLYST strategy** | Startup product cluster | Multi-instance (strategy/product/website/lawyer) | Cluster bridge at `~/.ktlyst/bridge/` | Pinned-marketplace plugin lock (one SHA bump = whole fleet upgrade) |
| **Pure Spectrum** | Single-client multi-project fractional consulting | Single-instance, multi-project | Renamed `q-system/` → `q-pure/`; `dashboard.md` aggregator | `/q-switch [project]` command |
| **4 Points Consulting** | OSINT investigative consulting | Single-instance, multi-investigation | Two parallel roots: `q-system/` (skeleton) + `q-investigate/` (domain overlay); per-case canonical | 21-byte `.active-case` pointer file orchestrates 24 commands |

**Cross-cutting truth across all 4:** the token-guard hook fired on all 4 of the research agents at exactly 50 tool calls. Different instances, different work, same hard stop. Hooks are contracts. Prompts are aspirations.

---

## 1. Source tiering (for citations in articles)

- **[GOV-DATA]** — Pew, SHRM, government reports
- **[PEER-REVIEW]** — academic peer-reviewed
- **[PRACTITIONER]** — Stack Overflow Developer Survey, HK Law, named-practitioner blogs
- **[JOURNALISM]** — named reporter at non-vendor outlet
- **[REAL-USER]** — first-person Reddit / HN
- **[FOUNDER-SYSTEM]** — direct citation of the founder's actual running code/architecture. This is the strongest tier for THIS series because it's first-person verifiable.
- **[VENDOR-FRAMING]** — vendor content; strawman only

**Anchoring rule:** every load-bearing claim cites FOUNDER-SYSTEM or GOV-DATA / PRACTITIONER / REAL-USER. Vendor stats only as punchlines with their interest named.

---

## 2. The dominant pain patterns (external evidence)

### P1. Context amnesia / re-explaining
- **[REAL-USER]** [Looking for a proactive, cross-device AI agent](https://www.reddit.com/r/ChatGPTPro/comments/1thof60/) — paying for Gemini Advanced + Copilot Pro, still building memory from scratch.
- **[REAL-USER]** [OpenAI has now acknowledged that Pro lacks memory](https://www.reddit.com/r/ChatGPTPro/comments/1qzbdwb/) — Pro tier drops Apps, Memory, Canvas.
- **[REAL-USER]** [Built Chrome ext for cross-tool memory](https://www.reddit.com/r/OpenAI/comments/1steijn/) — Memdex, built because no native solution.

### P2. Tool sprawl + subscription stack overload
- **[PRACTITIONER]** Stack Overflow Dev Survey 2025: **6-10 AI tools default** ([survey.stackoverflow.co/2025](https://survey.stackoverflow.co/2025))
- **[REAL-USER]** [Subscription costs > groceries](https://www.reddit.com/r/productivity/comments/1t739xr/)
- **[REAL-USER]** [I open my apps less and less](https://www.reddit.com/r/productivity/comments/1ta0stb/) — apps becoming invisible back-ends

### P3. Hallucination as trust killer
- **[PRACTITIONER]** SO Dev Survey 2025: **66% biggest frustration = "almost right but not quite"**. **More devs actively distrust AI accuracy than trust it.** ([survey.stackoverflow.co/2025](https://survey.stackoverflow.co/2025))
- **[PRACTITIONER]** HK Law: "never trust, always verify" ([Feb 2026](https://www.hklaw.com/en/insights/publications/2026/02/a-legal-practitioners-guide-to-ai-and-hallucinations))
- **[REAL-USER]** [Close call with AI hallucinations](https://www.reddit.com/r/ClaudeAI/comments/1thxxdb/) — decimal point error almost lost B2B client

### P4. Quality regression — covered, see brief v3 receipts.
### P5. Context rot — covered.
### P6. Memory rules don't stick — covered.
### P7. Data loss — covered.

---

## 3. The fear layer (mainstream framing)

| Pain | Source | Tier |
|------|--------|------|
| 52% US workers worried about AI in workplace | [Pew Feb 2025](https://www.pewresearch.org/social-trends/2025/02/25/u-s-workers-are-more-worried-than-hopeful-about-future-ai-use-in-the-workpl) | GOV-DATA |
| 53% Americans say AI HURTS privacy more than helps | [Pew via TechNewsWorld](https://www.technewsworld.com/story/pew-finds-more-americans-worried-about-ai-than-excited-by-it-178574.html) | GOV-DATA |
| Companies cutting jobs as AI investment shifts | [Reuters May 13 2026](https://www.reuters.com/business/world-at-work/companies-cutting-jobs-investments-shift-toward-ai-2026-05-13/) | JOURNALISM |
| Parents arrive at clinic acting on ChatGPT advice | [r/Nurses](https://www.reddit.com/r/Nurses/comments/1syhpsj/chat_gpt/) | REAL-USER |
| 10yo asks ChatGPT everything — homework, curiosities, drawings | [r/Mommit](https://www.reddit.com/r/Mommit/comments/1mtcqnn/) | REAL-USER |
| "ChatGPT is not a licensed OT" — sounds right, isn't | [r/ParentingADHD](https://www.reddit.com/r/ParentingADHD/comments/1khq29t/) | REAL-USER |
| "Who do you all talk to?" — loneliness routes into AI | [r/AskWomenOver30](https://www.reddit.com/r/AskWomenOver30/comments/1goo9vm/) | REAL-USER |
| Seniors need phone-call AI, not app setup | [r/TechForAgingParents](https://www.reddit.com/r/TechForAgingParents/comments/1rvm9ea/) | REAL-USER |

---

## 4. THE FOUNDER-SYSTEM EVIDENCE BASE (article spine)

### 4.1 The Stack — what's actually wired across 4 instances

**[FOUNDER-SYSTEM]** Across the 4 running instances, the stack converges on a tiny set of MCPs + a pinned plugin marketplace:

| Capability | kipi-system | KTLYST strategy | Pure Spectrum | 4 Points |
|------------|-------------|-----------------|---------------|----------|
| Web scraping | Apify | — | Apify (token hardcoded — security smell) | Apify + 55 actors |
| Search | Perplexity | Exa | — | Perplexity + Exa + Tavily + Jina + Brave + Parallel + Bright Data (7 APIs) |
| Reddit | reddit MCP | reddit MCP | reddit MCP | reddit MCP |
| Browser | Playwright | Playwright | — | — |
| Knowledge base | NotebookLM | — | NotebookLM | NotebookLM |
| CRM | — | Notion | — | — |
| Plugins | kipi-core + 6 others (full source) | Pinned to assafkip/kipi-system@85cf2fc (zero local code) | Same 6 plugins | Same 6 + custom MCP servers (osint-infra, threat-intel) |
| Models | Haiku 4.5 (data), Sonnet 4.6 (analysis), Opus 4.6 (synthesis) | Opus default, effort: thorough | Same | Same |

**The pattern:** the stack is small and consistent. Variety lives in the domain overlays, not in the MCP list.

**Killer pattern — the pinned marketplace.** KTLYST strategy carries **zero plugin code**. Just a SHA lock at `.claude/plugin-manifest.lock` pinning `assafkip/kipi-system@85cf2fc`. Runtime executes from `~/.claude/plugins/marketplaces/kipi/`. Upgrading every instance = one SHA bump. That's how you escape subscription-stack hell — your "subscriptions" are upstream code you control, pinned by hash.

### 4.2 The Memory layer — same primitives, four different topologies

**[FOUNDER-SYSTEM]** This is the deepest article-3 material. The skeleton primitives are:
- `canonical/` — single-writer source of truth files
- `ripple-graph.json` — file-level dependency graph
- `bus/YYYY-MM-DD/*.json` — content-named pipeline files, validated by 25 JSON Schemas
- `~/.ktlyst/bridge/*.json` — cross-instance message bus (cluster only)
- `memory/last-handoff.md` + `MEMORY.md` — session continuity

The four instances use these differently:

**kipi-system (the skeleton):**
- 11 canonical files (talk-tracks, objections, discovery, market-intelligence, pricing-framework, verticals, engagement-playbook, lead-lifecycle-rules, content-intelligence, decisions, changelog)
- ripple-graph forces consistency checks across 5 downstream files when `my-project/current-state.md` changes
- Bus protocol: content-named files (`hitlist.json`, `leads.json`, `preflight.json`, `calendar.json`, `linkedin-posts.json`) in `bus/{date}/`, each validated by a schema in `agent-pipeline/schemas/`. Example: `schemas/hitlist.schema.json:32` requires `rank, contact_name, platform, action_type, copy, rationale, energy, time_est` and conditionally requires `post_url` if `action_type == "comment"`.

**KTLYST strategy (multi-instance cluster):**
- 23 canonical files (more than skeleton because of GTM artifacts: future-state, ai-native-founder, credibility-flex, weak-ties-framework, mom-test-playbook)
- **Cluster bridge** at `~/.ktlyst/bridge/`: writes `canonical-digest.json` (4.8KB), `market_signal.json` (17KB, last 2026-05-04), `website-state.json`; reads `product_state.json` (fresh 2026-05-20 15:35), `legal-flags.json`, `threat_status_history.json`
- Cross-instance message bus: `v2-rewrite-channel.jsonl` (1.4MB) with `write-cursors/` tracking per-instance read offsets — i.e., a real append-only log with consumer offsets, not a shared mutable file

**Pure Spectrum (single-instance, multi-project):**
- **Renamed `q-system/canonical/` → `q-pure/canonical/`** to disambiguate skeleton-managed files from client-owned files. Leftover `q-system/canonical/changelog.md` is the smoking gun showing the rename happened mid-life.
- `dashboard.md` (instance-unique) aggregates 5 projects
- `engagement.md` (instance-unique) declares stakeholder constraints
- No bridge directory — there's no sibling instance to bridge to
- `graph.jsonl` knowledge graph (entity-relationship triples)

**4 Points Consulting (single-instance, multi-investigation):**
- **Two parallel memory roots**: `q-system/` (skeleton) + `q-investigate/` (domain overlay)
- `q-investigate/canonical/` — case-agnostic doctrine (collection methodology, confidence scales)
- **Per-case canonical** at `q-investigate/investigations/case-NNN/canonical/` — scope + collection plan, mutated only via `/q-scope`
- Per-case `memory/` with `investigation-state.md`, `sessions/`, `last-handoff.md`
- **`.active-case` pointer file (21 bytes)** — single text file naming the current case. Orchestrates 24 commands. The killer "21-byte fact that runs your whole consulting practice" pattern.

**The pattern:** same primitives (canonical, memory, ripple-graph, bus). Topology adapts to business shape. Multi-instance cluster gets a bridge. Single-instance multi-project gets a dashboard. Single-instance multi-investigation gets a pointer file + per-case folders.

### 4.3 The Agent layer — hooks are the contract, prompts are aspirations

**[FOUNDER-SYSTEM]** Top-level agents (same 5 across all instances):

| Agent | Model | Tool allowlist |
|-------|-------|----------------|
| preflight | haiku-4-5 | Read, Grep, gcal/gmail/notion read-only |
| data-ingest | haiku-4-5 | Read, Google_Calendar/Gmail/Notion wildcards |
| content-reviewer | sonnet-4-6 | Read, Grep (+ founder-voice skill) |
| engagement-hitlist | opus-4-6, effort: max | Read, Grep |
| synthesizer | opus-4-6, effort: max | Read, Grep, Write, Bash(python3:*) |

Plus 52+ pipeline agents in the morning routine prefixed `00-` through `10-` with `_cadence-config.md`, `_scoring-config.md`, `_auto-fail-checklist.md` underscore configs. Routed by `step-orchestrator.md`.

**Hooks — the enforcement layer:**

| Hook | Triggers | What it does |
|------|----------|--------------|
| `token-guard.py` | UserPromptSubmit + PreToolUse | Blocks at 50 tool calls without user input, 25 subagents, 15 reads without write, 3 retries on same failing call. Hard exit-2. **Fired on all 4 of my research agents.** |
| `destructive-op-deny.sh` (global) | PreToolUse | Blocks rm -rf, git push --force, git reset --hard, Notion delete, Linear delete, etc. Bypass only via `ALLOW_DESTRUCTIVE=1` set BEFORE Claude starts. |
| `wiring-check.py` | PostToolUse(Edit\|Write) | Verifies every new skill/command/hook/agent is connected end-to-end. |
| `sycophancy-harness.py` | After morning phase 6 | Python independently grades the LLM that just graded the morning routine. Per `.claude/rules/sycophancy.md:9` — "If the harness disagrees, the harness wins." |
| `auto-commit.py` | Stop | Commits at session end. |
| `post-compact.sh` | PostCompact | Re-injects mode, loops, voice. |
| `lefthook.yml` (Pure Spectrum, 4 Points) | git pre-commit | Local-to-instance enforcement on top of skeleton hooks. |

**The pattern:** prompt-level rules failed (the destructive-op incident proves this — agent "fixed" a credential mismatch by deleting a prod volume). Hook-level rules hold. Every contract that matters is a Python script that exits non-zero, not a markdown bullet asking nicely.

### 4.4 Skeleton vs Instance — what propagates, what stays local

**[FOUNDER-SYSTEM]** `kipi update` syncs:
- `q-system/CLAUDE.md`, `.claude/rules/*.md`, `.claude/agents/*.md`, `.claude/output-styles/*.md`, `plugins/*/`

Does NOT sync:
- Root `CLAUDE.md`
- `q-system/canonical/*` (instance-owned content)
- `q-system/my-project/*` (the business identity)
- `q-system/memory/*` (per-instance state)
- `.mcp.json` (instance secrets)
- `~/.ktlyst/bridge/*` (cluster-shared, not skeleton-shared)

CLI: `kipi update [--dry] | new | push | check | list`. Registry: `instance-registry.json`.

**The pattern:** code propagates, content doesn't. Identity stays local. Same skeleton, four legitimately different businesses. The articles teach how to draw this line.

---

## 5. Article series structure (v4 — anchored on actual systems)

### Article 1 — "Your AI Stack: 4 businesses, 1 skeleton, 6 MCPs"

**Audience:** mainstream + early operator
**Hook (first 50 words):** "I run 4 businesses on one shared AI skeleton. A startup. Two consulting practices. A research-mode OSINT operation. Same 5 agents. Same 6 plugins. Same 4 MCPs. Different topology, different memory, different commands. Here's the stack that survives the chaos."
**Lead pain:** subscription stacking (SO 6-10 tools default), 1.5M ChatGPT abandonment, the "tools don't connect, I'm the middleman" rant
**Core moves:**
1. The mainstream fear context (Pew 52% workers worried, 53% AI hurts privacy)
2. Show the actual MCP table across 4 instances — only 4-7 MCPs each
3. The pinned-marketplace pattern as the alternative to subscription-stacking
4. The "code propagates, content doesn't" line
**Vendor strawmen:** HCLTech 43% (named with vendor interest), McKinsey 20% time loss (named)
**Close move:** A copy-pasteable starter stack (apify + reddit + perplexity + 1 model choice + 1 plugin marketplace), readable + actionable in <30 minutes.

### Article 2 — "Your AI Memory: same primitives, four topologies"

**Audience:** knowledge workers + semi-technical founders
**Hook (first 50 words):** "My consulting practice runs on a 21-byte text file. It's named `.active-case`. It contains a slug like `case-014-trump-coin`. That's it. 24 commands resolve their context against it. No prompt engineering, no chain-of-thought. A pointer file. Here's why your AI memory should look like a filesystem, not a context window."
**Lead pain:** SO 66% "almost right" + P1 context amnesia + P6 memory rules don't stick + P5 context rot
**Core moves:**
1. The single dominant claim: the model isn't the memory. Your filesystem is.
2. The four-topology table (KTLYST cluster bridge / Pure Spectrum dashboard / 4 Points active-case / kipi-system bus pipeline)
3. The primitives: canonical/, ripple-graph.json, bus/{date}/, bridge/, memory/last-handoff.md
4. The bus-file architecture — content-named JSON, 25 schemas, resumable phases. Show one schema literally.
5. The single-writer rule — canonical files have one writer named by role, not by person.
**Vendor strawmen:** Meta's 60K KW "second brain" (named as Meta marketing), McKinsey 20% (named)
**Close move:** A starter memory layout the reader can `mkdir` in 5 minutes: `canonical/{decisions,discovery,insights}.md` + `memory/last-handoff.md` + `.active-context` pointer file. Done.

### Article 3 — "Your AI Agents: hooks are contracts, prompts are aspirations"

**Audience:** founder-operators + builders
**Hook (first 50 words):** "I just ran 4 research agents in parallel across 4 instances of my system. All 4 hit a hard stop at exactly 50 tool calls. Different work, different memory, different agents. Same `token-guard.py` exits non-zero. That's not a system prompt. That's a Python script. Here's why your agent layer needs hook-level enforcement or you don't actually have an agent layer."
**Lead pain:** SO 66% "almost right" + reliability + handoff failures + the destructive-op-deny incident story
**Core moves:**
1. The agent table — 5 standard agents + 52+ pipeline agents, model IDs in frontmatter (Haiku data, Sonnet analysis, Opus synthesis)
2. The hook table — token-guard / destructive-op-deny / wiring-check / sycophancy-harness / auto-commit
3. The bus-file architecture as resumable pipeline (failed phase = re-run that phase only)
4. The sycophancy-harness — Python independently grades the LLM that just graded the morning. "If the harness disagrees, the harness wins."
5. The 4 Points fail-stop rule — any tool failure halts the pipeline. Forensic integrity. Different domain, different rule, same hook-level enforcement.
6. The destructive-op-deny incident — agent "fixed" credential mismatch by deleting prod volume. Prompt rules failed. Hook rules hold.
**Vendor strawmen:** HCLTech 43% (named), Temporal 85%^10 (named: "Temporal will sell you durable execution; the math is right, the pitch is the math")
**Close move:** Three non-negotiables grounded in the founder's actual hooks — (1) token-guard or equivalent budget enforcement, (2) destructive-op-deny or equivalent pre-execution block, (3) wiring-check or equivalent post-edit validation. Reader can copy the actual scripts.

---

## 6. The cross-cutting truths (use in every article)

1. **Same skeleton, different topology.** Multi-instance gets a bridge. Multi-project gets a dashboard. Multi-investigation gets a pointer file. The primitives are the same. The shape adapts.
2. **Hooks are contracts. Prompts are aspirations.** All 4 research agents hit the 50-tool-call hook regardless of their instructions. Proof.
3. **Code propagates, content doesn't.** `kipi update` syncs the skeleton. Identity stays local. This is what makes 4 businesses on 1 skeleton work.
4. **Determinism guards the LLM.** Sycophancy-harness verifies the LLM auditor. Token-guard caps the budget. Destructive-op-deny blocks before execution. Wiring-check validates after edit. The Python is the contract; the LLM is the interpreter.
5. **Filesystem-as-memory beats context-window-as-memory.** Bus files, canonical files, bridge files, pointer files. All persistent. All version-controlled. All readable by humans.

---

## 7. Vendor strawman list (use only when interest is named inline)

- HCLTech 43% enterprise AI failure — sells AI transformation
- Temporal 85%^10 math — sells durable execution
- McKinsey 20% time-loss — sells the audit
- IntuitionLabs "demos work, production doesn't" — AI consulting
- Maxim AI hallucination data — sells eval platform
- StackAI 89% observability — sells agent platform
- Lyzr / AgileInfoways / Smartdev / ValueBound — vendor blogs
- Meta 60K KW second brain — Meta marketing
- usecarly / indyinhomecare / storypoint / mihup / hg-institute — service vendors

---

## 8. Still-open gaps (low priority — articles can ship without)

- Direct DOI for the Science sycophancy study (peer-reviewed, March 2026) — Perplexity paraphrased via aggregator.
- X/Twitter raw quotes if wanted as flavor.
- Pure Spectrum's hardcoded APIFY_TOKEN security smell — could become a sidebar in article 1 ("don't do what I did") but optional.

---

## 9. Single-line summary for the series

> The model is good enough. The structure around the model is what fails. One shared skeleton, four businesses, six MCPs — the spine you actually need.
