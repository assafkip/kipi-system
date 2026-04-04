---
description: Auto-invoke design skills only for public-facing pages and assets
globs:
  - "sites/**/*.html"
  - "sites/**/*.css"
  - "sites/**/*.tsx"
  - "sites/**/*.jsx"
---

# Design Skill Auto-Invocation (ENFORCED)

Invoke design skills ONLY when building output that will be published or seen by the founder's audience (prospects, investors, users, public web).

| Trigger | Skill | What it does |
|---------|-------|-------------|
| Creating a public-facing webpage, landing page, or UI | `kipi-design:ui-ux-pro-max` | UX guidelines, styling, accessibility |
| Brand identity work (logo, identity system, guidelines) | `kipi-design:brand` | Brand voice, visual identity, messaging |
| Comprehensive design (logo, CIP, banners, slides, tokens) | `kipi-design:design` | Orchestrates all design sub-skills |

**Gate check:** Before invoking, ask: "Will someone other than the founder see this?" If no, skip.

**Do NOT invoke for:**
- HTML/CSS built for the founder's own use (dashboards, schedules, internal tools, reports)
- Editing existing pages (typo fixes, content updates, minor tweaks)
- Template files, config files, or build output
- System HTML (morning schedule, logs, debug views)
- Test files or documentation
