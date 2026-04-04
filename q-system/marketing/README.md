# Marketing System

Automated content + distribution system for founders.

## Structure

```
marketing/
  templates/           - Post templates by platform
  assets/              - Reusable copy blocks (bio, boilerplate, stats, proof points)
  content-guardrails.md - Quality gates before publishing
  content-themes.md    - Theme rotation for content planning
  brand-voice.md       - Channel-specific voice rules
```

## Commands

| Command | What it does |
|---------|-------------|
| `/q-market-plan` | Weekly content planning from theme rotation + calendar |
| `/q-market-create [type]` | Generate content (linkedin, x, medium, substack, one-pager, outreach, deck, follow-up, reddit, investor-update) |
| `/q-market-review` | Validate against guardrails |
| `/q-market-publish` | Mark published, update tracking |
| `/q-market-status` | Pipeline snapshot |

## Content Cadence (customize to your schedule)

| Day | Content Type |
|-----|-------------|
| Mon | Signals / news roundup |
| Tue | Thought leadership post |
| Wed | Article publish day |
| Thu | Thought leadership post |
| Fri | Behind-the-scenes / building-in-public |

## Theme Rotation

Themes rotate on a 4-week cycle. Define your themes in `content-themes.md`. Each theme maps to canonical files that provide the source material.
