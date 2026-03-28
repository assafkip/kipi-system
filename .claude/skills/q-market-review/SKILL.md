# /q-market-review — Content review pipeline

Validate content against guardrails. Runs 4 focused review passes in sequence. Returns PASS/FAIL with specific fixes per pass.

## Setup guard

**FIRST:** Read `{config_dir}/founder-profile.md`. If it contains `{{SETUP_NEEDED}}`, STOP and tell the user:

> This system hasn't been configured yet. Run `/q-setup` first to set up your profile, integrations, and canonical files.

Do not proceed with any other steps.

## Path resolution

Read the `kipi://paths` MCP resource to get resolved directories. Key directories:
- **Config** (`{config_dir}`): founder-profile, enabled-integrations, canonical/, voice/, marketing/
- **Data** (`{data_dir}`): my-project/, memory/
- **State** (`{state_dir}`): output/, bus/
- **Repo**: system code (agents, templates, steps) stays in the git repo

## Arguments

`/q-market-review [file]` — path to content file to review. If not provided, ask.

## Preconditions

Read these files:
1. `{config_dir}/founder-profile.md`
2. `{config_dir}/marketing/content-guardrails.md` — the validation rules
3. `.claude/skills/founder-voice/SKILL.md` — voice rules
4. `{config_dir}/voice/voice-dna.md` — voice DNA
5. `.claude/skills/audhd-executive-function/SKILL.md` — if AUDHD enabled

## Integration checks

No external integrations required.

## Process

Run 4 review passes IN SEQUENCE using Agent tool (Sonnet model for all):

### Pass 1: Voice
- Run `kipi_voice_lint(text)` for deterministic banned-word and structure detection
- Run `kipi_copy_edit_lint(text)` for plain-English violations
- Check content against founder-voice skill rules for higher-order patterns (scar pattern, contrast)
- PASS/FAIL with specific line-level fixes

### Pass 2: Guardrails
- Check content against `{config_dir}/marketing/content-guardrails.md`
- Load the relevant marketing guide with `kipi_guide(topic)` for channel-specific rules (e.g., `kipi_guide('copywriting')`, `kipi_guide('social-content')`)
- Verify claims against canonical files
- Check for overclaiming, misclassification language
- PASS/FAIL with specific fixes

### Pass 3: Anti-AI Detection
- Run `kipi_scan_draft` on the content for deterministic banned-word scanning
- Run `kipi_voice_lint(text)` if not already run — covers hedging density, emdash, filler openers
- Check for higher-order AI patterns (uniform structure, formulaic conclusions) via LLM reasoning
- PASS/FAIL with rewrites for flagged sections

### Pass 4: Actionability
- If AUDHD mode enabled: check against audhd-executive-function rules
- Even if not: verify content has clear CTA, no vague conclusions
- PASS/FAIL with specific fixes

## Output

For each pass, report:
- **PASS** or **FAIL**
- Specific issues found with line references
- Suggested fixes for each issue
- Overall verdict: PUBLISH / REVISE / REWRITE

## Output rules

- Be specific about what to fix — not "improve the tone" but "line 4: replace 'leverage' with 'use'"
- If all 4 passes pass, say PUBLISH
- If 1-2 minor issues, say REVISE with the fixes
- If structural problems, say REWRITE with guidance
