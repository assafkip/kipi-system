---
name: headline-engineering
description: Platform-optimized headline and hook engineering for X (Twitter), Reddit, LinkedIn, Medium, Substack. Apply when writing or reviewing any title, tweet, thread opener, Reddit post title, or social hook intended for public publication. Triggers on "write a headline", "draft a tweet", "X thread", "Reddit post", "LinkedIn post", "Medium article", "make this hook stronger", "shorter title", "more clickable", "the title is too long", or any time a draft has a title that will be seen by people outside the company.
---

# Headline Engineering

This skill fires whenever someone is writing or reviewing copy that has to earn a click.

It does NOT replace [[assaf-voice]] — voice DNA still applies. This skill handles the part voice doesn't: WHERE the copy will live and HOW that platform's audience decides what to click.

## Load order

1. **Always load** `references/platform-hooks.md` — the 6 viral patterns, char-count sweet spots, first-7-words rule.
2. **For specific platforms** load `references/headline-templates.md` — proven shapes per platform with char counts.
3. **For challenges or updates** load `references/research-receipts.md` — the source data behind every claim in this skill.

## The decision tree

Apply in order:

**Step 1 — Identify the platform.** Different platforms have different optimal lengths and reward different shapes. Don't write a "headline" abstractly. Write for X, OR for Reddit, OR for LinkedIn, OR for Medium. The same idea gets phrased four different ways.

**Step 2 — Identify the length range.**
- X: under 110 chars, sweet spot 71-100
- Reddit text titles: 30-66 chars
- LinkedIn long-form titles: 60-100 chars
- Medium titles: 50-90 chars

**Step 3 — Pick the pattern.** Six patterns earn clicks (full detail in `references/platform-hooks.md`):
- A. Absurd-concrete-object ("Real LLM on a Game Boy Color")
- B. Confession + reversal ("I'm done with X")
- C. PSA / "admits" exposé ("Anthropic admits X")
- D. Specific number + impossible feat ("64-year-old problem solved")
- E. Naive question ("Forgive my ignorance but how is X better than Y?")
- F. "I asked X to..." setup ("I asked ChatGPT to imagine itself in retirement")

**Step 4 — Front-load the punch.** First 5-7 words decide whether anyone reads word 8. If the punch is "21-byte file," "21" goes in the first 7 words, not at the end.

**Step 5 — Run the check.** Three quick tests:
- Word 7 test: cover everything after word 7. Does the hook still stop the scroll?
- Specificity test: are there at least one specific number, name, or concrete object in the first 10 words?
- Pattern test: which of A-F is this? If you can't name one, it's a generic AI-style title. Rewrite.

## Banned title patterns

Do not write any of these. They are AI-style and underperform on every platform:

- "The Ultimate Guide to X"
- "X Things You Need to Know About Y"
- "Why X Matters" (unless paired with a specific number or scar)
- "How to X" (too soft on every platform)
- "Mastering X" / "Unlocking the Power of Y"
- Long subtitle-style titles with colons + clauses + em dashes (no em dashes period)
- "X: A Comprehensive [Guide / Look / Analysis]"
- "In Today's Fast-Paced World..."

## Banned within the title

- Em dashes (—)
- Words from the [[assaf-voice]] banned list: leverage, robust, transformative, etc.
- Hedging language: "might," "could," "perhaps," "some thoughts on"
- "Excited," "thrilled," "humbled" (the gratitude tells)
- Hashtags (in the title itself; OK below the body)

## When to use this skill alongside [[assaf-voice]]

Always. Voice handles tone and sentence DNA. This skill handles the hook shape and length. Both fire for any published content.

For DM / email / internal note → voice skill only, skip this one.
For LinkedIn post / Medium article / X thread / Reddit post / Substack → both fire.

## Quality check before output

Before returning a title to the founder, verify:

1. Char count fits the platform range
2. First 5-7 words contain the punch
3. At least one specific number, name, or concrete object
4. Identifiable pattern from A-F
5. No banned words
6. No em dashes
7. Passes [[assaf-voice]] voice checks (scar / contrast / specificity / theater)

If any check fails, rewrite before output. Never output 3+ candidates without a recommended pick named explicitly ("My call: #1").
