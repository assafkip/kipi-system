# MCP Tool Extraction Plan

## Goal
Move deterministic operations from skills into kipi-mcp server tools to save tokens and improve reliability. Code beats LLM for math, validation, and lookups.

## Principles
- Only extract what's **fully deterministic** — if it needs judgment, leave it in the skill
- Skills still exist — they just call MCP tools for the mechanical parts
- Each tool must be independently testable with pytest

---

## Tier 1: High frequency, build first

### 1. `voice_lint(text: str) -> dict`
**Source:** founder-voice SKILL.md (lines 59-85) + references
**Frequency:** Every content generation, multiple times daily

Checks:
- 80+ banned AI words (delve, comprehensive, crucial, robust, innovative, etc.)
- Hedging phrases ("I think," "I believe," "it seems like," "arguably," "perhaps")
- Filler phrases ("I'm excited to announce," "thrilled to share," "In today's rapidly evolving landscape")
- Structural anti-patterns: uniform sentence length (compute variance), uniform paragraph length, "Furthermore/Moreover/Additionally" as paragraph openers, colon overuse (count, threshold)
- Single-sentence paragraph presence check
- Average/max sentence length

Returns: `{banned_words: [{word, count}], hedging: [str], filler: [str], antipatterns: [{pattern, count}], avg_sentence_len: float, max_sentence_len: int, has_single_sentence_para: bool, pass: bool}`

### 2. `validate_schedule(items: list[dict], dashboard_rows: list[dict]) -> dict`
**Source:** audhd-executive-function SKILL.md (lines 56-64, 70-83, 155-174, 207-220)
**Frequency:** Every morning routine output

Checks:
- 10-point quality check (copy-paste test, link test, time test, context test, zero-decision test, no-shame test, crack test, inline test, order test, independence test)
- Banned language: 11 specific words/phrases with replacements
- Section ordering: Quick Wins → Messages → Posts → Emails → Deep Focus → FYI
- Required fields per item: platform, person+company, action, copy_text, link, estimated_minutes, energy_tag
- Subject line present for email items
- Friction sort verification (ascending by estimated_minutes)
- Dashboard wiring: every downtrend row must link to an action item
- Crack detection: awaiting reply >7 days, no interaction >14 days, meeting not followed up

Returns: `{quality_checks: [{name, pass, violations}], banned_language: [{word, replacement, location}], section_order_ok: bool, missing_fields: [{item_idx, missing}], friction_order_ok: bool, unlinked_downtrends: [str], cracks: [{type, contact, days}], pass: bool}`

### 3. `score_lead(attributes: dict, signals: list[dict], model: str) -> dict`
**Source:** revops SKILL.md + references/scoring-models.md
**Frequency:** Every /q-plan, /q-morning lead prioritization

Computes:
- Fit score from lookup tables: company_size (5-25pts), job_title (5-25pts), industry (0-20pts), revenue (5-20pts), department (5-20pts), seniority (5-25pts)
- Engagement score from signals with decay: demo_request (+30), pricing_page (+20, -5/wk), trial_signup (+25), contact_sales (+30), case_study (+15, -5/2wk), comparison_page (+15, -5/wk), roi_calc (+20, -5/2wk)
- Negative signals: competitor_domain (-50), student_edu (-30), personal_email (-10), unsubscribe (-20), hard_bounce (-50), spam (-100), no_visit_90d (-15)
- MQL threshold by model: plg=60, enterprise=75, midmarket=65
- Pipeline velocity: (deals × avg_size × win_rate) / avg_cycle_days

Returns: `{fit_score: int, engagement_score: int, negative_score: int, total: int, mql_threshold: int, is_mql: bool, decay_details: [{signal, original, decayed, days_since}]}`

### 4. `ab_test_calc(baseline: float, mde: float, daily_traffic: int, num_variants: int, pct_exposed: float) -> dict`
**Source:** ab-test-setup SKILL.md + references/sample-size-guide.md
**Frequency:** Per experiment design

Computes:
- Sample size per variant from lookup table (baseline × lift matrix)
- Multi-variant multiplier: 2=1x, 3=1.5x, 4=2x
- Duration: (sample_per_variant × variants) / (daily_traffic × pct_exposed)
- Minimum 7 days enforcement
- Feasibility: <14d=easy, 14-30=feasible, 30-60=acceptable, >60=reconsider

Returns: `{sample_per_variant: int, total_sample: int, estimated_days: int, min_days: 7, feasibility: str, recommendations: [str]}`

### 5. `validate_ad_copy(platform: str, format: str, headlines: list[str], descriptions: list[str], primary_text: str|None) -> dict`
**Source:** ad-creative SKILL.md + references/platform-specs.md
**Frequency:** Per ad batch creation

Checks:
- Character limits per platform/format (30+ distinct limits):
  - Google RSA: headline 30, description 90
  - Meta: primary 125/2200, headline 40/255, description 30/255
  - LinkedIn: intro 150/600, headline 70/200
  - TikTok: 80/100
  - Twitter: 280, card headline 70, card description 200
- Headline mix (Google RSA 15): 3-4 keyword, 3-4 benefit, 2-3 social proof, 2-3 CTA, 1-2 differentiator, 1 brand
- Character count annotation per element
- Over-limit flagging with trimmed alternatives

Returns: `{violations: [{element, text, char_count, limit}], mix_check: {keyword: int, benefit: int, ...}, all_within_limits: bool}`

---

## Tier 2: Medium frequency, build second

### 6. `seo_check(title, meta, headings, canonical, images, cwv) -> dict`
**Source:** seo-audit SKILL.md
- Title: 50-60 chars, unique, keyword near start
- Meta description: 150-160 chars, unique, has CTA
- Headings: one H1, contains keyword, no skip levels
- Canonical: present, self-referencing, consistent protocol/www/trailing slash
- Images: alt text present, descriptive filenames, modern formats
- CWV: LCP < 2.5s, INP < 200ms, CLS < 0.1

### 7. `churn_health_score(login_freq, feature_usage, support_sentiment, billing_health, engagement) -> dict`
**Source:** churn-prevention SKILL.md
- Weighted formula: 0.30 + 0.25 + 0.15 + 0.15 + 0.15
- Thresholds: 80-100=healthy, 60-79=attention, 40-59=at_risk, 0-39=critical

### 8. `cancel_flow_offer(reason, mrr, plan_tier) -> dict`
**Source:** churn-prevention references/cancel-flow-patterns.md
- Deterministic mapping: reason → primary offer + fallback offer
- Discount guardrails: 20-30% for 2-3 months, never 50%+

### 9. `validate_cold_email(subject, body, followup_number) -> dict`
**Source:** cold-email SKILL.md + references
- Subject: 2-4 words, lowercase, no punctuation tricks, no product pitch
- Body: 25-75 words optimal, 3rd-5th grade reading level
- Self-focus ratio: I/We vs You/Your sentence count
- AI pattern detection: "I hope this email finds you well," etc.
- Benchmark lookup by reply rate

### 10. `generate_schema(page_type, data) -> dict`
**Source:** schema-markup SKILL.md + references/schema-examples.md
- JSON-LD template generation by page type
- Required/recommended property enforcement
- Multi-type @graph array assembly

### 11. `copy_edit_lint(text) -> dict`
**Source:** copy-editing SKILL.md + references/plain-english-alternatives.md
- 50+ word replacements (utilize→use, implement→set up, leverage→use, etc.)
- Filler word detection (very, really, just, actually, basically, "in order to")
- Passive voice detection
- Sentence length check (max 25 words usually)
- Paragraph length check (2-4 sentences for web)

---

## Tier 3: Cross-cutting infrastructure

### 12. `preflight() -> dict`
**Source:** Pattern repeated across all 14 q-* skills
**Frequency:** Every single skill invocation

Combines three checks that every skill currently does manually:
- Setup guard: read founder-profile.md, check for `{{SETUP_NEEDED}}`
- Legacy detection: check if `q-system/my-project/founder-profile.md` exists with real data
- Integration availability: parse enabled-integrations.md, return which tools are configured
- Path resolution: return all resolved paths (already exists as kipi://paths, but bundling saves round-trips)

Returns: `{setup_needed: bool, legacy_detected: bool, integrations: {notion: bool, apify: bool, gmail: bool, gcal: bool, ...}, paths: {...}}`

Skills would replace their 10-15 line preamble with a single `preflight()` call.

### 13. `crack_detect(contacts: list[dict], loops: list[dict]) -> dict`
**Source:** audhd-executive-function (lines 155-174), q-plan, q-wrap
**Frequency:** Every morning routine, every /q-plan, every /q-wrap

Checks:
- Awaiting reply > 7 days (date math)
- No interaction > 14 days (date math)
- Meeting happened but not followed up (boolean: meeting_date exists, followup_sent is null)
- Scheduled but not confirmed (boolean)
- Cooling contacts: score dropping (trend calculation)
- Loop escalation: open loops past threshold

Returns: `{stale_contacts: [{name, days_since, type}], missed_followups: [{name, meeting_date}], cooling: [{name, score, trend}], escalated_loops: [{target, level, days_open}]}`

---

## Implementation approach

Each tool goes in `kipi-mcp/src/kipi_mcp/` as either:
- A method on an existing class (e.g., `MetricsStore` for scoring)
- A new module (e.g., `linter.py` for voice_lint + copy_edit_lint)
- Added to `server.py` as `@mcp.tool()` endpoints

### File structure
```
kipi-mcp/src/kipi_mcp/
  linter.py          — voice_lint, copy_edit_lint, validate_cold_email
  scorer.py          — score_lead, churn_health_score, ab_test_calc
  validator.py       — (extend existing) validate_schedule, validate_ad_copy, seo_check
  schema_generator.py — generate_schema
  server.py          — register all as @mcp.tool()
```

### Test structure
```
kipi-mcp/tests/
  test_linter.py
  test_scorer.py
  test_validator_tools.py  — (separate from existing test_validator.py which tests kipi_validate)
  test_schema_generator.py
```

### Skill updates
After tools are built, update each SKILL.md to say:
"Call `voice_lint(text)` before reviewing — it handles banned words, structural anti-patterns, and sentence stats mechanically. Focus your review on the semantic checks (scar pattern, contrast, personality)."

This means the skill still loads but Claude skips the mechanical reasoning and trusts the tool output.

---

## Priority order
1. `preflight()` — saves tokens on EVERY skill invocation
2. `voice_lint()` — runs on every content output
3. `validate_schedule()` — runs every morning
4. `score_lead()` — core to prioritization
5. `ab_test_calc()` — pure math, easy win
6-13. Remaining tools in Tier 2-3 order

## Estimated total savings
~15-20K tokens per full daily cycle (morning + engage + content + wrap)
