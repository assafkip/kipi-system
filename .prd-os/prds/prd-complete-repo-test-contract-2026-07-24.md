---
id: prd-complete-repo-test-contract-2026-07-24
title: Complete Repository Test Contract
status: approved
created_at: 2026-07-24T21:00:00Z
updated_at: 2026-07-24T21:01:37Z
owner: senior-staff
reviewers: []
findings_path: .prd-os/findings/prd-complete-repo-test-contract-2026-07-24-findings.jsonl
codex_reviewed_at: 2026-07-24T21:01:01Z
---

# Complete Repository Test Contract

## Problem

CI installs only `pytest`, runs the skeleton capability gate, separation
validation, and PRD OS tests
[`.github/workflows/validate.yml:20-47`]. The shipped MCP package declares
runtime dependencies plus separate test dependencies
[`plugins/kipi-core/kipi-mcp/pyproject.toml:6-18`], but CI does not install the
package or collect its test suite. `scripts/test_persona_reorg.py` calls
`sys.exit` at module import time [`scripts/test_persona_reorg.py:122-124`],
which can terminate pytest collection.

The design publish gate imports a `design_room` executor and contains a
self-test path
[`plugins/kipi-design/hooks/publish_gate.py:135-155`,
`plugins/kipi-design/hooks/publish_gate.py:226-280`], but the executor is not
packaged inside `kipi-design` and the workflow does not run its tests. A
2026-07-24 run of `python3 validate-separation.py 3` reported 70 pass, 1 fail,
and 1 warning, proving a broad capability gate can fail while CI still lacks a
declared path for shipped runtime suites.

## Goals

- Create one repository-level test entrypoint and one deterministic manifest of
  every shipped plugin suite, script test, self-test, and enforcement hook.
- Install declared MCP and plugin test dependencies and test MCP as an
  installed package.
- Make pytest collection import-safe for script modules.
- Package the design-room executor with `kipi-design`, or make the publish gate
  self-contained within that plugin boundary.
- Run the design publish-gate self-test in CI.
- Fail CI when a shipped test artifact or enforcement hook lacks a manifest
  execution path.
- Keep the current skeleton capability gate and extend its declared coverage
  contract.

## Non-goals

- Fixing product behavior exposed by newly collected tests.
- Replacing a working skeleton gate without an equivalence receipt.
- Adding optional developer tools that are not required by a shipped suite.
- Editing external instance repositories.

## Proposed approach

1. Extend the existing `q-system/.q-system/capability-manifest.json` and
   `capability-gate.py` two-way discovery contract to enumerate shipped plugin
   suites, executable test files, hook configuration, and self-test markers.
   Do not create a second test manifest. Explicit exemptions require an owner
   and rationale.
2. Add one entrypoint that creates an isolated environment, installs each
   package with its declared test extra, runs installed-package tests, script
   tests, hook self-tests, and the existing capability gate, then returns one
   aggregate exit code.
3. Move import-time execution behind `main()` guards and add a collection-only
   check.
4. Put the design executor and gate in one packaged boundary and test the
   installed wheel, not the source checkout.
5. Wire CI to the repository entrypoint and run a negative manifest fixture
   that adds an undeclared shipped test or hook and expects failure.

## Alternatives considered

- **Add individual CI steps manually.** Rejected because new shipped suites can
  remain invisible.
- **Run raw pytest from repository root.** Rejected because import-time scripts
  can exit collection and installed-package wiring remains untested.
- **Remove the capability gate.** Rejected because it has working coverage the
  founder explicitly requires preserving.

## Scenarios

- **New plugin suite.** A shipped test directory appears without a manifest
  entry. The coverage contract fails before tests run.
- **MCP package.** CI builds and installs `kipi-mcp` with its test extra, then
  runs the installed suite without repository import shortcuts.
- **Script collection.** Pytest imports `scripts/test_persona_reorg.py` without
  exiting, then executes its test path explicitly.
- **Design publish.** The installed `kipi-design` package runs its publish-gate
  self-test and resolves the executor inside the same package boundary.

## Resolved decisions

- **One manifest drives coverage.** Rationale: self-enumeration catches silent
  suite omissions. The existing capability manifest remains that authority.
- **Installed-package tests are required.** Rationale: source-tree imports do
  not prove packaging.
- **The existing capability gate remains.** Rationale: extension needs proof,
  not replacement.
- **Collection and execution are separate checks.** Rationale: a module can
  collect safely and still fail its intended behavior.

## Risks and rollback

- The entrypoint can increase CI time. Emit per-suite duration and keep
  deterministic parallelism bounded. Rollback restores the prior workflow but
  keeps the manifest audit visible.
- Installing all dependencies can expose version conflicts. Build isolated
  package environments and fail with the exact resolver output.
- Packaging the design executor can change import paths. Keep a compatibility
  import until installed-wheel and source tests pass; rollback returns the old
  import with a fail-closed missing-executor result.

## Open questions

- Which current executable files with `test` in their name are historical
  artifacts rather than shipped suites?
- Should the repository entrypoint build one environment per plugin or one
  locked shared environment?
- What CI time budget triggers suite sharding without weakening the aggregate
  required check?

## Evidence

- **E1:** `.github/workflows/validate.yml:20-47`.
- **E2:** `plugins/kipi-core/kipi-mcp/pyproject.toml:6-29`;
  `plugins/kipi-core/kipi-mcp/tests/`.
- **E3:** `scripts/test_persona_reorg.py:122-124`.
- **E4:** `plugins/kipi-design/hooks/publish_gate.py:135-155`,
  `plugins/kipi-design/hooks/publish_gate.py:226-280`;
  `plugins/kipi-design/hooks/tests/test_publish_gate.py`.
- **E5:** Command result `python3 validate-separation.py 3`, run 2026-07-24:
  70 pass, 1 fail, 1 warning.

## Issues

```json
[
  {
    "id": "crtc-test-manifest",
    "finding_id": "finding-1",
    "title": "Enumerate every shipped test and enforcement path",
    "priority": "p1",
    "allowed_files": ["q-system/.q-system/capability-manifest.json", "q-system/.q-system/scripts/capability-gate.py", "q-system/.q-system/scripts/test_capability_gate.py"],
    "disallowed_files": [".github/workflows/**", "plugins/**/src/**", "q-system/canonical/**", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/scripts/test_capability_gate.py"],
    "required_reviews": ["test-owner"],
    "acceptance": "Write a failing undeclared-artifact fixture first. Enumerate shipped plugin suites, script tests, self-tests, and enforcement hooks with owned exemptions.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/scripts/test_capability_gate.py -k undeclared"
  },
  {
    "id": "crtc-repo-entrypoint",
    "finding_id": "finding-2",
    "title": "Create one repository test entrypoint and CI path",
    "priority": "p1",
    "allowed_files": ["scripts/test-repo", ".github/workflows/validate.yml", "tests/test_repo_entrypoint.py"],
    "disallowed_files": ["plugins/**/src/**", "q-system/canonical/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q tests/test_repo_entrypoint.py", "scripts/test-repo --list"],
    "required_reviews": ["ci-owner"],
    "acceptance": "Write the failing aggregate-exit test first. Install declared test dependencies, execute every manifest entry, retain the skeleton capability gate, and fail on any red suite.",
    "bypass_check": "python3 -m pytest -q tests/test_repo_entrypoint.py -k failing_entry_propagates_nonzero"
  },
  {
    "id": "crtc-installed-mcp-suite",
    "finding_id": "finding-3",
    "title": "Run MCP tests as an installed package",
    "priority": "p1",
    "allowed_files": ["plugins/kipi-core/kipi-mcp/pyproject.toml", "plugins/kipi-core/kipi-mcp/tests/test_installed_package.py"],
    "disallowed_files": ["plugins/kipi-core/kipi-mcp/src/**", ".github/workflows/**", "q-system/**", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_installed_package.py"],
    "required_reviews": ["packaging-owner"],
    "acceptance": "Write a failing source-tree-shadowing test first. Build and install the package with declared test dependencies and run tests without repository import leakage.",
    "bypass_check": "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_installed_package.py -k no_source_shadow"
  },
  {
    "id": "crtc-import-safe-collection",
    "finding_id": "finding-4",
    "title": "Make script test modules import-safe",
    "priority": "p1",
    "allowed_files": ["scripts/test_persona_reorg.py", "tests/test_collection_contract.py"],
    "disallowed_files": [".github/workflows/**", "plugins/**", "q-system/**", ".prd-os/**"],
    "required_checks": ["python3 -m pytest --collect-only -q scripts/test_persona_reorg.py", "python3 -m pytest -q tests/test_collection_contract.py"],
    "required_reviews": ["test-owner"],
    "acceptance": "Write the failing targeted collection reproducer first. Move execution behind explicit entrypoints and prove importing scripts/test_persona_reorg.py cannot terminate the process.",
    "bypass_check": "python3 -m pytest -q tests/test_collection_contract.py -k sys_exit"
  },
  {
    "id": "crtc-design-publish-package",
    "finding_id": "finding-5",
    "title": "Package and test the design publish-gate boundary",
    "priority": "p1",
    "allowed_files": ["plugins/kipi-design/pyproject.toml", "plugins/kipi-design/hooks/publish_gate.py", "plugins/kipi-design/design_room/**", "plugins/kipi-design/hooks/tests/test_publish_gate.py"],
    "disallowed_files": [".github/workflows/**", "plugins/kipi-core/**", "q-system/**", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q plugins/kipi-design/hooks/tests/test_publish_gate.py", "python3 plugins/kipi-design/hooks/publish_gate.py --self-test"],
    "required_reviews": ["design-owner", "packaging-owner"],
    "acceptance": "Write a failing installed-boundary test first. Package the executor with kipi-design or make the gate self-contained, then run its self-test from the installed artifact.",
    "bypass_check": "python3 -m pytest -q plugins/kipi-design/hooks/tests/test_publish_gate.py -k missing_executor"
  },
  {
    "id": "crtc-single-manifest-reconciliation",
    "finding_id": "finding-6",
    "title": "Prove the capability manifest is the only test authority",
    "priority": "p1",
    "allowed_files": ["q-system/.q-system/scripts/test/test-single-test-manifest.sh"],
    "disallowed_files": ["q-system/.q-system/capability-manifest.json", "q-system/.q-system/scripts/capability-gate.py", "plugins/**", ".prd-os/**"],
    "required_checks": ["bash q-system/.q-system/scripts/test/test-single-test-manifest.sh"],
    "required_reviews": ["test-owner"],
    "acceptance": "Write a failing duplicate-manifest fixture first. Prove every repository test declaration resolves through the existing capability manifest and no second authority is introduced.",
    "bypass_check": "bash q-system/.q-system/scripts/test/test-single-test-manifest.sh --reject-duplicate"
  },
  {
    "id": "crtc-aggregate-exit-contract",
    "finding_id": "finding-7",
    "title": "Prove any failing suite makes the repository entrypoint red",
    "priority": "p1",
    "allowed_files": ["tests/test_repo_entrypoint_failures.py"],
    "disallowed_files": ["scripts/test-repo", ".github/workflows/**", "plugins/**", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q tests/test_repo_entrypoint_failures.py"],
    "required_reviews": ["ci-owner"],
    "acceptance": "Write a failing aggregate-exit fixture first. Inject one red manifest entry and require scripts/test-repo to preserve a nonzero final exit.",
    "bypass_check": "python3 -m pytest -q tests/test_repo_entrypoint_failures.py -k every_red_propagates"
  },
  {
    "id": "crtc-targeted-collection-contract",
    "finding_id": "finding-8",
    "title": "Keep the import-safe issue independently collectable",
    "priority": "p1",
    "allowed_files": ["tests/test_targeted_collection.py"],
    "disallowed_files": ["scripts/test_persona_reorg.py", "plugins/**", ".github/workflows/**", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q tests/test_targeted_collection.py"],
    "required_reviews": ["test-owner"],
    "acceptance": "Write a failing isolated-collection fixture first. Collect only scripts/test_persona_reorg.py in an environment that does not require MCP or design dependencies.",
    "bypass_check": "python3 -m pytest -q tests/test_targeted_collection.py -k no_cross_suite_dependency"
  }
]
```
