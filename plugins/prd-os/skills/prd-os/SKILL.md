---
name: prd-os
description: PRD creation and PRD execution operating system. Use when the founder asks to turn a rough idea into a PRD, run a Codex review on a PRD or issue, decompose an approved PRD into issue specs, or execute an issue with scope enforcement and receipt-based closeout. Not for general product ideation or casual drafting; this is the formal gated workflow.
---

# prd-os

Formal, repo-native workflow for PRD creation and PRD execution inside Claude Code. An independent reviewer is the gate at both phases: Codex, or a Claude senior-staff-engineer subagent when Codex is unavailable.

Whichever reviewer ran is recorded in the findings ledger as `codex-review`, `codex-adversarial`, `claude-review`, or `claude-adversarial`. Stamping one for another puts false provenance in a repo whose thesis is receipts. Enforcement is partial and the boundary matters: the `REVIEWER_SOURCES` validator in `findings_writer.py` refuses any value outside that set (so `manual` and `plan` cannot fill a review gate), but no checker can tell which of the four actually ran. That last step is a model decision with no gate behind it.

## Status

Operational. Plugin version is authoritative in `.claude-plugin/plugin.json`; the state machines, commands, and gates below are shipped and enforced by the runner scripts. `CHANGELOG.md` carries the per-version history.

## State machines

PRD: `idea -> draft -> in-review -> draft (on revise) -> approved -> archived`.

Issue: `open -> in-progress -> closed`. Receipts required between approve and close: `verified`, `reviewed`, `findings_triaged`.

## Commands

PRD side (this plugin): `/prd-start`, `/prd-review`, `/prd-triage`, `/prd-approve`, `/prd-split`, `/prd-archive`, `/prd-personas`, `/prd-map`.

There is no `/prd-revise` command. A PRD returns to `draft` via `prd_runner.py advance draft` after triage.

Issue side ships in the **`kipi-dsse` plugin**, not this one: `/issue-start <id>`, `/issue-approve`, `/issue-verify`, `/issue-review`, `/issue-closeout`, `/issue-amend`. The two plugins share the `.prd-os/` state directory and the findings ledger.

Bootstrap: `/prd-os-init` (runs once per repo to scaffold `.prd-os/`, write `config.json`, and add the runtime state dir to `.gitignore`). It does NOT register hooks -- that claim shipped through 0.17.0 with no code behind it (ASK-402). Hooks come from this plugin's `hooks/hooks.json` when the plugin is enabled.

Ledger CLI (no slash command; run through `kipi judgment <subcommand>`): the Judgment Compiler freezes decision-time workflow context for each triage decision into an append-only hash-chained receipt ledger. See `scripts/judgment_compiler.py` and the operator guide.

## Non-negotiables

- PRD drafting must not drift into implementation. Scope enforcement restricts edits to the PRD file during drafting.
- Issue planning stays in `open` status. The stop-gate does not arm until `/issue-approve` transitions to `in-progress`.
- Empty `allowed_files` means deny-all except the active spec itself (control-plane carve-out). This is a fixed contract; do not propose allow-all behavior.
- Every finding gets a disposition before approve or closeout. The enum is exactly `pending`, `accepted`, `rejected`, `deferred` (`DISPOSITIONS` in `findings_writer.py`); the writer refuses anything else. No finding may be left `pending`. `rejected` and `deferred` require `--rationale`.
- Concurrent PRD and issue contexts are blocked. `/prd-start` refuses if an issue is `in-progress`; `/issue-start` refuses if a PRD is `in-review`.
- The reviewer never edits. Claude is the sole editor. Codex runs through `/codex:review` and `/codex:adversarial-review` and returns findings for Claude to triage; a Claude reviewer subagent runs read-only under the same contract.
- Runtime state (`.claude/state/active-{prd,issue}.json`) is never committed. The bootstrap command adds the state directory to `.gitignore`.
- Out-of-scope findings are never dropped. A `deferred` disposition auto-creates an open spillover item, and `gates run` stays red until it is resolved. See Spillover below.

## Spillover: out-of-scope findings never vanish

An issue found mid-work that is out of scope must be CAPTURED, not mentioned. The
ledger is `.prd-os/spillover.jsonl`; the standing gate enforces it.

- Capture: `prd_runner.py spillover add --source <id> --desc "..."` (a `deferred`
  triage disposition does this automatically; `rejected` does not).
- Gate: `prd_runner.py gates run` FAILS while any item is `open` — the same
  no-bypass re-proof as the registered gates. Forgetting an item = a red gate.
- Resolve: `spillover resolve <id> --resolution-ref <closed-issue-id>` (refuses
  unless that issue is actually closed) or `--void "<reason>"` for a non-item.
- Report: closeout/archive name each item, its resolving issue, the fix, and the
  system impact. See the `.claude/rules/no-orphan-findings.md` rule.

## Portable core vs repo-local split

Plugin (portable): commands, runner scripts, hooks, templates, review rubric, findings schema, tests.

Repo (local): `.prd-os/config.json`, `.prd-os/prds/`, `.prd-os/issues/`, `.prd-os/findings/`, `.claude/state/`.

Ledger files (`spillover.jsonl`, `gates.jsonl`, `judgments.jsonl`) resolve to the shared worktree ledger root, so parallel worktrees write to one ledger rather than diverging copies.

## Execution discipline

`fable-discipline` is this plugin's execution-discipline layer (recon before edit, verify against a copy with a negative self-test, single-writer chokepoints, scar-anchored why-comments). `/issue-start` loads it for PRD/DSSE work; the `fable-discipline-auto-invoke` rule loads it for everything else. Its deterministic slice (test isolation) is enforced by the `fable-discipline-lint` hook in this plugin's `hooks.json`.

## Load-path warning

These commands run from the marketplace clone (`~/.claude/plugins/marketplaces/<mp>/`), not from a project's `plugins/` directory. An edit to a project copy is inert until the clone is refreshed. Confirm which copy is live before relying on a change to command or skill text.

## Upgrade policy

Plugin follows semver. MAJOR bumps may change the state machine, remove commands, or change the findings schema; they require operator action. MINOR bumps are additive. PATCH bumps are fixes. Config schema version is tracked separately in `.prd-os/config.json` and bumps only when the runner cannot load older configs without migration. See `CHANGELOG.md`.
