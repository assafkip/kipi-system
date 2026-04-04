# Template: LinkedIn Thought Leadership Post

> Used by `/q-market-create linkedin-tl [topic]`
> Cadence: 2-3x/week per content-themes.md rotation

---

## Pre-Generation Steps

1. **Check editorial calendar** - What theme is assigned this week?
2. **Read canonical sources** for the theme (see content-themes.md)
3. **Check recent debriefs** - Any conversation insights that deepen this theme?
4. **Review previous posts** - Avoid repeating what was already said this week
5. **Decide imagery format** - See Imagery section below

## Structure (150-250 words)

**Hook (1-2 sentences):**
- Scar or sharp observation from real experience
- Pattern-interrupt: something unexpected or contrarian
- NOT: "I'm excited to share..." or "In today's landscape..."

**Body (3-5 short paragraphs):**
- Develop the point with specifics
- Use contrast patterns ("X isn't Y. It's Z.")
- Include at least one real example or named experience
- Short paragraphs (1-3 sentences each)

**Close:**
- Question-as-dagger (exposes an uncomfortable truth) OR
- Sharp reframe of the opening
- NEVER: "Thoughts?" / "Agree?" / "What do you think?"

**Hashtags:**
- 3-5 relevant hashtags at the end
- Include one broad industry hashtag + 2-3 specific ones

## Imagery

See `04-post-visuals.md` for full decision matrix.

- **Multi-point argument:** Gamma carousel (3-5 cards, 1:1, dark background, one insight per card)
- **Single take / hot take:** Nano Banana hero image (16:9, dark tech, abstract, data-viz style)
- **Fallback (always):** Gamma social card (1 card, headline + subtext)
- **Prompt hint:** Match visual to the post's core metaphor or stat. No stock photo look.

## Rules

- Sounds like the founder, not a content marketer
- At least one scar/real experience reference
- Zero banned AI words
- Sentence length varies
- Under 250 words
- No product pitch (unless specifically requested)

## Output Format

Save to: `output/marketing/linkedin/linkedin-tl-YYYY-MM-DD-[slug].md`

## Post-Generation

1. Run `/q-market-review` against the draft
2. Generate imagery per Imagery section
3. Create Content Pipeline DB entry (Status: Drafted)
