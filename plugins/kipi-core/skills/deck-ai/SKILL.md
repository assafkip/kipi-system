---
name: deck-ai
user-invocable: false
description: Generate modern presentation decks (PDF) from markdown content. Local open-source alternative to Gamma — uses Slidev for layouts and Unsplash for imagery. Invoke when the user asks to "make a deck", "build slides from this", or "turn this into a presentation".
---

# deck-ai

Turn plain markdown into a themed, image-rich slide deck exported as PDF.
Closest open-source equivalent to Gamma. Runs locally. No subscription.

## What this skill does

1. Reads source markdown (slides separated by `---`).
2. Picks a layout + image keyword per slide. Two modes:
   - **LLM mode** (preferred): Claude writes `decisions.json` directly using the Write tool. No extra API call.
   - **Rules mode** (fallback): deterministic regex picks. Used when the skill is invoked from a non-LLM harness.
3. Fetches images from Unsplash by keyword.
4. Renders the whole thing to PDF via Slidev.

## When to invoke

Triggers: "make a deck", "turn this into slides", "slide version of X",
"build a presentation from this", "gamma-style deck".

Do NOT invoke for plain editing / rewriting of existing slide content.
Do NOT invoke if the user wants a PPTX specifically (use `python-pptx` instead).

## Required setup (first run)

### Prerequisites
- Node 18+ and `pnpm` on the user's machine. If missing:
  ```
  brew install node
  npm install -g pnpm
  ```

### API key
- **Unsplash** (required): https://unsplash.com/oauth/applications — only the **Access Key**.
- Key lives in `.env` at the calling instance root:
  ```
  echo 'UNSPLASH_ACCESS_KEY=<your-key>' >> ./.env
  ```
- Never commit `.env`. Never paste the key into any file in this skill.
- No separate Anthropic key needed — when this skill runs inside Claude Code, Claude itself writes `decisions.json`.

### Install workspace (one-time per instance)
```
bash <skill>/scripts/setup.sh ./deck-workspace
```
This creates a local Slidev workspace with themes installed.
Takes ~1-2 minutes first run. Subsequent runs reuse it.

## Workflow (per deck)

```
# 1. Preflight: key + deps must be present
bash <skill>/scripts/check_env.sh ./deck-workspace

# 2. (LLM mode) Claude reads <input.md>, decides layout + image keyword
#    per slide, and WRITES ./deck-workspace/decisions.json with the Write
#    tool (schema below). Skip this step when running outside Claude.

# 3. Generate Slidev markdown from source
#    LLM mode:
python3 <skill>/scripts/generate.py <input.md> ./deck-workspace/slides.raw.md \
    --theme seriph --decisions ./deck-workspace/decisions.json
#    Rules mode (no decisions file):
python3 <skill>/scripts/generate.py <input.md> ./deck-workspace/slides.raw.md --theme seriph

# 4. Fill image placeholders from Unsplash
python3 <skill>/scripts/fetch_images.py ./deck-workspace/slides.raw.md

# 5. Export PDF
bash <skill>/scripts/render.sh ./deck-workspace ./deck-workspace/slides.raw.md ./deck.pdf
```

### decisions.json schema (step 2)

One object per slide, in source order. `generate.py` validates this file
and exits non-zero on any violation.

```json
[
  {"layout": "cover",       "image_keyword": "sunrise mountains"},
  {"layout": "image-right", "image_keyword": "student classroom"},
  {"layout": "center",      "image_keyword": null},
  {"layout": "end",         "image_keyword": null}
]
```

Rules Claude must follow when writing `decisions.json`:

- `layout` is one of: `cover`, `center`, `statement`, `two-cols`, `image-right`, `image-left`, `quote`, `end`, `default`.
- Slide 1 must be `cover`.
- If a slide has `<!-- layout: X -->` in the source, use that layout.
- `image_keyword` is 1-3 concrete nouns suitable for stock photo search. Required for `cover`, `image-right`, `image-left`. `null` for every other layout.
- No brand names, no anime character names, no abstract concepts. Use the underlying physical scene instead.

Good keywords: `library books`, `koi fish`, `child drawing`, `mountain sunrise`.
Bad keywords: `Naruto`, `loneliness`, `theme of courage`, `The Ordinary World`.

## Source markdown format

Slides separated by a line containing only `---`. First slide is the cover.

Example:
```
# Deck Title

Subtitle line.

---

# Second slide

Body content here.

<!-- layout: image-right -->

Anime anchor: Naruto.

---

# Homework

Optional closing text.
```

## Layouts

See `references/layout-catalog.md` for the full enum and pick rules.
Force a layout by adding `<!-- layout: <name> -->` in a slide body.

## Image keywords

Use concrete nouns in `{{IMG:keyword}}` placeholders. 1-3 words.
Good: `mountain sunrise`, `library books`, `child drawing`.
Bad: `feeling of wonder`, `theme of courage` (abstract concepts return weak results).

## Themes

Default: `@slidev/theme-seriph` (clean serif, modern).
Fallback: `@slidev/theme-default` (sans-serif, minimal).

Install more themes in the workspace:
```
cd ./deck-workspace && pnpm add @slidev/theme-<name>
```
Browse: https://sli.dev/resources/theme-gallery

## Limitations

- Slidev renders via Playwright Chromium on first export (adds ~30s).
- Unsplash free tier: 50 requests/hour. Reuse keywords if hitting the limit.
- PDF export does not preserve interactive elements (embeds, live code).
- Slide source must be standard markdown. HTML-heavy content may break layout.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `pnpm: command not found` | `npm install -g pnpm` |
| `UNSPLASH_ACCESS_KEY not set` | Add to `.env` at calling dir |
| Images all say "no image found" | Keywords too abstract. Use concrete nouns. |
| PDF export hangs | First run downloads Chromium. Let it finish. |
| Layout looks wrong | Check `<!-- layout: X -->` hint or let rules pick |

## What this skill does NOT do (v2)

- AI-generated images (Unsplash stock only; could add Flux/Ideogram later)
- Brand theme editor (use provided themes or install more via pnpm)
- Per-slide image retries (one Unsplash result per keyword; no ranking)
