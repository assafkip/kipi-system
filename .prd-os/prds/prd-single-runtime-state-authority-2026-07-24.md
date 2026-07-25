---
id: prd-single-runtime-state-authority-2026-07-24
title: Single Runtime State Authority
status: approved
created_at: 2026-07-24T20:53:00Z
updated_at: 2026-07-24T20:54:08Z
owner: senior-staff
reviewers: []
findings_path: .prd-os/findings/prd-single-runtime-state-authority-2026-07-24-findings.jsonl
codex_reviewed_at: 2026-07-24T20:53:19Z
---

# Single Runtime State Authority

## Problem

The file OS defines instance truth under the instance repository's `q-system`
tree [`ARCHITECTURE.md:29-61`]. The MCP launch config instead maps runtime data
to `CLAUDE_PLUGIN_DATA` [`plugins/kipi-core/.mcp.json:4-9`], and `KipiPaths`
places canonical, project, memory, output, and bus state under that separate
tree [`plugins/kipi-core/kipi-mcp/src/kipi_mcp/paths.py:61-92`,
`plugins/kipi-core/kipi-mcp/src/kipi_mcp/paths.py:130-151`].
`server.py` initializes most readers from those paths but directly reads a
repository founder profile on one legacy path
[`plugins/kipi-core/kipi-mcp/src/kipi_mcp/server.py:57-129`,
`plugins/kipi-core/kipi-mcp/src/kipi_mcp/server.py:167`]. Commands and MCP can
therefore observe different truth.

Repo assets also resolve relative to the plugin package
[`plugins/kipi-core/kipi-mcp/src/kipi_mcp/paths.py:168-199`], while the actual
agent pipeline is under `q-system/.q-system/agent-pipeline/`. The current
resolver expects `q-system/agent-pipeline/` and can point installed-cache
runtimes at absent agents, templates, methodology, sources, or schedules
[`plugins/kipi-core/kipi-mcp/src/kipi_mcp/paths.py:172-195`].

## Goals

- Make the active instance repository the authority for canonical,
  `my-project`, memory, output, and bus state. Resolve its state root from the
  registry's `path`, `subtree_prefix`, and `instance_q_dir` fields rather than
  hardcoding `q-system`; do not infer writable truth from plugin installation
  paths. [E1, E2]
- Keep the fleet registry authoritative at the skeleton control-plane root,
  with an explicit path passed to fleet operations. [E1]
- Route file commands, MCP tools, morning initialization, backup, export,
  import, and validation through the same resolved contract. [E2, E3]
- Resolve agents, templates, methodology, sources, and schedule templates from
  verified packaged resources or the active instance, with no dead fallback.
  [E4]
- Migrate every record from `CLAUDE_PLUGIN_DATA` without loss, collision, or
  silent overwrite. [E2]
- Test the installed plugin-cache layout and fail when command and MCP stores
  diverge. [E4]

## Non-goals

- Rewriting canonical content or deciding duplicate-copy ownership. That waits
  for `canonical-writeback-contract`.
- Changing product schemas or inventing migration content.
- Using `CLAUDE_PLUGIN_DATA` as a second writable store after migration.
- Editing external instance repositories during this PRD program.

## Proposed approach

1. Define one registry-derived state root per instance. If `instance_q_dir` is
   set, use `<path>/<instance_q_dir>`. Otherwise use the preserved state
   directories below `<path>/<subtree_prefix>/q-system`; a standalone entry
   must supply an explicit state root. Canonical, `my-project`, memory, output,
   bus, marketing, sources, founder profile, enabled integrations, metrics DB,
   harvest DB, and system DB all derive from that root. Fleet-global voice and
   AUDHD data derive from `KIPI_FLEET_ROOT/global`. The registry remains
   `KIPI_FLEET_ROOT/instance-registry.json`. Missing or ambiguous mappings fail
   closed. [E1, E2]
2. Make one resolver the only production reader of those locations. Remove the
   direct legacy founder-profile read and route morning and MCP initialization
   through the resolver. [E3]
3. Package immutable runtime assets inside `plugins/kipi-core` with an explicit
   manifest and production startup loader. Include agents, templates,
   methodology, sources, and schedule templates. Validate every declared asset
   at startup. Writable data never resolves inside an installed cache. [E4]
4. Add a two-phase migration: inventory and hash the non-authoritative store,
   stop on conflicts, copy absent records, verify counts and hashes, then mark
   the old store read-only with a receipt. Preserve the source until backup and
   import verification pass.
5. Run the same contract against a temporary installed-cache layout. Start the
   command and MCP paths, assert identical roots, mutate one test record, and
   prove both readers observe it.

## Alternatives considered

- **Keep both stores and synchronize.** Rejected because synchronization keeps
  two writable authorities and cannot remove split-brain behavior.
- **Make plugin data authoritative.** Rejected because repository commands,
  backups, and instance ownership are already defined around `q-system`. [E1]
- **Resolve data relative to the plugin package.** Rejected because cache
  locations are installation artifacts, not instance identity. [E4]

## Scenarios

- **Morning plus MCP.** Morning writes a calibration under the active instance
  root; the MCP reads the same record and reports the same path.
- **Installed cache.** The plugin executes from a versioned cache while
  `KIPI_INSTANCE_ROOT` points at a fixture repo; all immutable assets exist and
  all writable state stays in the fixture.
- **Migration conflict.** The old and authoritative stores contain different
  values for one logical record; migration stops, reports both hashes, and
  changes neither copy.
- **Two-brain negative.** A fixture points command and MCP resolution at
  different roots; startup fails before any write.

## Resolved decisions

- **Registry-derived instance state is authoritative.** Rationale: the
  architecture says instance-owned locations vary and the registry records
  those variations. [E1]
- **Every current KipiPaths record class is mapped.** Rationale: leaving global
  voice, AUDHD, marketing, databases, sources, profile, or integration records
  behind would make the migration lossy. [E2]
- **Plugin data is migration input only.** Rationale: retaining it as writable
  state preserves the defect. [E2]
- **Assets and data use separate roots.** Rationale: immutable packaged
  resources and instance-owned writable records have different lifecycles.
- **Ambiguity fails closed.** Rationale: a guessed root can write valid data to
  the wrong authority.

## Risks and rollback

- A wrong root can redirect every runtime write. The resolver must validate
  required instance markers before use. Rollback restores the previous binary
  while the old plugin-data tree remains intact and read-only.
- Migration can overwrite newer truth. Hash conflicts stop before copy.
  Rollback removes only newly copied, receipt-listed files and restores the
  pre-migration backup.
- Packaging can omit an asset. The installed-cache contract enumerates the
  asset manifest and fails startup. Rollback returns to the prior package.

## Open questions

- Which command surface sets `KIPI_INSTANCE_ROOT` for sessions launched outside
  an instance repository?
- Is the fleet registry needed by any non-fleet MCP tool? If not, those tools
  should not receive `KIPI_FLEET_ROOT`.
- How long must the read-only migration source be retained after all hash,
  backup, export, and import receipts pass?

## Evidence

- **E1:** `ARCHITECTURE.md:29-61`, `ARCHITECTURE.md:86-92`.
- **E2:** `plugins/kipi-core/.mcp.json:4-9`;
  `plugins/kipi-core/kipi-mcp/src/kipi_mcp/paths.py:61-151`.
- **E3:** `plugins/kipi-core/kipi-mcp/src/kipi_mcp/server.py:57-167`;
  `plugins/kipi-core/kipi-mcp/src/kipi_mcp/morning_init.py:1-240`.
- **E4:** `plugins/kipi-core/kipi-mcp/src/kipi_mcp/paths.py:168-199`;
  command result `test -d q-system/.q-system/agent-pipeline` exited 0 and
  `test -d q-system/agent-pipeline` exited 1 on 2026-07-24.

## Issues

```json
[
  {
    "id": "srsa-authoritative-path-contract",
    "finding_id": "finding-1",
    "title": "Implement the authoritative instance and fleet path contract",
    "priority": "p0",
    "allowed_files": ["plugins/kipi-core/kipi-mcp/src/kipi_mcp/paths.py", "plugins/kipi-core/kipi-mcp/tests/test_paths.py"],
    "disallowed_files": ["q-system/canonical/**", "q-system/my-project/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_paths.py"],
    "required_reviews": ["runtime-owner"],
    "acceptance": "Write failing root-resolution and ambiguity tests first. Derive each instance state root from registry path, subtree_prefix, and instance_q_dir, require an explicit standalone mapping, and resolve fleet registry only from KIPI_FLEET_ROOT.",
    "bypass_check": "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_paths.py -k 'ambiguous or plugin_cache_write'"
  },
  {
    "id": "srsa-unified-readers",
    "finding_id": "finding-2",
    "title": "Route MCP, morning, backup, import, export, and validation through one resolver",
    "priority": "p0",
    "allowed_files": ["plugins/kipi-core/kipi-mcp/src/kipi_mcp/server.py", "plugins/kipi-core/kipi-mcp/src/kipi_mcp/morning_init.py", "plugins/kipi-core/kipi-mcp/tests/test_state_authority.py"],
    "disallowed_files": ["plugins/kipi-core/kipi-mcp/src/kipi_mcp/paths.py", "q-system/canonical/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_state_authority.py"],
    "required_reviews": ["runtime-owner"],
    "acceptance": "Write a failing shared-record contract test first. Every listed reader and writer must report and use the same resolved store, with no direct legacy repository read.",
    "bypass_check": "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_state_authority.py -k two_brain"
  },
  {
    "id": "srsa-packaged-asset-manifest",
    "finding_id": "finding-3",
    "title": "Package and validate immutable runtime assets",
    "priority": "p0",
    "allowed_files": ["plugins/kipi-core/kipi-mcp/pyproject.toml", "plugins/kipi-core/kipi-mcp/src/kipi_mcp/assets-manifest.json", "plugins/kipi-core/kipi-mcp/src/kipi_mcp/asset_loader.py", "plugins/kipi-core/kipi-mcp/src/kipi_mcp/assets/**", "plugins/kipi-core/kipi-mcp/sources/**", "plugins/kipi-core/kipi-mcp/tests/test_installed_assets.py"],
    "disallowed_files": ["q-system/canonical/**", "q-system/my-project/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_installed_assets.py"],
    "required_reviews": ["packaging-owner"],
    "acceptance": "Write a failing installed-cache asset test first. Enumerate agents, templates, methodology, sources, and schedule templates and fail startup if any declared asset is absent.",
    "bypass_check": "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_installed_assets.py -k missing_declared_asset"
  },
  {
    "id": "srsa-lossless-migration",
    "finding_id": "finding-4",
    "title": "Migrate non-authoritative plugin data without loss",
    "priority": "p0",
    "allowed_files": ["plugins/kipi-core/kipi-mcp/src/kipi_mcp/state_migration.py", "plugins/kipi-core/kipi-mcp/tests/test_state_migration.py"],
    "disallowed_files": ["q-system/canonical/**", "q-system/my-project/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_state_migration.py"],
    "required_reviews": ["data-owner"],
    "acceptance": "Write failing conflict and interrupted-copy tests first. Map canonical, project, memory, output, bus, marketing, sources, profile, integrations, three databases, global voice, and AUDHD records; inventory hashes, stop on conflicts, verify copies, preserve the source, and emit a rollback receipt.",
    "bypass_check": "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_state_migration.py -k 'conflict or interruption or rollback'"
  },
  {
    "id": "srsa-installed-two-brain-contract",
    "finding_id": "finding-5",
    "title": "Run installed-cache and two-brain negative contracts",
    "priority": "p0",
    "allowed_files": ["plugins/kipi-core/kipi-mcp/tests/test_installed_state_contract.py", "plugins/kipi-core/kipi-mcp/tests/fixtures/installed-cache/**"],
    "disallowed_files": ["plugins/kipi-core/kipi-mcp/src/**", "q-system/canonical/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_installed_state_contract.py"],
    "required_reviews": ["test-owner"],
    "acceptance": "Write the failing installed-layout reproducer first. Prove commands and MCP share one root and reject mismatched stores before a write.",
    "bypass_check": "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_installed_state_contract.py -k rejects_two_brain"
  },
  {
    "id": "srsa-registry-state-root-fixtures",
    "finding_id": "finding-6",
    "title": "Cover registry-derived state-root variants",
    "priority": "p0",
    "allowed_files": ["plugins/kipi-core/kipi-mcp/tests/test_registry_state_roots.py"],
    "disallowed_files": ["plugins/kipi-core/kipi-mcp/src/**", "q-system/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_registry_state_roots.py"],
    "required_reviews": ["runtime-owner"],
    "acceptance": "Write failing fixtures first for instance_q_dir, subtree fallback, null subtree, and missing explicit standalone state roots. Prove no writable path lands in a deletable generic directory.",
    "bypass_check": "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_registry_state_roots.py -k 'null_subtree or updater_delete'"
  },
  {
    "id": "srsa-complete-record-class-mapping",
    "finding_id": "finding-7",
    "title": "Verify every current KipiPaths record class migrates",
    "priority": "p0",
    "allowed_files": ["plugins/kipi-core/kipi-mcp/tests/test_record_class_migration.py"],
    "disallowed_files": ["plugins/kipi-core/kipi-mcp/src/**", "q-system/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_record_class_migration.py"],
    "required_reviews": ["data-owner"],
    "acceptance": "Write a failing enumeration test first. Introspect every KipiPaths writable record class and require a destination mapping, copied hash, and verification receipt.",
    "bypass_check": "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_record_class_migration.py -k unmapped_class"
  },
  {
    "id": "srsa-production-asset-loader",
    "finding_id": "finding-8",
    "title": "Wire the packaged asset manifest into production startup",
    "priority": "p0",
    "allowed_files": ["plugins/kipi-core/kipi-mcp/src/kipi_mcp/asset_loader.py", "plugins/kipi-core/kipi-mcp/src/kipi_mcp/server.py", "plugins/kipi-core/kipi-mcp/tests/test_asset_startup.py"],
    "disallowed_files": ["q-system/**", "instance-registry.json", ".prd-os/**", ".git/**"],
    "required_checks": ["python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_asset_startup.py"],
    "required_reviews": ["packaging-owner"],
    "acceptance": "Write a failing startup test first. Production startup must load the manifest, verify every packaged asset, and refuse missing or cache-external resources.",
    "bypass_check": "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_asset_startup.py -k missing_or_external"
  }
]
```
