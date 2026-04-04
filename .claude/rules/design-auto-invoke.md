---
description: Auto-invoke design skills when building NEW UI pages or components
globs:
  - "sites/**/*.html"
  - "sites/**/*.css"
  - "sites/**/*.tsx"
  - "sites/**/*.jsx"
---

# Design Skill Auto-Invocation (ENFORCED)

Invoke design skills ONLY when creating new pages, components, or landing pages from scratch.

| Trigger | Skill | What it does |
|---------|-------|-------------|
| Creating a NEW webpage, landing page, or UI component | `kipi-design:ui-ux-pro-max` | UX guidelines, styling, accessibility |
| Brand identity work (logo, identity system, guidelines) | `kipi-design:brand` | Brand voice, visual identity, messaging |
| Comprehensive design (logo, CIP, banners, slides, tokens) | `kipi-design:design` | Orchestrates all design sub-skills |

**Rule:** Run `ui-ux-pro-max` first to generate the design system BEFORE writing new pages/components.

**Gate check:** The globs above are a file-scope filter, NOT a trigger. Before invoking any design skill, verify: "Am I creating a NEW page or component from scratch?" If editing an existing file, skip this rule entirely, even if the glob matches.

**Do NOT invoke for:**
- Editing existing HTML/CSS (typo fixes, content updates, minor tweaks)
- Template files, config files, or build output
- Files outside `sites/` (system HTML like schedule templates)
- Test files or documentation
