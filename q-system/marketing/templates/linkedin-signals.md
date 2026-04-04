# Template: LinkedIn Signals Post

> Used by `/q-morning` Step 4 (daily)
> NOT theme-driven. News-driven from {{YOUR_SIGNALS_SOURCE}}.

---

## Pre-Generation Steps

1. **Fetch signals** - Pull from your signals/news source
2. **Pick 2-4 top signals** based on:
   - Breaking news, high severity, actively exploited, big-name brands
   - Trending or viral potential
   - Interesting to your target audience
3. **DO NOT query NotebookLM** - signals are breaking news, not research

## Structure

```
[LEAD SIGNAL - most attention-grabbing. 1-2 sentences with key facts.]

[SIGNAL 2 - 1 sentence with key facts]

[SIGNAL 3 (optional) - 1 sentence]

[SIGNAL 4 (optional) - 1 sentence]

[CLOSER - total signals analyzed today + link]
Full breakdown: {{YOUR_SIGNALS_URL}}
```

## Imagery

See `04-post-visuals.md` for full decision matrix.

- **Format:** Hero image (breaking news needs attention-grabbing visuals)
- **Tool:** Nano Banana (16:9, dark background, data-viz / breaking-news style)
- **Prompt hint:** Reference the lead signal's topic. Abstract, urgent feel. No text overlay.
- **Fallback:** Gamma social card (headline = lead signal stat or fact)

## Rules

- 100-200 words
- Breaking news tone, not thought leadership
- Write like a practitioner sharing news, not a vendor framing narratives
- No product pitch or positioning angle
- No banned words from brand-voice.md
- Always link to {{YOUR_SIGNALS_URL}}
- Include numbers when available
- 3-5 hashtags relevant to your industry

## Output Format

Save to: `output/signals-post-YYYY-MM-DD.md`

## Post-Generation

1. Save to signals file
2. Add to Daily Posts page (if using Notion)
3. Create Content Pipeline DB entry if marketing system active
