---
name: deck-ai
description: Generate an editable PPTX presentation from markdown content. Runs locally, no subscription; python-pptx builds the slides and Unsplash supplies the imagery. Invoke when the user asks to "make a deck", "build slides from this", or "turn this into a presentation".
---

# deck-ai

Turn plain markdown into a themed, image-rich slide deck exported as an
editable PPTX. Every text frame stays editable in PowerPoint or Keynote.
Runs locally. No subscription.

## What this skill does

1. Reads source markdown (slides separated by `---`).
2. Picks a layout + image keyword per slide. Claude writes `decisions.json`
   with the Write tool. No extra API call.
3. Fetches images from Unsplash by keyword and embeds them in the file
   (no hotlinks).
4. Renders the whole thing to PPTX via `python-pptx`.

## When to invoke

Triggers: "make a deck", "turn this into slides", "slide version of X",
"build a presentation from this", "gamma-style deck".

Do NOT invoke for plain editing / rewriting of existing slide content.
The output is PPTX. If the user needs PDF, produce the PPTX first and
convert it outside this skill.

## Required setup (first run)

### Prerequisites
```
python3 -m pip install python-pptx
```

### API key
- **Unsplash** (required when any slide has an image keyword):
  https://unsplash.com/oauth/applications, only the **Access Key**.
- Key lives in `.env` at the calling instance root:
  ```
  echo 'UNSPLASH_ACCESS_KEY=<your-key>' >> ./.env
  ```
- Never commit `.env`. Never paste the key into any file in this skill.
- No separate Anthropic key needed. When this skill runs inside Claude Code,
  Claude itself writes `decisions.json`.

## Workflow (per deck)

```
# 1. Preflight: key + python-pptx must be present
bash <skill>/scripts/check_env.sh

# 2. Claude reads <input.md>, decides layout + image keyword per slide,
#    and WRITES ./decisions.json with the Write tool (schema below).

# 3. Render
python3 <skill>/scripts/render_pptx.py <input.md> ./decisions.json ./deck.pptx
```

`scripts/fetch_images.py` is the Unsplash resolver `render_pptx.py` imports.
Run it directly only to debug a keyword:
`python3 <skill>/scripts/fetch_images.py "koi fish"`.

### decisions.json schema (step 2)

One object per slide, in source order. `render_pptx.py` validates this file
and exits non-zero on any violation, including a count mismatch against the
number of slides in the source.

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

See `references/layout-catalog.md` for the full enum.
Force a layout by adding `<!-- layout: <name> -->` in a slide body.

## Image keywords

Images come from the `image_keyword` field in `decisions.json`, one per slide.
There are no in-body image placeholders; a keyword written into slide text is
rendered as text. Use concrete nouns, 1-3 words.
Good: `mountain sunrise`, `library books`, `child drawing`.
Bad: `feeling of wonder`, `theme of courage` (abstract concepts return weak results).

## Look

One built-in look: neutral serif-friendly palette, 13.333 x 7.5in widescreen.
There is no theme system. To restyle, edit the palette constants at the top of
`scripts/render_pptx.py` or restyle the generated PPTX in PowerPoint.

## Limitations

- Unsplash free tier: 50 requests/hour. Repeated keywords are cached per run.
- Markdown support is bullets, numbered lists, blockquotes, `**bold**` and h2.
  HTML-heavy content is not rendered.
- No speaker notes, no transitions, no charts.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `MISSING: python-pptx` | `python3 -m pip install python-pptx` |
| `UNSPLASH_ACCESS_KEY not set` | Add to `.env` at calling dir |
| `decisions count N != slides M` | One decisions entry per source slide, in order |
| `slide N layout=X needs image_keyword` | `cover` / `image-right` / `image-left` require a keyword |
| Images all say "no image found" | Keywords too abstract. Use concrete nouns. |
| Layout looks wrong | Check `<!-- layout: X -->` hint in the slide body |

## What this skill does NOT do

- AI-generated images (Unsplash stock only; could add Flux/Ideogram later)
- Themes or a brand theme editor (one built-in look)
- Per-slide image retries (one Unsplash result per keyword; no ranking)
- PDF export
