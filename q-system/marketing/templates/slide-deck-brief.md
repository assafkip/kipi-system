# Template: Slide Deck Brief (Gamma Presentation)

> Used by `/q-market-create deck [topic]`
> Generated via Gamma MCP as a presentation

---

## Pre-Generation Steps

1. **Determine deck type:** Pitch (8-12 slides), Topic (3-5 slides), Meeting-specific
2. **Read canonical sources:** talk-tracks.md, decisions.md, current-state.md, stats-sheet.md, proof-points.md
3. **Query NotebookLM** for topic/meeting decks (optional)
4. **Check existing decks** in `output/marketing/decks/`

## Input Text Structure: Full Pitch Deck

```
Create a pitch deck for {{YOUR_COMPANY}}, a {{YOUR_STAGE}} startup building {{YOUR_CATEGORY}}.

SLIDE 1 - TITLE:
"{{YOUR_TAGLINE}}"
{{YOUR_COMPANY}} | {{YOUR_STAGE}}

SLIDE 2 - THE REALITY:
[Key stats that prove the problem exists. From stats-sheet.md.]

SLIDE 3 - THE EVIDENCE:
[2-4 case studies or proof points from proof-points.md]

SLIDE 4 - THE ANSWER:
[{{YOUR_METAPHOR}} - what you are, in one slide]

SLIDE 5 - HOW IT WORKS:
[Your pipeline/process/workflow visualization]

SLIDE 6 - THE PRODUCT:
[What's built today. Technical credibility points from current-state.md]

SLIDE 7 - VALIDATION + MARKET:
[Endorsers, market size, pricing from stats-sheet.md]

SLIDE 8 - COMPETITIVE LANDSCAPE:
[Status quo as #1 competitor. Named adjacents from competitive-landscape.md]

SLIDE 9 - TEAM + ASK:
[Founders, fundraise amount, allocation]
```

## Input Text Structure: Topic Deck (3-5 slides)

```
SLIDE 1 - HOOK: [Stat or question that stops the scroll]
SLIDE 2 - THE PROBLEM: [Specific, concrete, with examples]
SLIDE 3 - THE SHIFT: [The insight or category-level change]
SLIDE 4 - PROOF: [Evidence, case studies, data]
SLIDE 5 (optional) - IMPLICATIONS: [What this means for the audience]
```

## Rules

- Headlines carry the argument - body text supports, doesn't repeat
- One insight per slide
- Stats are visual anchors (large, bold, isolated)
- Dark, minimal aesthetic - no clip art, no stock photos
- {{YOUR_BRAND_THROUGHLINE}} as the brand through-line

## Output Format

Save to: `output/marketing/decks/deck-[topic]-YYYY-MM-DD.md`
