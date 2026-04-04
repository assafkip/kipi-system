# Template: Substack Newsletter

> Used by `/q-market-create substack [topic]`
> More personal voice than Medium. Direct address to subscribers.
> Can repurpose/expand the week's Medium article or be original content.

---

## Pre-Generation Steps

1. Read `canonical/content-intelligence.md` for performance patterns
2. Read this week's Medium article draft (if exists) for potential expansion
3. Read `canonical/talk-tracks.md` for current positioning language
4. Query NotebookLM for research grounding if topic benefits from it

## Structure

### Subject Line
- Under 50 characters
- Specific, not clickbait
- Pattern: "[Insight] + [Stakes]" or a direct question

### Opening (2-3 sentences)
- Personal hook. What happened this week that made you think.
- First person. Direct address ("you" to the subscriber).
- No throat-clearing. Start with the insight, not the setup.

### Body (400-800 words)

**Structure A: Expand on Medium**
- Link to the Medium article
- Add behind-the-scenes thinking, founder perspective, what you're still figuring out
- More vulnerable/honest than Medium (show the uncertainty)

**Structure B: Original**
- One insight from this week (call, signal, conversation, something you read)
- Why it matters for your audience
- Connect to the broader thesis

**Structure C: Signals roundup + commentary**
- Top 3-5 signals from the week with practitioner commentary
- What patterns you see across them
- What it means for the industry

### "What I'm Seeing" Section (3-5 bullets)
- Quick hits from the week: signals, conversations, industry moves
- Each bullet is 1-2 sentences max
- This is the "value density" section readers come back for

### Closing CTA (1-2 sentences)
- "If this resonated, share it with someone who'd find it useful."
- "Reply and tell me [specific question]. I read every response."
- "Subscribe if you haven't - I publish weekly on [topic]."

## Imagery

See `04-post-visuals.md` for full decision matrix.

- **Header image:** Nano Banana (16:9, editorial style, matches newsletter theme)
- **Reuse option:** If this week's LinkedIn post already has a hero image, reuse it for visual consistency
- **Keep consistent:** Same visual identity across weekly issues builds recognition

## Rules

- More personal than Medium. This is a letter, not an article.
- First person throughout
- Show thinking-in-progress, not finished arguments
- No product pitch unless it's a company announcement
- No banned AI words
- Mark vision claims `{{UNVALIDATED}}` if unbuilt

## Output Format

Save to: `output/marketing/substack/substack-YYYY-MM-DD-[slug].md`

## Post-Generation

1. Run `/q-market-review` against the draft
2. Create Content Pipeline DB entry (Status: Drafted)
