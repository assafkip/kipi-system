---
id: lessons-scaffold
title: Scaffold q-system/lessons/ corpus + README (promotion rule, unrelated definition, read-only-consumer invariant) + one seed kind=pattern lesson; verify lessons/ propagates via kipi update and is not excluded
status: closed
priority: p1
parent_prd: prd-cross-instance-learning-2026-06-19
allowed_files:
  - q-system/lessons/**
  - q-system/.q-system/scripts/test/test-lessons-propagation.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-lessons-propagation.sh
required_reviews: []
bypass_check: "bash q-system/.q-system/scripts/test/test-lessons-propagation.sh"
---
<!-- generated-by: prd_split.py prd=prd-cross-instance-learning-2026-06-19 finding=finding-4 at=2026-06-19T23:50:26Z -->

# Scaffold q-system/lessons/ corpus + README (promotion rule, unrelated definition, read-only-consumer invariant) + one seed kind=pattern lesson; verify lessons/ propagates via kipi update and is not excluded

## Context

Parent PRD: `.prd-os/prds/prd-cross-instance-learning-2026-06-19.md`

## Acceptance

- [ ] `q-system/lessons/README.md` documents: the promotion rule (kind=pattern|methodology only; 2+ unrelated instances; human-authored in the skeleton), the "unrelated" definition (no shared client/confidentiality boundary, not same KTLYST cluster), and the read-only-consumer invariant (instances never author or edit lessons).
- [ ] One seed lesson `q-system/lessons/<id>.md` with frontmatter EXACTLY `{id, kind, title, date}`, `kind: pattern`, HOW-only body.
- [ ] `test-lessons-propagation.sh` asserts `q-system/lessons/` is NOT in `kipi-update.sh`'s rsync `--exclude` block, and that a dry-run `rsync -ain --delete` from the skeleton `q-system/` includes `lessons/` as content (and the test FAILS if `lessons/` were excluded — negative assertion).
- [ ] `required_checks` passes (`bash q-system/.q-system/scripts/test/test-lessons-propagation.sh`).
