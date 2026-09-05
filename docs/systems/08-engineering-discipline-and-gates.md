# 08. Engineering discipline and gates

Done means wired, tested and receipted, not written. This subsystem is the set of gates
that decide what counts as done: the PRD operating system with its findings and
spillover ledgers, the issue lifecycle with its scope and stop gates, the capability gate
that proves declared tests exist, the lints that refuse a document from claiming
enforcement it does not have, and the one verification script that runs identically as a
pre-commit hook and in CI.

## Components

```mermaid
flowchart TB
    subgraph prdos [prd-os plugin]
        PS[/prd-start /prd-map /prd-personas /prd-review /prd-triage /prd-approve /prd-split /prd-archive /prd-os-init]
        PR[prd_runner.py: new load status advance archive clear gates spillover add list check triage resolve]
        FW[findings ledger, receipts.jsonl, spillover.jsonl, gates.jsonl]
        FD[fable-discipline skill + fable-discipline-lint.py, PostToolUse]
    end
    subgraph dsse [kipi-dsse plugin]
        IS[/issue-start /issue-approve /issue-verify /issue-review /issue-closeout /issue-amend]
        SH[scope_hook.py, PreToolUse: edits only inside allowed_files]
        SG[stop_gate.py, Stop: no unrecorded issue state]
    end
    subgraph gates [Repo gates]
        CG[capability-gate.py + capability_manifest.py + fragments]
        ECL[enforced-claim-lint.py]
        POE[prompt-only-enforcement-guard.py]
        PL[plan-lint.py]
        IBA[instruction-budget-audit.py, ratchet]
        STS[settings-template-sync-check.py]
        WC[wiring-check.py + /wiring-check]
        RTL[reimplementing-test-lint.py, portability-lint.sh + portability-lint-hook.py, undefined-helper-lint.sh, plugin-version-bump-check.py, receipts-ledger-check.py, runtime-plugin-freshness.py]
    end
    V[verify.sh: THE floor, --staged in lefthook pre-commit, same script in CI validate]
    LH[lefthook.yml: verify, settings-template-sync, receipts-ledger, instruction-budget, plugin-version-bump, blocked-paths, gitleaks, large-files, enforced-claim; commit-msg: client-names-msg, linear-issue-ref]
    PS --> PR --> FW
    FD -.pairs.-> PR
    IS --> SH & SG
    CG & ECL & POE & PL & IBA & STS & WC & RTL --> V
    V --> LH
    LH --> CI[GitHub: validate, verify, reviewer-floor]
```

Four groups. The PRD operating system takes an idea through draft, review, triage,
approval, split into issues, and archive, refusing to advance while findings are pending
and refusing to archive while any accepted finding lacks a receipt; its execution
discipline layer is the fable-discipline skill and its lint. The issue lifecycle scopes an
agent's edits to the issue's allowed files and refuses to end a turn with unrecorded state.
The repo gates each hold one deterministic claim: declared tests exist and are green; a
document may only say ENFORCED when a script substantiates it; a plan has its five
sections; always-on instruction lines never grow; the two settings files agree; a new hook
or skill is reachable. All of them run through one floor script that the pre-commit hook
and continuous integration execute identically, so a commit that passes locally passes
there.

## Flow: a PRD to shipped code

```mermaid
stateDiagram-v2
    [*] --> draft: /prd-start (blocked while an issue is active)
    draft --> reviewing: /prd-review streams normalized findings to JSONL
    reviewing --> triaged: /prd-triage, every finding accepted / rejected / deferred
    triaged --> approved: /prd-approve (blocked by pending findings)
    approved --> split: /prd-split, one issue spec per manifest entry
    split --> issue_open: /issue-start loads a spec, snapshots allowed_files
    issue_open --> in_progress: /issue-approve
    in_progress --> verified: /issue-verify runs required_checks, records the receipt
    verified --> reviewed: /issue-review, Codex native + adversarial, scoped to allowed_files
    reviewed --> closed: /issue-closeout, per-finding dispositions; deferred auto-creates spillover
    closed --> archived: /prd-archive (blocked until every accepted finding has a receipt)
    archived --> [*]
    note right of closed: gates run stays RED while any spillover item is open; only fixed-and-closed or voided-with-reason clear it
```

Every transition is a command, and the commands refuse in the direction that matters:
forward while something is pending, and closing while something lacks a receipt. A deferred
finding is never terminal; it becomes a spillover item in both findings systems, and the
standing gate stays red until that item is resolved against a closed issue or voided with a
recorded reason. There is no third way to clear it.

## Every piece

prd-os
- Commands: `/prd-os-init`, `/prd-start`, `/prd-map`, `/prd-personas`, `/prd-review`, `/prd-triage`, `/prd-approve`, `/prd-split`, `/prd-archive`.
- `prd_runner.py`: the engine; `spillover add|list|check|triage|resolve` and `gates run` are the surfaces other work calls. Ledgers in `.prd-os/`.
- `accept-rate.py`: the disposition and receipt-coverage metric.
- `spillover-promote.py`: a confirmed finding becomes a fully scoped Linear issue; refuses without allowed files and acceptance.
- `spillover-ratchet.py` (PostToolUse): surfaces open items about a file at the moment someone edits it, once per file per day.
- `prd-os` skill: the method. `fable-discipline` skill: the execution discipline (recon before edit, verify against a copy with a negative self-test, single-writer chokepoints, scar-anchored why-comments); `fable-discipline-lint.py` enforces the deterministic slice, test isolation and deferral language without a capture; `export-fable-mirror.sh --check` keeps the public mirror in step.

kipi-dsse
- Commands: `/issue-start`, `/issue-approve`, `/issue-verify`, `/issue-review`, `/issue-closeout`, `/issue-amend`.
- `scope_hook.py` (PreToolUse): refuses Edit, Write and NotebookEdit outside the active issue's allowed files.
- `stop_gate.py` (Stop): refuses to end a turn with an unrecorded issue state.
- Kipi's judgment compiler (`kipi judgment`, ASK-363) freezes decision-time workflow context per triage decision.

Repo gates
- `capability-gate.py`, `capability_manifest.py`, `q-system/.q-system/capability/` (one fragment per declaration): declared versus actual; a test present but undeclared, or declared but absent, is red. `fleet-capability-verify.py` runs it in every instance. `capability-map-gen.py`, `capability-overlap.py`: structural maps and cross-repo overlap.
- `enforced-claim-lint.py`: a rule claiming ENFORCED must name an executable that exists, its config, and its test, in a JSON block; `--all` runs across every rule.
- `prompt-only-enforcement-guard.py`: blocks prose that pairs an enforcement verb with a prompt-only subject and names no executable within a five-line window.
- `plan-lint.py`: a plan under `output/plans/` needs the dated filename and five sections; plans before 2026-08-21 grandfathered.
- `instruction-budget-audit.py`: the always-on instruction line count, a ratchet against a baseline; 512 of a 300-line target at the time of writing, so it gates regression, not the absolute.
- `settings-template-sync-check.py`, `hook_envelope_audit.py`: page 03.
- `wiring-check.py` (PostToolUse, advisory) and the `/wiring-check` command: nesting, function length, debug leftovers, orphaned defs, hardcoded URLs; and the end-of-task gate that proves every change is reachable.
- `reimplementing-test-lint.py`: a test named for a script it never runs. `undefined-helper-lint.sh`: a helper called but never defined. `portability-lint.sh` and its hook: green locally, wrong where it runs. `plugin-version-bump-check.py`: a changed plugin bumps its version. `receipts-ledger-check.py`: the one JSONL allowed past the blocked-paths hook, gated on content. `runtime-plugin-freshness.py`: fails when the running plugin copy is older than the merged one. `ci-shaped-run.sh`: run a test the way CI runs it before pushing. `repo-preflight.sh`: whether an autonomous dispatcher may enter a repo.
- `verify.sh`: the floor; `--staged` in the pre-commit hook, identical in CI.
- `lefthook.yml`: pre-commit (verify, settings-template-sync, receipts-ledger, instruction-budget, plugin-version-bump, blocked-paths, gitleaks, large-files, enforced-claim) and commit-msg (client-names-msg, linear-issue-ref).
- `linear-issue-ref-check.py` (commit-msg): every commit names an issue or carries `[no-issue: reason]`, which is appended to a bypass ledger so bypasses stay countable.
- `prompt-audit-ledger.py`: renders the founder-readable checklist of dated instruction text.
- `conftest.py` (two copies): keeps standalone verifiers out of pytest collection.
- `consumer-parity-check.py` (PostToolUse, both settings files): a module that declares an exclusion predicate cannot gain a consumer that bypasses it; the rsync that builds a model and the walk that vets it must agree.
- `pr_verify.py`: runs a PR's tests and writes the green receipt the merge gate reads. `pr-restack.py`: merges origin/main into every open PR branch that has gone dirty and reports.
- `permission-ask-counter.py`: counts the turns that name a pick and then end by asking permission, the autonomy-contract rejection shape.
- `roadmap_scope.py`: the one deterministic classifier for product and roadmap scope, used by the `/improve` skill.
- `kipi-update-voiceloop-migrate.py`: migrates one instance from the `voicekit` package name to `voiceloop` before the updater rsyncs.

Rules that live on this page (every rule file, so a reader can find the one that fired)
- Always-on: `coding-standards.md`, `coding-audhd.md`, `security.md`, `token-discipline.md`, `wiring-check.md`, `no-orphan-findings.md`, `skill-hook-pairing.md`, `quick-plan.md`, `rca-mode.md`, `fable-discipline-auto-invoke.md`, `dev-skills-auto-invoke.md`, `model-allocation.md`, `folder-structure.md`, `linear-first.md`, `founder-notifications.md`, `automated-filer-marking.md`, `sycophancy-core.md`, `sycophancy.md`, `memory-freshness.md`, `memory-confidence.md`, `self-healing-retry.md`, `voice-enforcement.md`, `social-reaction-gate.md`, `design-auto-invoke.md`, `dogfood-gate.md`, `auto-detection.md`, `audhd-interaction.md`, `morning-pipeline.md`, `content-output.md`, `marketing-system.md`, `linkedin.md`, `anti-misclassification.md`, `md-hygiene.md`, `remote-coverage.md`, `repair-first-generation.md`.
- Paths-scoped (loaded only when a matching file is in play): `evidence-ledger.md`, `fable-escalation.md`, `loop-exits.md`, `concurrent-session-worktrees.md`, `instrument-discipline.md`, `voice-loop-anywhere.md`.
- Each rule that says ENFORCED carries a JSON block naming its executable, config and test; `enforced-claim-lint.py --all` holds that on every commit. `instruction-budget-audit.py` counts the always-on lines (512 against a 300 target) and ratchets against regression.

## Scars

- PR #259: `verify.sh` shipped with no caller. Result: wired in the pre-commit hook the same day, with the note that a floor nothing invokes is an aspiration.
- 2026-07-25: fourteen test files absent from the manifest flipped every instance's gate red after a sync. Result: one fragment per declaration, so branches never conflict on one array.
- 2026-08-21: 39 of 57 plans on disk lacked a section, and a gate red on its own population gets switched off. Result: grandfathering by date.
- ASK-132: `wiring-check.py` reports and never blocks, because a hard block would land on every code write across every instance; flipping it is a founder decision in the open.

## Retired

- The single-file `capability-manifest.json`: replaced by the fragment directory; the assembler refuses if both exist.
