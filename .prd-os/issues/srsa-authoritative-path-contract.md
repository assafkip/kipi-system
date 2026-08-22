---
id: srsa-authoritative-path-contract
title: Implement the authoritative instance and fleet path contract
status: open
priority: p0
parent_prd: prd-single-runtime-state-authority-2026-07-24
allowed_files:
  - plugins/kipi-core/kipi-mcp/src/kipi_mcp/paths.py
  - plugins/kipi-core/kipi-mcp/src/kipi_mcp/morning_init.py
  - plugins/kipi-core/kipi-mcp/src/kipi_mcp/validator.py
  - plugins/kipi-core/kipi-mcp/tests/test_paths.py
  - plugins/kipi-core/kipi-mcp/tests/test_backup.py
  - plugins/kipi-core/kipi-mcp/tests/test_morning_init.py
  - plugins/kipi-core/kipi-mcp/tests/test_validator.py
  - plugins/kipi-core/kipi-mcp/tests/test_bus_verifier.py
  - plugins/kipi-core/kipi-mcp/tests/conftest.py
  - plugins/kipi-core/.claude-plugin/plugin.json
disallowed_files:
  - q-system/canonical/**
  - q-system/my-project/**
  - q-system/.q-system/scripts/evidence_ledger.py
  - instance-registry.json
  - .prd-os/**
required_checks:
  - PYTHONPATH=plugins/kipi-core/kipi-mcp/src python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_paths.py
  - PYTHONPATH=plugins/kipi-core/kipi-mcp/src python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_paths.py plugins/kipi-core/kipi-mcp/tests/test_backup.py plugins/kipi-core/kipi-mcp/tests/test_morning_init.py plugins/kipi-core/kipi-mcp/tests/test_validator.py plugins/kipi-core/kipi-mcp/tests/test_bus_verifier.py
required_reviews:
  - runtime-owner
bypass_check: "PYTHONPATH=plugins/kipi-core/kipi-mcp/src python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_paths.py -k 'fails_closed or resolves_instance_domain_dir'"
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

## AMENDMENT 2026-08-22b (Sana) -- the spec's own checks could not run

Recorded here rather than via `/issue-amend` on purpose: `active-issue.json` is CLEARED
(issue_id null) and this spec still claimed `status: in-progress` with zero receipts and
no receipt chain behind commit 9d8d671e. Loading the issue only to amend it would have
put a live issue on the board mid-amendment. Status is set back to `open`, which is what
is actually true. Amend the loaded snapshot with `/issue-amend` at the next `issue-start`.

**1. bypass_check named no test that exists (sp-b82fda60, blocker).**
The selector was `-k 'ambiguous or plugin_cache_write'`. Neither name appears anywhere in
`plugins/kipi-core/kipi-mcp/tests/`. Measured:

    pytest ... -k 'ambiguous or plugin_cache_write'   -> rc=5  (no tests collected)

`issue_runner.py` `_close_preflight` calls `prd_runner.gate_register(..., command=bypass_check)`
at CLOSE and **never runs it**. So closing this issue as written would have written a
standing gate into `.prd-os/gates.jsonl` that exits 5 forever, and `gates run` is in this
repo's definition of done. Gates only grow; there is no hand-clear. Replaced with a
selector that collects 3 real cases and is RED today for the right reason:

    -k 'fails_closed or resolves_instance_domain_dir'  -> collects 3, rc=1 today

It goes green exactly when the resolver lands, which is what a bypass_check is for.
PROVE IT COLLECTS with `--collect-only` before closing. The runner will not.

**2. allowed_files was short (sp-aaef828d).** The spillover said "short by three"; the
measured set is larger. Files referencing `canonical_dir` / `my_project_dir` /
`tmp_kipi_paths`, counted 2026-08-22:

    src : paths.py, morning_init.py, validator.py, bus_verifier.py
    test: conftest.py(1) test_backup.py(19) test_bus_verifier.py(3)
          test_morning_init.py(49) test_paths.py(14) test_validator.py(1)

`tmp_kipi_paths` calls `ensure_dirs()`, so a fail-closed resolver reaches every one of
them. With the old 4-entry list the scope hook would have blocked those edits mid-build.
Widened above. `bus_verifier.py` is deliberately NOT added -- it is already being changed
under `crpr-bus-verifier-can-fail` and two issues must not both own one file.

**3. A second required_check pins the collateral.** The single-file check could go green
while the resolver broke the other suites. Baseline measured 2026-08-22 on the 5 in-scope
test files: **5 failed (this issue's reproducer), 91 passed**. The 91 is the number that
must not drop. Note `pytest tests/` as a whole is NOT usable as a check: 5 unrelated
modules fail collection on `ModuleNotFoundError: No module named 'yaml'`, pre-existing and
environmental, so a directory-wide check would be red for a reason this issue cannot fix.

**4. Reproducer status: red, and red for the right reason (sp-0cf100b3).**
Commit 9d8d671e claimed a red reproducer. It ERRORED AT COLLECTION, so none of the 5
cases ever ran. Three stacked defects, fixed in commit 63248474:
`PathContractError` imported but never defined (module-level ImportError = collection
error); `registry_fixture` defined nowhere, repointed at `tmp_registry_with_instances`;
and `test_ensure_dirs_never_creates_repo_owned_dirs` asserted a sentinel name nothing
creates, so it PASSED against unfixed code. Now: `--collect-only` prints 20 tests, and
5 fail on their own assertions. Do not re-verify by re-running only the file -- confirm
`--collect-only` first, every time.

## ARBITRATION 2026-08-22 (Sana): two p0 issues, one resolver (sp-36677c6f)

`crpr-one-canonical-resolver` builds a registry-backed fail-closed `instance_root()` in
`q-system/.q-system/scripts/evidence_ledger.py`. This issue builds one in
`plugins/kipi-core/kipi-mcp/src/kipi_mcp/paths.py`. The parent PRD decided "ONE resolver"
and that decision is not currently held by either spec.

**They cannot share an implementation as written.** `crpr-one-canonical-resolver` lists
`disallowed_files: plugins/**`; this issue touches only `plugins/`. The allowed_file sets
are mutually exclusive, so "just import the other one" is not available to either issue.

Three options, and why the pick:

- (a) `evidence_ledger.py` imports the resolver from `kipi_mcp.paths`. REJECTED. A
  `q-system/` script ships to 23 instances via `kipi update` rsync, while the plugin RUNS
  from the marketplace clone at `~/.claude/plugins/marketplaces/`. The import would
  resolve to the instance's synced `plugins/` copy, which is a different file from the one
  executing. That is the load-path scar exactly, and it would be correct in this repo and
  wrong in the deployed layout.
- (b) `kipi_mcp.paths` imports from `evidence_ledger.py`. REJECTED for the mirror reason:
  the MCP server has no `q-system/` on its path.
- (c) **PICKED. One CONTRACT, two thin call sites, one conformance test.** A single
  executable table of resolution cases (ambiguous two-domain-dir, resolved dir with no
  `canonical/`, registry disagreeing with the filesystem, unregistered repo) that BOTH
  implementations are run against by one test. Neither tree imports the other; drift
  between them is a test failure rather than a discovery months later.

(c) keeps the PRD's intent -- one behaviour, enforced -- without inventing an import that
crosses a deployment boundary. **Sequencing: this issue lands first** and owns the
contract table, because it owns the runtime path that `kipi_canonical_digest` actually
uses; `crpr-one-canonical-resolver` then conforms to the table rather than authoring a
second one. The conformance test is a deliverable of whichever issue lands SECOND, so it
cannot be written against only one implementation.

**Duplicate fixtures:** `srsa-registry-state-root-fixtures` claims ownership of the
`instance_q_dir` / subtree-fallback fixtures that this issue's reproducer already wrote
into `conftest.py` (`registry_with_domain_dir`) and `test_paths.py`. Those fixtures are
SHIPPED as of commit 63248474. `srsa-registry-state-root-fixtures` must not re-author
them; its remaining scope is whatever it needs beyond `registry_with_domain_dir`, and if
that is nothing it should be closed as delivered-by this issue rather than worked.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Implement the authoritative instance and fleet path contract
