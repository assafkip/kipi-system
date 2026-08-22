---
id: srsa-authoritative-path-contract
title: Implement the authoritative instance and fleet path contract
status: open
priority: p0
parent_prd: prd-single-runtime-state-authority-2026-07-24
allowed_files:
  - plugins/kipi-core/kipi-mcp/src/kipi_mcp/paths.py
  - plugins/kipi-core/kipi-mcp/tests/test_paths.py
  - plugins/kipi-core/kipi-mcp/tests/conftest.py
disallowed_files:
  - q-system/canonical/**
  - q-system/my-project/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_paths.py
required_reviews:
  - runtime-owner
bypass_check: "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_paths.py -k 'ambiguous or plugin_cache_write'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-single-runtime-state-authority-2026-07-24 finding=finding-1 at=2026-07-24T20:54:11Z -->

# Implement the authoritative instance and fleet path contract

## Context

Parent PRD: `.prd-os/prds/prd-single-runtime-state-authority-2026-07-24.md`

## Acceptance

Write failing root-resolution and ambiguity tests first. Derive each instance state root from registry path, subtree_prefix, and instance_q_dir, require an explicit standalone mapping, and resolve fleet registry only from KIPI_FLEET_ROOT.

AMENDED 2026-08-22 (prd-canonical-read-path-repair-2026-08-22, finding-10). The
acceptance above never mentioned `my_project_dir`, so this issue's required_check could
pass while `current_state` stayed empty. Added, in scope because it is the same property
table in the same file:

- `my_project_dir` resolves from the instance tree exactly as `canonical_dir` does. It is
  the identical defect: `morning_init.py:192` reads `current-state.md` from
  `paths.my_project_dir`, which today points at `~/.kipi-system/instances/<name>/`.
- Do NOT treat `valid: true` as proof this landed. `_validate_digest` needs 5 of 7 checks
  and dropping `current_state.works_today` still leaves 6 reachable, so the headline
  signal goes green with this half broken (finding-28). Assert `current_state` directly.
- END-TO-END ASSERTION (finding-9, finding-14): call `kipi_canonical_digest` from the
  consulting instance and assert a REAL value that exists in no template and in no fossil
  stub -- the heading `RULE-2026-08-18-A` from that instance's live `decisions.md`. The
  fossil stubs each carry exactly one fenced `### RULE-XXX: [Name]` template heading and
  `_split_sections` does not skip fences, so asserting on the shape rather than the value
  is a false green.
- `ensure_dirs()` (`paths.py:218-221`) mkdirs both properties. Once they are repo-derived,
  an unset `repo_dir` writes into the real plugin dir; `test_paths.py:136` is the case.
- `conftest.py` has NO fixture with a non-null `instance_q_dir` (lines 58, 66), so the
  registry branch would ship untested. Add one. conftest.py is added to allowed_files for
  exactly this.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Implement the authoritative instance and fleet path contract
