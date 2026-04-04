# Template: Medium Article

> Used by `/q-market-create medium [topic]`
> Cadence: Draft Friday, publish Sunday (or your chosen schedule)
> Theme: Pulled from editorial-calendar.md

---

## Pre-Generation Steps

1. **Check editorial calendar** - What theme is assigned for this week?
2. **Read ALL canonical sources** for the theme (see content-themes.md)
3. **Query NotebookLM** (PRIMARY use for Medium):
   - "What evidence supports [theme's core claim]?"
   - "What counterarguments exist for [theme's position]?"
   - "What real-world examples illustrate [theme]?"
4. **Check recent debriefs** - Any conversation insights that deepen this theme?
5. **Check case studies** - Any case that fits as concrete example?
6. **Review previous content** - Avoid repeating what was already said this week

## Structure

```markdown
# [Title - specific, not clickbait. States the insight directly.]

[HOOK - 2-3 sentences. Start with a concrete scenario, stat, or question.]

## [Section 1: The Problem - with specifics]
[200-300 words. Name the tools, the teams, the failure mode. Use a real example.]

## [Section 2: Why It Persists]
[200-300 words. The structural reason this hasn't been solved.]

## [Section 3: What Changes It]
[200-300 words. The shift in thinking required. NOT "use {{YOUR_PRODUCT}}." Let the reader connect the dots.]

## [Section 4: Implications]
[100-200 words. Forward-looking. End with a question or reflection.]
```

## Imagery

See `04-post-visuals.md` for full decision matrix.

- **Hero image:** Nano Banana (16:9, editorial quality, matches article theme)
- **In-article images:** Optional Gamma diagrams for data-heavy sections or process flows
- **Prompt hint:** Abstract, conceptual. Matches the article's core metaphor. No stock photo look.
- **Medium-specific:** Hero image appears as thumbnail in feeds. Make it attention-grabbing at small sizes.

## Rules

- 800-1500 words (hard range)
- At least one concrete example
- Cite sources
- Subheadings every 200-300 words
- No "{{YOUR_PRODUCT}} solves this" framing
- First person where it adds credibility
- End with a question or forward-looking statement, not a pitch
- No banned words
- Mark vision claims {{UNVALIDATED}} if unbuilt

## Output Format

Save to: `output/marketing/medium/medium-YYYY-MM-DD-[slug].md`

## Post-Generation

1. Run `/q-market-review` against the draft
2. Create Content Pipeline DB entry (Status: Drafted)
