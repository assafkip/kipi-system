---
name: prd-os
description: PRD creation and PRD execution operating system. Use when the founder asks to turn a rough idea into a PRD, run a Codex review on a PRD or issue, decompose an approved PRD into issue specs, or execute an issue with scope enforcement and receipt-based closeout. Not for general product ideation or casual drafting; this is the formal gated workflow.
---

# prd-os

Formal, repo-native workflow for PRD creation and PRD execution inside Claude Code. Codex is the review gate at both phases.

## Status

Scaffold only at plugin version `0.1.0`. This skill describes the target system so Claude knows what is coming; the implementation lands in later steps. Until the commands and runner scripts ship, do not claim the workflow is operational.

## State machines

PRD: `idea -> draft -> in-review -> draft (on revise) -> approved -> archived`.

Issue: `open -> in-progress -> closed`. Receipts required between approve and close: `verified`, `reviewed`, `findings_triaged`.

## Commands (once wired)

PRD side: `/prd-start`, `/prd-review`, `/prd-revise`, `/prd-approve`, `/prd-split`.

Issue side: `/issue-start <id>`, `/issue-approve`, `/issue-verify`, `/issue-review`, `/issue-closeout`.

Bootstrap: `/prd-os-init` (runs once per repo to scaffold `.prd-os/` and register hooks).

## Non-negotiables

- PRD drafting must not drift into implementation. Scope enforcement restricts edits to the PRD file during drafting.
- Issue planning stays in `open` status. The stop-gate does not arm until `/issue-approve` transitions to `in-progress`.
- Empty `allowed_files` means deny-all except the active spec itself (control-plane carve-out). This is a fixed contract; do not propose allow-all behavior.
- Every Codex finding gets a disposition before approve or closeout. The dispositions are `must-fix`, `optional`, `deferred`, or `rejected-with-reason`. No finding may be left unset.
- Concurrent PRD and issue contexts are blocked. `/prd-start` refuses if an issue is `in-progress`; `/issue-start` refuses if a PRD is `in-review`.
- Codex never edits. Claude is the sole editor. Codex runs through `/codex:review` and `/codex:adversarial-review` and returns findings for Claude to triage.
- Runtime state (`.claude/state/active-{prd,issue}.json`) is never committed. The bootstrap command adds the state directory to `.gitignore`.

## Portable core vs repo-local split

Plugin (portable): commands, runner scripts, hooks, templates, review rubric, findings schema, tests.

Repo (local): `.prd-os/config.json`, `.prd-os/prds/`, `.prd-os/issues/`, `.prd-os/findings/`, `.claude/state/`.

## What to do right now (pre-implementation)

The plugin is not yet wired. If the founder asks to run `/prd-start`, `/prd-review`, or any `/prd-*` command, say explicitly that the command does not exist yet and point to the current build step in `CHANGELOG.md`. Do not simulate the workflow with ad-hoc markdown.

For issue execution, continue using the existing `.claude/commands/issue-*.md` commands until the plugin-scoped replacements land and are proven in parallel.

## Upgrade policy

Plugin follows semver. MAJOR bumps may change the state machine, remove commands, or change the findings schema; they require operator action. MINOR bumps are additive. PATCH bumps are fixes. Config schema version is tracked separately in `.prd-os/config.json` and bumps only when the runner cannot load older configs without migration. See `CHANGELOG.md`.
