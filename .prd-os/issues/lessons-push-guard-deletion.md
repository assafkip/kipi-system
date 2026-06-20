---
id: lessons-push-guard-deletion
title: Push guard must block committed lesson DELETION via a reverse skeleton-dict check (for rel in skel: if rel not in inst), layout-agnostic, no merge-base, with a git-rm deletion test
status: closed
priority: p1
parent_prd: prd-lessons-hardening-2026-06-20
allowed_files:
  - kipi-push-upstream.sh
  - q-system/.q-system/scripts/test/test-lessons-push-guard.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-lessons-push-guard.sh
required_reviews: []
bypass_check: "bash q-system/.q-system/scripts/test/test-lessons-push-guard.sh"
---
<!-- generated-by: prd_split.py prd=prd-lessons-hardening-2026-06-20 finding=finding-1 at=2026-06-20T01:18:13Z -->

# Push guard must block committed lesson DELETION via a reverse skeleton-dict check (for rel in skel: if rel not in inst), layout-agnostic, no merge-base, with a git-rm deletion test

## Context

Parent PRD: `.prd-os/prds/prd-lessons-hardening-2026-06-20.md`

## Acceptance

- [ ] In `kipi-push-upstream.sh`'s lessons guard, after the existing forward blob-compare loop, add a REVERSE check over the same normalized dicts: `for rel in skel: if rel not in inst:` -> fail (a skeleton lesson missing from the instance = a committed deletion). Layout-agnostic (reuses `lessons/<tail>` keys), NO merge-base. Keep the existing fail-closed on `skel is None`.
- [ ] The error message instructs running `kipi update` first if the lesson is merely out of date (the behind-instance fail-safe case).
- [ ] `test-lessons-push-guard.sh`: add a case where a clone instance commits `git rm` of a lesson -> `kipi push` REFUSES (non-zero + skeleton-authored message, before the push stage). All existing cases still pass.
- [ ] required_check passes (`bash q-system/.q-system/scripts/test/test-lessons-push-guard.sh`).
