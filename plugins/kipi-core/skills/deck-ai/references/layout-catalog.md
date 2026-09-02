# Layout Catalog

Layouts available to the `deck-ai` skill. Claude picks one per slide and
records it in `decisions.json`. To force a layout, add
`<!-- layout: <name> -->` at the top of the source slide.

## Layouts

| Name | When to use | Has image slot |
|---|---|---|
| `cover` | First slide. Big title, subtitle, optional hero image. | Optional |
| `center` | Single short statement or question. <25 words body. | No |
| `statement` | Full-bleed single sentence. Use for emphasis. | No |
| `two-cols` | Comparing two things side by side. | No |
| `image-right` | Concept + supporting visual (image on right). | Yes |
| `image-left` | Concept + supporting visual (image on left). | Yes |
| `quote` | Direct quote from a book / person. | No |
| `end` | Last slide. Thanks / homework / CTA. | No |
| `default` | Anything else. Title + body. | No |

## Image slots

A layout with an image slot takes its picture from the `image_keyword` field
for that slide in `decisions.json`. There are no in-body placeholders.
`scripts/render_pptx.py` resolves the keyword through `scripts/fetch_images.py`
and embeds the result. Keywords should be 1-3 words, concrete nouns.

Good: `mountain sunrise`, `koi fish`, `student writing`
Bad: `feeling of loneliness`, `theme of redemption`

