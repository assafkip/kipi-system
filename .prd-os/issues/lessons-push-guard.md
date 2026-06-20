---
id: lessons-push-guard
title: Pre-push guard in kipi-push-upstream.sh: hard-fail before the subtree push if q-system/lessons/ was locally modified; plus a deterministic registry-type guard that fails if a client/confidential instance is type=direct-clone
status: closed
priority: p1
parent_prd: prd-cross-instance-learning-2026-06-19
allowed_files:
  - kipi-push-upstream.sh
  - q-system/.q-system/scripts/test/test-lessons-push-guard.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-lessons-push-guard.sh
required_reviews: []
bypass_check: "bash q-system/.q-system/scripts/test/test-lessons-push-guard.sh"
---
<!-- generated-by: prd_split.py prd=prd-cross-instance-learning-2026-06-19 finding=finding-7 at=2026-06-19T23:50:26Z -->

# Pre-push guard in kipi-push-upstream.sh: hard-fail before the subtree push if q-system/lessons/ was locally modified; plus a deterministic registry-type guard that fails if a client/confidential instance is type=direct-clone

## Context

Parent PRD: `.prd-os/prds/prd-cross-instance-learning-2026-06-19.md`

## Acceptance

- [ ] `kipi-push-upstream.sh`: before the `git subtree push`, a LESSONS read-only guard hard-fails (exit 1) if `q-system/lessons/` has uncommitted changes OR if the instance's committed lessons/ content differs from the skeleton's. Compare is layout-agnostic (matches by the `lessons/`-relative subpath, so flat and nested subtree layouts both work); fetches the skeleton; `SKELETON_REMOTE` is overridable via `KIPI_SKELETON_REMOTE` for testing. README excluded.
- [ ] A registry-type guard: if `instance-registry.json` is reachable, fail if any instance is `type=direct-clone` and not on a small allowlist (`car-research`, the founder's own non-client instance).
- [ ] `test-lessons-push-guard.sh`: sets up a bare skeleton + an instance clone; asserts clean lessons + clean registry pass; an uncommitted lesson edit -> exit 1; a committed lesson edit -> exit 1; a non-allowlisted direct-clone in the registry -> exit 1.
- [ ] required_check passes (`bash q-system/.q-system/scripts/test/test-lessons-push-guard.sh`).
