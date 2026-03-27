# /q-market-review — Content review pipeline

Validate content against guardrails. Runs 4 focused review passes in sequence. Returns PASS/FAIL with specific fixes per pass.

## Arguments

`/q-market-review [file]` — path to content file to review. If not provided, ask.

## Preconditions

Read these files:
1. `q-system/my-project/founder-profile.md`
2. `q-system/marketing/content-guardrails.md` — the validation rules
3. `.claude/skills/founder-voice/SKILL.md` — voice rules
4. `.claude/skills/founder-voice/references/voice-dna.md` — voice DNA
5. `.claude/skills/audhd-executive-function/SKILL.md` — if AUDHD enabled

## Integration checks

No external integrations required.

## Process

Run 4 review passes IN SEQUENCE using Agent tool (Sonnet model for all):

### Pass 1: Voice
- Check content against founder-voice skill rules
- Verify sentence structure, scar pattern, contrast pattern
- Check for banned AI words and structural anti-patterns
- PASS/FAIL with specific line-level fixes

### Pass 2: Guardrails
- Check content against `marketing/content-guardrails.md`
- Verify claims against canonical files
- Check for overclaiming, misclassification language
- PASS/FAIL with specific fixes

### Pass 3: Anti-AI Detection
- Check for AI-generated language patterns from founder-voice skill
- Banned words list, uniform paragraph structure, formulaic patterns
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
