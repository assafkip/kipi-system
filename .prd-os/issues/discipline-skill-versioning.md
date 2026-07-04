---
id: discipline-skill-versioning
title: Freeze fable-discipline SKILL.md as -v1; record merge in prd-os CHANGELOG
status: open
priority: p0
parent_prd: prd-fable-discipline-2026-07-04
allowed_files:
  - plugins/prd-os/CHANGELOG.md
  - plugins/prd-os/skills/prd-os/references/fable-discipline-v1.md
disallowed_files: []
required_checks:
  - test -f plugins/prd-os/skills/prd-os/references/fable-discipline-v1.md
  - diff -q plugins/kipi-core/skills/fable-discipline/SKILL.md plugins/prd-os/skills/prd-os/references/fable-discipline-v1.md
  - grep -q 'fable-discipline' plugins/prd-os/CHANGELOG.md
required_reviews: []
bypass_exempt: "Pure preservation + documentation (frozen -v1 copy, CHANGELOG entry). Introduces no gate, skip, or no-verify bypass."
---
<!-- generated-by: prd_split.py prd=prd-fable-discipline-2026-07-04 finding=finding-4 at=2026-07-04T01:45:32Z -->

# Freeze fable-discipline SKILL.md as -v1; record merge in prd-os CHANGELOG

## Context

Parent PRD: `.prd-os/prds/prd-fable-discipline-2026-07-04.md`

## Acceptance

Current SKILL.md preserved verbatim as fable-discipline-v1.md inside the prd-os plugin; CHANGELOG.md Unreleased section records the merge with rationale (one discipline system; taste-skill binary-phrasing lesson). No behavior change in this issue.
