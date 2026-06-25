# Changelog

All notable changes to the `prd-os` plugin are recorded here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow semantic versioning; see `README.md` for the bump policy and the distinction between plugin version and config schema version.

## [Unreleased]

(next release goes here)

## [0.5.0]

### Added
- **Cross-PRD findings advisory**: `findings_xref.py` surfaces prior
  `rejected`/`deferred` findings from sibling PRDs that closely match a pending
  finding (token-shingle Jaccard, deterministic, read-only, no LLM). Wired into
  `/prd-triage` via `findings_writer.py advisory`, which swallows every xref
  failure so it can never block triage. Threshold resolves flag > config
  `xref_threshold` > 0.6, validated to a finite [0,1] value.
- **`/prd-os-init`** (`prd_os_init.py`): one-time bootstrap that writes
  `.prd-os/config.json` with defaults. Idempotent, non-destructive, validates
  what it writes. The runners previously pointed at it but it did not exist.
- **`/prd-map`** (`prd_map_runner.py` + `codebase_map.schema.json`): facts-only
  codebase snapshot for grounding PRDs. `codebase_map_path` added to config.
- **PRD template sections**: `Alternatives considered`, `Scenarios`, and
  `Resolved decisions` give the cold-context reviewer the decision space.
- **Review rubric**: a penalty-of-being-wrong lens for assigning severity
  (alongside the existing dimensions, including Recurring gap classes).

### Fixed
- `kipi-dsse` `issue_runner.py` defaulted `issues_dir` to `issues` while
  `config.py` used `.prd-os/issues`; a no-config repo wrote issue specs to one
  path and the runner looked in another. Aligned to the canonical default.

### Removed
- Legacy issue-execution stack: `scripts/issue_runner.py`,
  `hooks/scope_hook.py`, `hooks/stop_gate.py` (and their tests). Issue
  execution and scope/stop enforcement are owned by the `kipi-dsse` plugin
  ("the spine goes native"); the prd-os copies were unreachable (no `issue-*`
  commands here) and could not even read kipi-dsse's state schema, so both
  plugins' hooks fired on every edit with the prd-os copy failing open. prd-os
  now ships no hooks. The PRD-side concurrency guard is unaffected — it reads
  `active-issue.json` directly via `concurrency.py`.

### Notes
- All 0.4.0 capabilities preserved (spillover gate, persona/skeptic review,
  gap-classes dimension). The additive parts of this release add capability;
  the removal deletes only dead duplicates, no reachable behavior.

## [0.4.0]

### Added
- **Spillover gate** (`.prd-os/spillover.jsonl`): out-of-scope findings are
  captured to a durable ledger, and `prd_runner.py spillover add|list|check|resolve`
  manages it. `gates run` now FAILS while any spillover item is open, so an
  out-of-scope finding can never be silently dropped. `resolve` requires a closed
  issue (or an explicitly recorded `--void` reason).
- A `deferred` triage disposition AUTO-creates an open spillover item
  (findings_writer); `rejected` stays terminal. Moving a finding off `deferred`
  clears its item.
- `prd-archive` + `issue-closeout` report each spillover item, its resolving
  issue, the fix, and the system impact.

## [0.3.0]

### Added
- `templates/gap-classes.md`: a catalog of recurring defect classes (scaling,
  security, correctness/concurrency, cross-cutting) distilled from a
  reproducer-first, adversarially-reviewed build where ~50 defects were caught
  before merge. General by construction; no product specifics.
- `templates/review-rubric.md`: a sixth review dimension, "Recurring gap
  classes," that checks a PRD's design against the catalog.
- `commands/prd-review.md`: `/prd-review` now reads `gap-classes.md` alongside
  the rubric and feeds it to Codex, so dimension 6 has its source.

## [0.1.0] - 2026-04-16

### Added
- Initial plugin scaffold.
- `.claude-plugin/plugin.json` manifest (name, version, description, author).
- Directory tree for `commands/`, `hooks/`, `scripts/`, `templates/`, `tests/`, and `skills/prd-os/`.
- `skills/prd-os/SKILL.md` placeholder describing the planned system.
- `README.md` documenting the package layout, portable-core vs repo-local split, and versioning policy.
- This changelog.

### Notes
- Scaffold only. No runner logic, no commands, no hooks, no templates, no tests are wired.
- No changes to the host repo's settings, commands, or runtime.
- Config schema version not yet defined; lands with the runner port in step 3.
