---
id: prd-enforcement-instruction-contract-2026-07-24
title: Enforcement Instruction Contract
status: approved
created_at: 2026-07-24T21:15:00Z
updated_at: 2026-07-24T21:10:16Z
owner: senior-staff
reviewers: []
findings_path: .prd-os/findings/prd-enforcement-instruction-contract-2026-07-24-findings.jsonl
codex_reviewed_at: 2026-07-24T21:09:01Z
---

# Enforcement Instruction Contract

## Problem

`CONTRIBUTE.md` and `UPDATE.md` say `.githooks/pre-commit` and
`.githooks/pre-push` are active and fresh clones set `core.hooksPath`
[`CONTRIBUTE.md:3-12`, `CONTRIBUTE.md:31-39`, `UPDATE.md:16-22`]. The tracked
hooks exist, but `git config --get core.hooksPath` returned no value on
2026-07-24. `.git/hooks/pre-commit` is Lefthook-managed, no active pre-push
hook exists, and `lefthook.yml` defines only pre-commit commands
[`lefthook.yml:4-67`].

Updater commits bypass hooks with `--no-verify`
[`kipi-update.sh:95-99`, `kipi-update.sh:196`, `kipi-update.sh:287`].
The instruction audit defines a 300-line target
[`q-system/.q-system/scripts/instruction-budget-audit.py:4-18`]. Its
2026-07-24 run reported 17 always-on files and 513 lines, failing by 213.
Root `AGENTS.md` imports `q-system/AGENTS.md`, but `test -f
q-system/AGENTS.md` exited 1.

## Goals

- Make Lefthook the single local hook installation path.
- Make fresh-clone installation deterministic and verifiable.
- Restore a real pre-push contract in Lefthook, or replace the documented
  contract with equivalent executable proof.
- Make updater-created commits pass the same relevant gates without
  `--no-verify`.
- Reduce always-on instructions to 300 lines or fewer without losing
  executable protections.
- Create the correctly owned `q-system/AGENTS.md` import target and verify it.
- Compare documented enforcement against active configuration in tests.
- Keep prompt guidance separate from deterministic enforcement.

## Non-goals

- Weakening or deleting executable gates to hit the instruction budget.
- Treating comments or prompt text as enforcement.
- Changing product behavior outside hook, instruction, and updater commit
  contracts.
- Editing unrelated user or global Git configuration.

## Proposed approach

1. Declare Lefthook as the only installer. Fresh-clone setup runs
   `lefthook install`, verifies generated pre-commit and pre-push hooks, and
   refuses a conflicting `core.hooksPath`.
2. Port the tracked pre-push proof into `lefthook.yml` with deterministic
   commands. After behavior parity and documentation checks pass, retire the
   tracked `.githooks/` path and prove no second hook authority remains.
3. Depend on `fcu-hook-safe-commits` from
   `prd-fail-closed-fleet-updater-2026-07-24` for updater commit behavior. This
   PRD supplies the active Lefthook contract that issue must pass.
4. Classify instruction lines as always-on behavior, path-scoped guidance, or
   executable protection. Move path-specific guidance behind real imports and
   keep executable protections in scripts, hooks, tests, or validators.
5. Create `q-system/AGENTS.md` as the owner of q-system path guidance. Root
   `AGENTS.md` keeps the import. A fresh-clone test resolves every import.
6. Generate an enforcement inventory from docs, Lefthook config, installed
   hooks, settings, and executable scripts. Any documented gate missing from
   active config, or active gate missing from docs, fails.

## Alternatives considered

- **Use `.githooks` as the installer.** Rejected because the active checkout
  already uses Lefthook and its config is the executable source. [E1]
- **Document the current mismatch.** Rejected because docs cannot make an
  inactive hook enforce anything.
- **Delete instruction text until the audit passes.** Rejected because
  executable protections and required ownership must remain.

## Scenarios

- **Fresh clone.** Setup installs Lefthook, verifies pre-commit and pre-push,
  resolves all AGENTS imports, and passes the 300-line audit.
- **Updater commit.** A fixture introduces a blocked change. The updater invokes
  normal commit behavior and Lefthook rejects it.
- **Documentation drift.** A documented pre-push command is absent from
  `lefthook.yml`; the agreement test fails.
- **Prompt-only claim.** A rule says an action is blocked but no executable
  path enforces it; the inventory marks it guidance, not protection.

## Resolved decisions

- **Lefthook is the local hook authority.** Rationale: it is already installed
  in `.git/hooks` and has tracked configuration.
- **Pre-push remains executable.** Rationale: removing the contract without
  equivalent proof would reduce enforcement.
- **Instruction reduction preserves machinery.** Rationale: line count is not a
  reason to delete gates.
- **`q-system/AGENTS.md` owns q-system guidance.** Rationale: the root import
  already declares that boundary.
- **Hook work is serialized.** Rationale: pre-push behavior lands first,
  `.githooks` retires after parity, and fresh-clone installation validates the
  final Lefthook configuration.
- **Updater behavior stays in the P0 updater PRD.** Rationale:
  `fcu-hook-safe-commits` already owns the same implementation surface.

## Risks and rollback

- Lefthook installation can replace local hook files. The installer snapshots
  only targeted hook files and verifies generated content. Rollback restores
  those snapshots.
- A new pre-push gate can block legitimate pushes. Each command has a direct
  reproducer and documented failure output. Rollback disables only the faulty
  command after review.
- Instruction moves can hide required guidance. The import resolver and
  protection inventory compare before and after coverage.
- Updater commits can stop fleet updates when gates fail. The updater leaves a
  recoverable worktree and reports the gate failure.

## Open questions

- Which tracked `.githooks` behaviors are not represented in Lefthook and need
  a direct port before migration?
- Which always-on instruction sections can become path-scoped without changing
  when they apply?
- Should fresh-clone setup install Lefthook directly or call one repository
  bootstrap entrypoint that also runs validation?

## Evidence

- **E1:** `CONTRIBUTE.md:3-12`, `CONTRIBUTE.md:31-39`, `UPDATE.md:16-22`;
  `.githooks/pre-commit`, `.githooks/pre-push`, `lefthook.yml:4-67`.
- **E2:** Command results run 2026-07-24:
  `git config --get core.hooksPath` returned empty;
  `.git/hooks/pre-commit` is Lefthook-managed; no active pre-push exists.
- **E3:** `kipi-update.sh:95-99`, `kipi-update.sh:196`,
  `kipi-update.sh:287`.
- **E4:** `q-system/.q-system/scripts/instruction-budget-audit.py:4-18`;
  command result 513 of 300 lines, 17 always-on files, exit 1.
- **E5:** Root `AGENTS.md:1-3`; command result
  `test -f q-system/AGENTS.md` exited 1.

## Issues

```json
[
  {
    "id": "eic-lefthook-install",
    "finding_id": "finding-1",
    "title": "Make Lefthook the deterministic fresh-clone installer",
    "priority": "p1",
    "allowed_files": ["scripts/install-hooks", "lefthook.yml", "tests/test_hook_install.py"],
    "disallowed_files": [".git/hooks/**", ".githooks/**", "q-system/canonical/**", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q tests/test_hook_install.py"],
    "required_reviews": ["enforcement-owner"],
    "acceptance": "Write failing fresh-clone and conflicting-hooksPath tests first. Install and verify Lefthook pre-commit and pre-push without editing global Git config.",
    "bypass_check": "python3 -m pytest -q tests/test_hook_install.py -k 'fresh_clone or conflicting'"
  },
  {
    "id": "eic-pre-push-contract",
    "finding_id": "finding-2",
    "title": "Restore the pre-push enforcement contract in Lefthook",
    "priority": "p1",
    "allowed_files": ["lefthook.yml", "tests/test_pre_push_contract.py"],
    "disallowed_files": [".git/hooks/**", ".githooks/**", "q-system/canonical/**", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q tests/test_pre_push_contract.py"],
    "required_reviews": ["enforcement-owner"],
    "acceptance": "Write a failing missing-pre-push test first. Port every still-valid tracked pre-push proof or document and test an equivalent executable replacement.",
    "bypass_check": "python3 -m pytest -q tests/test_pre_push_contract.py -k documented_active_parity"
  },
  {
    "id": "eic-instruction-budget",
    "finding_id": "finding-4",
    "title": "Reduce always-on instructions to 300 lines without losing protections",
    "priority": "p1",
    "allowed_files": ["AGENTS.md", "CLAUDE.md", ".claude/rules/**", "q-system/.q-system/scripts/instruction-budget-audit.py", "q-system/.q-system/scripts/test/test-instruction-protection-parity.sh"],
    "disallowed_files": ["q-system/canonical/**", "lefthook.yml", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 q-system/.q-system/scripts/instruction-budget-audit.py", "bash q-system/.q-system/scripts/test/test-instruction-protection-parity.sh"],
    "required_reviews": ["instruction-owner", "enforcement-owner"],
    "acceptance": "Write a failing protection-parity fixture first. Reach 300 lines or fewer by scoping guidance while every executable protection remains represented and runnable.",
    "bypass_check": "bash q-system/.q-system/scripts/test/test-instruction-protection-parity.sh --assert-no-prompt-only-protection"
  },
  {
    "id": "eic-q-system-agents-owner",
    "finding_id": "finding-5",
    "title": "Create and verify the q-system AGENTS ownership boundary",
    "priority": "p1",
    "allowed_files": ["q-system/AGENTS.md", "tests/test_agents_imports.py"],
    "disallowed_files": ["AGENTS.md", "q-system/canonical/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q tests/test_agents_imports.py"],
    "required_reviews": ["instruction-owner"],
    "acceptance": "Write the failing missing-import test first. Put q-system path guidance in q-system/AGENTS.md and prove every repository import resolves in a fresh clone.",
    "bypass_check": "python3 -m pytest -q tests/test_agents_imports.py -k missing_import"
  },
  {
    "id": "eic-enforcement-agreement",
    "finding_id": "finding-6",
    "title": "Compare documented enforcement with active configuration",
    "priority": "p1",
    "allowed_files": ["scripts/enforcement-agreement.py", "tests/test_enforcement_agreement.py", "CONTRIBUTE.md", "UPDATE.md"],
    "disallowed_files": ["lefthook.yml", ".git/hooks/**", "q-system/canonical/**", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q tests/test_enforcement_agreement.py"],
    "required_reviews": ["enforcement-owner"],
    "acceptance": "Write failing documented-only, active-only, and prompt-only fixtures first. Compare docs, Lefthook, settings, installed hooks, and executable scripts.",
    "bypass_check": "python3 -m pytest -q tests/test_enforcement_agreement.py -k 'documented_only or active_only or prompt_only'"
  },
  {
    "id": "eic-retire-dot-githooks",
    "finding_id": "finding-8",
    "title": "Retire the competing tracked githooks path after parity",
    "priority": "p1",
    "allowed_files": [".githooks/pre-commit", ".githooks/pre-push", "tests/test_single_hook_authority.py"],
    "disallowed_files": ["lefthook.yml", ".git/hooks/**", "q-system/canonical/**", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q tests/test_single_hook_authority.py"],
    "required_reviews": ["enforcement-owner"],
    "acceptance": "Write a failing dual-authority test first. Require Lefthook behavior parity and documentation agreement before deleting tracked hook files, then prove no active or documented second path remains.",
    "bypass_check": "python3 -m pytest -q tests/test_single_hook_authority.py -k no_second_authority"
  },
  {
    "id": "eic-hook-issue-order",
    "finding_id": "finding-9",
    "title": "Enforce pre-push, retirement, then installer order",
    "priority": "p1",
    "allowed_files": ["tests/test_hook_issue_order.py"],
    "disallowed_files": ["lefthook.yml", ".githooks/**", ".git/hooks/**", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q tests/test_hook_issue_order.py"],
    "required_reviews": ["enforcement-owner"],
    "acceptance": "Write a failing out-of-order test first. Require pre-push parity before githooks retirement and both receipts before fresh-clone installer verification.",
    "bypass_check": "python3 -m pytest -q tests/test_hook_issue_order.py -k refuses_out_of_order"
  }
]
```
