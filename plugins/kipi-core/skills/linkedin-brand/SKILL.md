---
name: linkedin-brand
description: "LinkedIn + personal brand system for founders. Apply when drafting LinkedIn posts, reactions, DMs, LinkedIn About sections, or planning LLM visibility."
---

# LinkedIn Brand Skill

This skill is the operating system for a founder's LinkedIn presence and broader LLM visibility. It enforces the 2026 algorithm reality (360Brew decoder-only LLM), provides summary frameworks, and governs the cross-platform entity graph that makes a founder legible to ChatGPT, Claude, Gemini, and Perplexity.

## When to Invoke

Auto-fire on any of these:
- Drafting a LinkedIn post, article, or carousel
- Writing a comment, reply, or quote-post reacting to someone else's LinkedIn content
- Drafting a LinkedIn DM
- Writing or editing the LinkedIn About section
- Auditing the founder's LinkedIn profile
- Planning LLM visibility, personal-site schema, or third-party mention pipeline
- Any question containing "LinkedIn," "personal brand," "visibility to LLMs," or "my About section"

Skip for: internal ops chat, code, system files.

## Before Drafting

Always read in this order:
1. `references/playbook.md` — format rules, cadence, first-hour rule
2. `references/voice-check.md` — AI-detection patterns to avoid
3. `references/summary-frameworks.md` — if drafting/editing an About section
4. `references/llm-visibility.md` — if question is about broader visibility

Then read instance-specific files (not bundled in the skill):
- `my-project/linkedin-playbook.md` — this founder's committed pillars
- `my-project/linkedin-summary-template.md` — this founder's current About draft
- `my-project/llm-visibility-plan.md` — this founder's entity graph and mention pipeline

If those instance files do not exist, ask the founder to create them before drafting. Do not invent pillars or positioning.

## Core Rules (ENFORCED on every draft)

### Format
- Zero hashtags, or one high-intent tag max. 3+ tags costs 29% reach.
- External links go in the first comment, never the body. Body links cost 32% reach.
- Short sentences. 8-15 words average. One idea per sentence.
- Scar-anchored. Lead with real experience, not abstract claims.
- Personal-adjacent outperforms pure professional.

### AI-detection patterns (scrub before publishing)

All patterns below are enforced deterministically by `kipi_voice_lint` and `kipi_copy_edit_lint` during the Pre-Publish Checklist. No memory-based self-check.

**Enforced by `kipi_voice_lint` / `kipi_copy_edit_lint`:**
- Em-dashes (any `\u2014` character)
- 55+ banned words: leverage, utilize, robust, paradigm, synergy, streamline, empower, delve, comprehensive, crucial, pivotal, innovative, transformative, cutting-edge, groundbreaking, unprecedented, tapestry, realm, catalyst, testament, optimize, foster, underscore, bolster, enhance, revolutionize, spearhead, seamlessly, meticulously, effectively, strategically, furthermore, moreover, additionally, indeed, ecosystem, landscape, holistic, scalable, disruptive, next-gen, seamless, and more. Full list: `plugins/kipi-core/kipi-mcp/src/kipi_mcp/draft_scanner.py` → `TIER1_WORDS / TIER1_VERBS / TIER1_ADVERBS`.
- Banned phrases: any `"in today's X"` variant (regex), "let's dive in," "let's explore," "it's important to note," "it's worth noting," "in conclusion," "game-changer," "unlock the potential," "revolutionize the way," "circling back," "just checking in," "i'm excited to," "thrilled to share," "humbled by," and more. Full list: `draft_scanner.py` → `BANNED_PHRASES`.
- Filler words: basically, actually, very, really, extremely, incredibly, just, quite, obviously, of course
- Passive voice patterns
- Sentence length: avg >20 words blocks
- Paragraph uniformity: all paragraphs with identical sentence counts flagged
- Rule-of-three pattern (`word, word, word`): flagged as warning (non-blocking). Review context; if it reads generic, rewrite.
- Hedging density: reported in the linter output as a metric (not blocking). Review it and trim hedges if >1 per 500 words.

If a pattern keeps slipping past, extend `draft_scanner.py` or `linter.py`. Never add rules to this file that ask Claude to remember.

See `references/voice-check.md` for the teaching reference.

### Cadence
- 3 posts per week: Tuesday, Wednesday, Thursday.
- Reposts count as posts.
- 70% time engaging on others' content, 30% posting your own.

### First-hour rule (the actual reach lever)
- Post 3-5 substantive comments each morning on 2nd-degree target posts (not 1st-degree connections). 2nd-degree comments carry 2.6x the weight of your own posts.
- First comment on your own post within 15 min of publishing.
- Revisit your own post at hour 2, hour 6, hour 24 and respond to every comment.

## Reaction-Mode Gate

Before drafting a reaction (comment, reply, quote-post, DM about someone's content):
1. Extract the poster's claims verbatim. No interpretation.
2. Show extracted claims to the founder. Do not draft until confirmed.
3. Draft in founder voice. Reactions are about the poster's ideas, not your product.
4. Self-check: zero product name-drops unless founder explicitly asked.

## Pre-Publish Checklist

Run in this order. Drafting is never blocked by cadence — only the final ship decision is.

### Step 0: Cadence awareness (ADVISORY, posts only)

When drafting a new original post, call `kipi_linkedin_cadence_check()` and surface the result to the founder. Do NOT block the draft — the founder may be preparing a post for a later week, or deliberately overriding the cap.

- If `posts_this_week >= 3`: surface verbatim "This would be your Nth post this week (cap is 3). Intentional override, or draft for next week?" and wait for the founder's answer before continuing.
- If `warnings[]` contains `engage_ratio`: surface the ratio and suggest 2nd-degree comments before shipping. Not blocking.

Skip Step 0 entirely when drafting a comment, reply, DM, or About section.

### Step 1: Deterministic gate (BLOCKING)

Call `kipi_linkedin_gate(draft, kind, day_of_week, override_day)`. Pass `kind` every time based on what you are drafting:

- `kind="post"` — original post. Hashtag, body-link, and day-of-week rules all apply.
- `kind="comment"` — comment or reply on another post. Hashtag and voice/copy rules apply; body-link and day-of-week rules do not.
- `kind="dm"` — direct message. Same as comment.
- `kind="about"` — LinkedIn About section. Same as comment.

For `kind="post"` only:
- `day_of_week` is the **ship day** weekday (`tue`/`wed`/`thu`). If you do not know the ship day, OMIT this field — passing today's weekday by default will block drafts prepared a day early.
- `override_day=true` bypasses the day-of-week gate.

If `pass: false`, read `violations[]`, `lint_voice.violations[]`, and `lint_copy.replacements/filler_words/passive_voice`. Fix each one and re-run until `pass: true`. After 3 iterations, surface the violation verbatim and ask whether to override.

Violation types: `hashtag_count`, `body_link` (posts only), `day_of_week` (posts only), plus any from `lint_voice` (`emdash`, `banned_word`, `banned_phrase`, `filler_opener`, `structural_opener`, `sentence_length`, `paragraph_uniformity`, `rule_of_three` warning-only) and `lint_copy` (replacements, filler_words, passive_voice).

### Step 2: Subjective checks (not mechanizable)

These require human judgment. Verify before returning:

1. First sentence scar-anchored (lead with real operational experience)?
2. Matches one of the founder's committed pillars (from `my-project/linkedin-playbook.md`)?
3. First-hour engagement plan stated (posts only: 3-5 2nd-degree comments to land)?
4. Pillar tag declared (posts only: `[Pillar 1: scar]`, `[Pillar 2: founder-op]`, `[Pillar 3: AI/visibility]`)?

If any subjective check fails, fix before returning the draft.

### Step 3: Log on ship (founder-triggered)

When the founder confirms a post shipped, call `kipi_log_linkedin_activity(kind="post", url=..., pillar=...)`. Same for every 2nd-degree comment: `kind="comment"`. This feeds Step 0's cadence check.

## LLM Visibility Mode

When the question is about visibility beyond LinkedIn (personal site, schema, podcasts, being findable by AI):

1. Read `references/llm-visibility.md` for the entity graph framework.
2. Read instance `my-project/llm-visibility-plan.md` for the founder's committed plan.
3. Apply entity consistency rule: name, title, one-line positioning must be byte-identical across LinkedIn, X, GitHub, personal site, podcast bios.
4. Third-party mentions beat owned content for LLM trust.
5. Skip Forbes/Wikipedia advice unless the founder has ≥5 independent mentions already.

## Output Rules

- Every draft is copy-paste ready. No "[insert hook here]" placeholders.
- Tag drafts with pillar: `[Pillar 1: scar]`, `[Pillar 2: founder-op]`, `[Pillar 3: AI/visibility]`.
- If the founder's pillars aren't in `my-project/linkedin-playbook.md`, ask before drafting.
- Never invent metrics, quotes, or company names the founder didn't provide.
- Mark unverified claims `{{UNVALIDATED}}` or `{{NEEDS_PROOF}}`.

## Related Skills

- `founder-voice` — apply alongside for voice DNA enforcement
- `audhd-executive-function` — apply if founder profile flags AUDHD (all output must be copy-paste actionable)
