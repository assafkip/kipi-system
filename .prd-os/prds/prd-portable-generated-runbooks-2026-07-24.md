---
id: prd-portable-generated-runbooks-2026-07-24
title: Portable Generated Runbooks
status: approved
created_at: 2026-07-24T21:20:00Z
updated_at: 2026-07-24T21:13:00Z
owner: senior-staff
reviewers: []
findings_path: .prd-os/findings/prd-portable-generated-runbooks-2026-07-24-findings.jsonl
codex_reviewed_at: 2026-07-24T21:11:36Z
---

# Portable Generated Runbooks

## Problem

Setup and operation documents encode old repository names, locations, fleet
members, and update behavior. `SETUP.md` still clones and enters
`q-founder-os` [`SETUP.md:23-27`]. `UPDATE.md` names
`~/Desktop/kipi-system`, describes subtree or Git pull behavior that differs
from the current rsync updater, and names retired `car-research`
[`UPDATE.md:12`, `UPDATE.md:47-50`, `UPDATE.md:113`, `UPDATE.md:139`].
`ARCHITECTURE.md` names retired propagation targets
[`ARCHITECTURE.md:72-80`], and `README.md` states a fixed deployment count
[`README.md:27-29`].

`instance-registry.json` currently contains 24 managed instance entries with
different `subtree_prefix` and `instance_q_dir` values
[`instance-registry.json:6-205`]. Docs duplicate that changing state instead of
generating it. `plugins/memory-lifecycle` is a tracked symlink to
`/Users/assafkip/projects/memory-lifecycle`; a 2026-07-24 `readlink` command
confirmed the other username and `test -e` failed.

## Goals

- Replace the absolute memory-lifecycle symlink with an explicit portable
  dependency contract.
- Correct setup repository and directory instructions.
- Generate instance counts and paths from the registry.
- Generate updater behavior from executable configuration where practical.
- Check docs for missing imports, stale absolute paths, and named retired
  instances.
- Classify canonical runbooks versus historical records.
- Add a fresh-clone setup smoke test.

## Non-goals

- Editing external instance repositories.
- Rewriting historical records to match current behavior.
- Changing updater behavior. This PRD documents executable state.
- Changing the current dirty registry while generating docs.

## Proposed approach

1. Replace `plugins/memory-lifecycle` with a dependency manifest containing the
   package source, version, install location, and required interface. Setup
   fails with a direct dependency error when it is absent. Do not remove the
   symlink until a source-resolution receipt records the authoritative remote,
   immutable version, and interface owner.
2. Define canonical runbooks as README, SETUP, UPDATE, INSTANCES,
   ARCHITECTURE, and CONTRIBUTE. Historical output and dated system records
   keep their original claims and receive a historical classification, not
   rewritten facts.
3. Generate the fleet table, count, paths, types, prefixes, and instance-owned
   directories directly from `instance-registry.json`. Check generated output
   in CI without modifying the registry. Render managed paths through a
   declared `$PROJECTS_ROOT` token and test reversible expansion.
4. Extract updater phase descriptions from a versioned executable behavior
   manifest consumed by both the updater and doc generator. A contract test
   refuses updater behavior that has no manifest phase. Narrative guidance can
   explain the phases but cannot redefine them.
5. Run a doc audit for unresolved imports, absolute user paths, retired
   instance names in canonical runbooks, and stale generated sections.
6. Clone a fixture checkout, install declared dependencies and hooks, resolve
   imports, run setup validation, and leave no path tied to the source machine.

## Alternatives considered

- **Use a relative symlink.** Rejected because the target is still outside the
  repository and absent on a fresh clone.
- **Hand-update fleet tables.** Rejected because registry changes will drift
  again.
- **Rewrite every old document.** Rejected because dated records are evidence,
  not current runbooks.

## Scenarios

- **Fresh machine.** Setup clones the current repository, installs the declared
  memory-lifecycle dependency, resolves all imports, and passes smoke checks.
- **Registry change.** One managed instance is added. Generated count and table
  change from the registry; a stale checked-in section fails.
- **Updater phase change.** Executable configuration changes. Generated updater
  behavior changes and the canonical runbook diff is required.
- **Historical retired name.** A dated RCA may retain it. A current runbook
  fails unless the reference is explicitly historical.

## Resolved decisions

- **Memory lifecycle becomes an explicit dependency.** Rationale: a host-bound
  symlink is not portable.
- **Registry generates fleet facts.** Rationale: it is the documented source of
  truth. [`ARCHITECTURE.md:86-92`]
- **Executable updater configuration generates behavior.** Rationale: docs
  should not compete with code.
- **Historical records stay historical.** Rationale: correcting their past
  claims would damage evidence.

## Risks and rollback

- Dependency installation can fail offline. The smoke test reports the exact
  missing package and leaves the checkout unchanged.
- Generated docs can create noisy diffs. Stable ordering and normalized paths
  make output deterministic.
- Classifying a live runbook as historical can hide current guidance. The
  canonical list is explicit and tested. Rollback restores its classification.
- Registry paths contain user-specific prefixes. Generated human docs may show
  paths, but the fresh-clone instructions use variables and never require the
  source user's home.

## Open questions

- What remote and immutable version own the memory-lifecycle interface? The
  source-resolution issue must answer this before replacement.
- Should generated fleet paths display full registry paths or normalized
  `$PROJECTS_ROOT` paths in canonical docs?
- Which dated top-level files, beyond RCAs and output, are historical records?

## Evidence

- **E1:** `README.md:27-29`, `SETUP.md:23-27`,
  `UPDATE.md:12`, `UPDATE.md:47-50`, `UPDATE.md:113`, `UPDATE.md:139`.
- **E2:** `ARCHITECTURE.md:72-92`; `INSTANCES.md`.
- **E3:** `instance-registry.json:1-205`, including 24 current managed entries.
- **E4:** `plugins/memory-lifecycle`; read-only `readlink` and `test -e`
  command results from 2026-07-24.
- **E5:** `.prd-os/spillover.jsonl` item `sp-bafc22ac`.

## Issues

```json
[
  {
    "id": "pgr-memory-lifecycle-dependency",
    "finding_id": "finding-1",
    "title": "Replace the absolute memory-lifecycle symlink with a dependency contract",
    "priority": "p2",
    "allowed_files": ["plugins/memory-lifecycle", "plugins/dependencies.json", "tests/test_plugin_dependencies.py"],
    "disallowed_files": ["instance-registry.json", "q-system/canonical/**", ".prd-os/**", ".git/**"],
    "required_checks": ["python3 -m pytest -q tests/test_plugin_dependencies.py"],
    "required_reviews": ["packaging-owner"],
    "acceptance": "Write a failing fresh-clone broken-symlink test first. Declare source, version, install location, and required interface and fail clearly when absent.",
    "bypass_check": "python3 -m pytest -q tests/test_plugin_dependencies.py -k 'absolute_symlink or missing_dependency'"
  },
  {
    "id": "pgr-generated-instance-docs",
    "finding_id": "finding-2",
    "title": "Generate fleet counts and paths from the registry",
    "priority": "p2",
    "allowed_files": ["scripts/generate-instance-docs.py", "INSTANCES.md", "tests/test_generated_instance_docs.py"],
    "disallowed_files": ["instance-registry.json", "q-system/canonical/**", ".prd-os/**", ".git/**"],
    "required_checks": ["python3 -m pytest -q tests/test_generated_instance_docs.py", "python3 scripts/generate-instance-docs.py --check"],
    "required_reviews": ["docs-owner"],
    "acceptance": "Write a failing stale-count and raw-home-path fixture first. Generate stable count, PROJECTS_ROOT-normalized path, type, subtree_prefix, and instance_q_dir fields without changing the registry.",
    "bypass_check": "python3 -m pytest -q tests/test_generated_instance_docs.py -k registry_change"
  },
  {
    "id": "pgr-generated-updater-runbook",
    "finding_id": "finding-3",
    "title": "Generate updater behavior from executable configuration",
    "priority": "p2",
    "allowed_files": ["q-system/.q-system/config/updater-behavior.json", "kipi-update.sh", "scripts/generate-updater-docs.py", "UPDATE.md", "tests/test_generated_updater_docs.py"],
    "disallowed_files": ["instance-registry.json", "q-system/canonical/**", ".prd-os/**", ".git/**"],
    "required_checks": ["python3 -m pytest -q tests/test_generated_updater_docs.py", "python3 scripts/generate-updater-docs.py --check"],
    "required_reviews": ["updater-owner", "docs-owner"],
    "acceptance": "Write a failing behavior-drift fixture first. Make the updater and generator consume one versioned behavior manifest covering preserved paths, phases, dry-run behavior, commit behavior, and rollback references.",
    "bypass_check": "python3 -m pytest -q tests/test_generated_updater_docs.py -k executable_drift"
  },
  {
    "id": "pgr-doc-portability-audit",
    "finding_id": "finding-4",
    "title": "Audit canonical runbooks for stale and nonportable references",
    "priority": "p2",
    "allowed_files": ["scripts/doc-portability-audit.py", "README.md", "SETUP.md", "ARCHITECTURE.md", "CONTRIBUTE.md", "tests/test_doc_portability.py"],
    "disallowed_files": ["q-system/output/**", "q-system/canonical/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q tests/test_doc_portability.py", "python3 scripts/doc-portability-audit.py"],
    "required_reviews": ["docs-owner"],
    "acceptance": "Write failing missing-import, stale-absolute-path, retired-instance, and old-repository fixtures first. Correct current setup instructions without rewriting historical records.",
    "bypass_check": "python3 -m pytest -q tests/test_doc_portability.py -k 'missing_import or absolute_path or retired'"
  },
  {
    "id": "pgr-runbook-classification-smoke",
    "finding_id": "finding-5",
    "title": "Classify runbooks and prove fresh-clone setup",
    "priority": "p2",
    "allowed_files": ["runbooks.json", "scripts/test-fresh-clone-setup.sh", "tests/test_runbook_classification.py"],
    "disallowed_files": ["q-system/output/**", "instance-registry.json", ".prd-os/**", ".git/**"],
    "required_checks": ["python3 -m pytest -q tests/test_runbook_classification.py", "bash scripts/test-fresh-clone-setup.sh"],
    "required_reviews": ["docs-owner", "packaging-owner"],
    "acceptance": "Write a failing unclassified-doc and source-machine-path test first. Mark canonical versus historical docs and pass setup in a disposable fresh clone.",
    "bypass_check": "python3 -m pytest -q tests/test_runbook_classification.py -k 'unclassified or historical_as_current'"
  },
  {
    "id": "pgr-updater-manifest-consumer",
    "finding_id": "finding-6",
    "title": "Prove updater and docs consume one behavior authority",
    "priority": "p2",
    "allowed_files": ["tests/test_updater_behavior_authority.py"],
    "disallowed_files": ["kipi-update.sh", "UPDATE.md", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q tests/test_updater_behavior_authority.py"],
    "required_reviews": ["updater-owner"],
    "acceptance": "Write a failing unconsumed-phase test first. Require every executable updater phase and every generated runbook section to derive from the same manifest.",
    "bypass_check": "python3 -m pytest -q tests/test_updater_behavior_authority.py -k unconsumed_phase"
  },
  {
    "id": "pgr-portable-path-rendering",
    "finding_id": "finding-7",
    "title": "Normalize registry paths in canonical runbooks",
    "priority": "p2",
    "allowed_files": ["tests/test_portable_registry_paths.py"],
    "disallowed_files": ["instance-registry.json", "scripts/generate-instance-docs.py", "INSTANCES.md", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q tests/test_portable_registry_paths.py"],
    "required_reviews": ["docs-owner"],
    "acceptance": "Write a failing source-username fixture first. Render managed paths with PROJECTS_ROOT, prove reversible expansion, and keep raw registry values untouched.",
    "bypass_check": "python3 -m pytest -q tests/test_portable_registry_paths.py -k source_username"
  },
  {
    "id": "pgr-memory-source-decision",
    "finding_id": "finding-8",
    "title": "Resolve the memory-lifecycle source before symlink removal",
    "priority": "p2",
    "allowed_files": ["plugins/memory-lifecycle-source.json", "tests/test_memory_lifecycle_source.py"],
    "disallowed_files": ["plugins/memory-lifecycle", "plugins/dependencies.json", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q tests/test_memory_lifecycle_source.py"],
    "required_reviews": ["packaging-owner"],
    "acceptance": "Write a failing missing-source receipt test first. Record the authoritative remote, immutable version, interface owner, and retrieval proof before replacement can execute.",
    "bypass_check": "python3 -m pytest -q tests/test_memory_lifecycle_source.py -k missing_or_mutable"
  }
]
```
