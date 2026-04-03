---
description: Auto-invoke design skills when building UI or visual output
globs:
  - "**/*.html"
  - "**/*.css"
  - "**/*.tsx"
  - "**/*.jsx"
  - "**/*.svelte"
  - "**/*.vue"
---

# Design Skill Auto-Invocation (ENFORCED)

When building any webpage, landing page, UI component, or visual output:

| Trigger | Skill | What it does |
|---------|-------|-------------|
| Building ANY webpage, landing page, UI, or HTML | `kipi-design:ui-ux-pro-max` | UX guidelines, styling, accessibility |
| Brand-related output (logo, identity, guidelines) | `kipi-design:brand` | Brand voice, visual identity, messaging |
| Comprehensive design (logo, CIP, banners, slides, tokens) | `kipi-design:design` | Orchestrates all design sub-skills |

**Rule:** ALWAYS run `ui-ux-pro-max` first to generate the design system BEFORE writing any HTML/CSS/JS.
