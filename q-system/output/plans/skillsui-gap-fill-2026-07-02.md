# skillsui gap-fill: 4 missing styles + animated-backgrounds reference

**Date:** 2026-07-02
**Origin:** [USER-DIRECTED] founder reviewed skillsui.app/skills, asked to fill the gaps with free repos instead of buying PRO.

## What / why

skillsui.app sells ~40 design skills. Our ui-ux-pro-max (84 styles) already covers ~90% as style knowledge. Two real gaps:
1. Four style names absent from `styles.csv`: Art Deco, Kawaii, Cozy/Cottagecore, Matrix.
2. No pointer to drop-in animated background component code (their Aurora/Liquid/Meteors/Constellations/Shooting Stars PRO offerings) or the scroll-scrub cinematic hero technique.

## Approach (the pick)

- Add 4 rows to `styles.csv` (No 86-89), same 22-column idiom as existing rows. They become searchable with zero code change (`core.py` DOMAINS already maps `style` → styles.csv).
- New `references/animated-backgrounds.md` mapping each effect → free repo + usage note, plus one pointer line in SKILL.md so it is discoverable (wiring, not dead text).
- Alternatives set aside: (a) a new `effects.csv` domain would mean editing the vendored `core.py`, creating merge friction against upstream nextlevelbuilder; (b) vendoring full component libraries is heavy, licenses vary per-component (Aceternity), and the repos move faster than our sync cadence.

## Files to touch

- `plugins/kipi-design/skills/ui-ux-pro-max/data/styles.csv` — +4 rows
- `plugins/kipi-design/skills/ui-ux-pro-max/references/animated-backgrounds.md` — new
- `plugins/kipi-design/skills/ui-ux-pro-max/SKILL.md` — +1 pointer line to the new reference
- Load path: `~/.claude/plugins/marketplaces/kipi/` (git clone of this repo) — commit, push, `git pull` there

## Acceptance criteria

- [x] `styles.csv` parses clean via python `csv`; every new row has exactly 22 columns (pre-existing bad-width row No 77 captured as spillover sp-42f164c5)
- [x] `search.py --domain style` returns hits for "art deco", "kawaii", "cottagecore", "matrix" — each ranks #1
- [x] `references/animated-backgrounds.md` exists; SKILL.md references table lists it
- [x] Marketplace clone matches repo after pull (`diff -rq` clean except `__pycache__`); search verified from the clone copy
- [x] ~~kipi update --dry~~ DEVIATION: plugins do not travel via `kipi update` (it syncs `q-system/` only). Plugin fleet path = marketplace clone + version-keyed cache; kipi-design bumped 1.2.0 → 1.2.1 (commit ee89d3f), cache picks up 1.2.1 on next plugin refresh

## Patterns to follow

- Row idiom: copy Glassmorphism row structure (checkbox checklist column, `--var` design-system column, ✓/⚠ ratings).
- Reference doc idiom: existing `references/*.md` are plain task-scoped markdown.
- Wiring-check scar 2026-06-20: runtime loads the marketplace clone, not this repo's `plugins/` — the pull step is the load-path proof, not optional.
