# Kipi Plugin Token Optimization Plan

## Problem

Every conversation loads ~8-10K tokens of skill routing descriptions + full CLAUDE.md behavioral rules before the user says anything. With 48 skills, 20+ MCP tools, and extensive behavioral docs, the baseline context cost is massive.

## Research findings

Key patterns from the ecosystem (sources at bottom):

1. **Claude Code ToolSearch** — Built-in deferred tool loading. Tools marked for deferral only show their names until explicitly searched. Reduced Claude Code's own system tools from 14-16K to ~1K tokens. Settled on two-tier: 8 core tools loaded, rest deferred.

2. **Speakeasy Dynamic Toolsets** — 3 meta-tools pattern (`search_tools`, `describe_tools`, `execute_tool`). 96.7% input token reduction. Token cost stays constant regardless of toolset size (40 vs 400 tools).

3. **Claude Code skills have NO deferred loading** — Unlike MCP tools, skill descriptions are always in the system prompt. The only way to reduce their footprint is to have fewer skills or make descriptions shorter.

4. **MCP Resource Templates** — On-demand content via URI patterns. Content not loaded until explicitly read.

5. **Industry consensus** — Keep 10-15 tools active max. Beyond 30-50, selection accuracy degrades. Use search/routing for the long tail.

---

## Three-layer optimization strategy

### Layer 1: Skill registry reduction (48 → ~16 skills)
**Impact: ~6K tokens saved per message, every message**

Move 32 marketing/growth skills out of `.claude/skills/` and into MCP-served guides. Keep only the q-* core commands and supporting skills as actual Claude Code skills.

### Layer 2: MCP deterministic tools (13 new tools)
**Impact: ~15-20K tokens saved per daily cycle**

Replace mechanical operations (scoring, validation, linting) currently done by LLM reasoning with deterministic MCP tools.

### Layer 3: Skill content chunking
**Impact: ~5-10K tokens saved per skill invocation**

Serve skill methodology + references in sections via MCP, not as monolithic files.

---

## Layer 1: Skill registry restructure

### Keep as `.claude/skills/` (16 entries in routing table)

These are the primary user interface — slash commands and supporting skills:

```
q-morning        q-setup         q-plan          q-create
q-draft          q-debrief       q-calibrate     q-engage
q-market-create  q-market-review q-wrap          q-handoff
q-migrate        q-reality-check founder-voice   audhd-executive-function
```

### Move to MCP guide system (32 entries served on demand)

These become markdown files under `guides/` in the repo, served by a new MCP tool:

```
copywriting          copy-editing           seo-audit             programmatic-seo
site-architecture    schema-markup          ai-seo                analytics-tracking
page-cro             form-cro               signup-flow-cro       onboarding-cro
popup-cro            paywall-upgrade-cro    pricing-strategy      launch-strategy
content-strategy     marketing-psychology   marketing-ideas       free-tool-strategy
social-content       competitor-alternatives cold-email            email-sequence
paid-ads             ad-creative            churn-prevention      referral-program
revops               sales-enablement       product-marketing-context  ab-test-setup
```

### New MCP tool for guide access

```python
@mcp.tool()
def kipi_guide(topic: str, section: str = "full") -> str:
    """Load a marketing/growth methodology guide.

    Topics: copywriting, seo-audit, cold-email, pricing-strategy,
    page-cro, revops, analytics-tracking, email-sequence, ...

    Sections: "full" (default), "methodology" (core process only),
    "references" (templates/examples only), or a specific reference
    file name like "platform-specs" or "scoring-models".
    """
```

This replaces 32 skill routing descriptions (~4-5K tokens) with 1 tool description (~200 tokens).

### File moves

```
# Before
.claude/skills/copywriting/SKILL.md
.claude/skills/copywriting/references/copy-frameworks.md
.claude/skills/copywriting/references/natural-transitions.md

# After
guides/copywriting/methodology.md          (was SKILL.md)
guides/copywriting/references/copy-frameworks.md
guides/copywriting/references/natural-transitions.md
```

The q-* skills that reference these guides update their instructions:
```
# Before (in q-market-create SKILL.md)
Apply the copywriting skill rules.

# After
Call kipi_guide("copywriting") for methodology, then generate content.
```

### Implementation

**Wave 1A** (3 parallel agents):
- Agent 1: Create `guides/` directory structure, move 32 skill dirs
- Agent 2: Implement `kipi_guide` tool in server.py + guide loader module
- Agent 3: Update q-* skills to reference `kipi_guide()` instead of inline skill references

---

## Layer 2: Deterministic MCP tools

### Tier 1 — High frequency (5 tools)

| Tool | Module | What it does |
|------|--------|-------------|
| `preflight()` | `preflight.py` | Setup guard + integration checks + paths. Replaces 10-15 line preamble in every q-* skill |
| `voice_lint(text)` | `linter.py` | 80+ banned words, hedging, filler, sentence stats, structural anti-patterns |
| `validate_schedule(items, dashboard)` | `linter.py` | AUDHD 10-point quality check, banned language, section order, friction sort, dashboard wiring |
| `score_lead(attributes, signals, model)` | `scorer.py` | Fit/engagement/negative scoring with decay, MQL threshold |
| `ab_test_calc(baseline, mde, traffic)` | `scorer.py` | Sample size, duration, feasibility |

### Tier 2 — Medium frequency (8 tools)

| Tool | Module | What it does |
|------|--------|-------------|
| `validate_ad_copy(platform, headlines, descs)` | `linter.py` | Platform char limits, headline mix enforcement |
| `seo_check(title, meta, headings, cwv)` | `linter.py` | CWV thresholds, title/meta validation, heading hierarchy |
| `churn_health_score(signals)` | `scorer.py` | Weighted health formula + intervention tier |
| `cancel_flow_offer(reason, mrr)` | `scorer.py` | Exit reason → save offer mapping |
| `validate_cold_email(subject, body)` | `linter.py` | Subject rules, word count, reading level, AI patterns |
| `generate_schema(page_type, data)` | `schema_gen.py` | JSON-LD template + required property enforcement |
| `copy_edit_lint(text)` | `linter.py` | 50+ word replacements, filler, passive voice |
| `crack_detect(contacts, loops)` | `scorer.py` | 7/14/48h threshold checks, missed followups |

### Implementation

**Wave 2A** (3 parallel agents):
- Agent 1: `linter.py` — voice_lint, validate_schedule, validate_ad_copy, seo_check, validate_cold_email, copy_edit_lint
- Agent 2: `scorer.py` — score_lead, ab_test_calc, churn_health_score, cancel_flow_offer, crack_detect, preflight
- Agent 3: `schema_gen.py` — generate_schema

**Wave 2B** (2 parallel agents):
- Agent 1: Tests for all new modules (test_linter.py, test_scorer.py, test_schema_gen.py)
- Agent 2: Register all tools in server.py, update skills to call tools instead of reasoning

---

## Layer 3: Guide content chunking

The `kipi_guide` tool supports a `section` parameter:

```python
kipi_guide("revops", section="methodology")    # ~350 lines (core process)
kipi_guide("revops", section="scoring-models")  # ~250 lines (one reference)
kipi_guide("revops", section="full")            # ~1,400 lines (everything)
```

This means Claude loads the methodology first (~350 lines), decides which references it needs, then fetches only those. For a skill like revops with 4 reference files totaling 1,000 lines, Claude might only need 1 of them for a given task.

**Savings:** Instead of loading 1,400 lines for every revops invocation, typical load is 350 + 250 = 600 lines. **~60% reduction per skill use.**

### Implementation

Built into the `kipi_guide` tool from Layer 1 — no separate wave needed. The `section` parameter routes to:
- `"full"` → concatenate methodology.md + all references
- `"methodology"` → just the core SKILL.md content
- Specific name → look up in references/ subdirectory

---

## Execution plan (parallelized)

### Phase 1: Guide system + skill moves (Layer 1)
**3 parallel agents, ~2 hours**

| Agent | Scope | Files touched |
|-------|-------|---------------|
| 1A | Move 32 skill dirs from `.claude/skills/` to `guides/`, rename SKILL.md → methodology.md | 32 dirs moved |
| 1B | Implement `guide_loader.py` + `kipi_guide` tool in server.py with section support | 2 new files, server.py |
| 1C | Update 14 q-* skills to reference `kipi_guide()`, update CLAUDE.md docs | 14 SKILL.md + 2 CLAUDE.md |

### Phase 2: Deterministic tools (Layer 2)
**3 parallel agents, ~3 hours**

| Agent | Scope | Files touched |
|-------|-------|---------------|
| 2A | `linter.py` — 6 validation/lint tools + tests | 2 new files |
| 2B | `scorer.py` + `preflight.py` — 6 scoring/calc tools + tests | 3 new files |
| 2C | `schema_gen.py` — schema generation + tests | 2 new files |

### Phase 3: Integration + registration (Layer 2 cont.)
**2 parallel agents, ~1 hour**

| Agent | Scope | Files touched |
|-------|-------|---------------|
| 3A | Register all 13 tools in server.py | server.py |
| 3B | Update guide methodology files to reference MCP tools for mechanical parts | ~14 methodology.md files |

### Phase 4: Verification
**1 agent, ~30 min**

- Run full test suite
- Grep for stale skill references
- Verify guide loader serves all 32 topics
- Count skill entries in routing table (should be ~16)
- Measure token reduction with a test conversation

---

## Expected savings

| Layer | Savings | When |
|-------|---------|------|
| Skill registry (48→16) | ~6K tokens/message | Every message, every conversation |
| Guide chunking (section loading) | ~5-10K per guide invocation | When marketing skills are used |
| Deterministic tools | ~15-20K per daily cycle | During morning routine + content creation |
| **Total** | **~25-35K tokens per daily cycle** | |

For a typical day (morning routine + 3-4 content/outreach tasks + wrap), this cuts token usage by roughly 30-40%.

---

## Sources

- [Claude Code ToolSearch](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool) — built-in deferred loading
- [anthropics/claude-code#31002](https://github.com/anthropics/claude-code/issues/31002) — ToolSearch rollout discussion
- [Speakeasy Dynamic Toolsets](https://www.speakeasy.com/blog/how-we-reduced-token-usage-by-100x-dynamic-toolsets-v2) — 96.7% reduction with 3-tool pattern
- [Cloudflare Code Mode](https://blog.cloudflare.com/code-mode-mcp/) — 99.9% reduction with search+execute
- [ToolHive MCP Optimizer](https://stacklok.com/blog/cut-token-waste-from-your-ai-workflow-with-the-toolhive-mcp-optimizer/) — 64-85% reduction
- [MCP Context Isolation](https://paddo.dev/blog/claude-code-mcp-context-isolation/) — per-task tool scoping
- [Lazy Plugin Loading](https://dev.to/aabyzov/claude-code-hook-limitations-no-skill-invocation-lazy-plugin-loading-and-how-i-solved-it-44f2) — UserPromptSubmit hook pattern
- [SEP-1576](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1576) — MCP token bloat spec proposal
- [Tetrate MCP Optimization](https://tetrate.io/learn/ai/mcp/token-optimization-strategies) — 10 optimization strategies
- [FastMCP Resources & Templates](https://gofastmcp.com/servers/resources) — on-demand content patterns
