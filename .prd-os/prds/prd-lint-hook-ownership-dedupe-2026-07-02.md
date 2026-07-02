---
id: prd-lint-hook-ownership-dedupe-2026-07-02
title: Lint Hook Ownership Dedupe
status: archived
created_at: 2026-07-02T19:34:21Z
updated_at: 2026-07-02T19:44:47Z
owner: assafkipnis
reviewers: []
findings_path: .prd-os/findings/prd-lint-hook-ownership-dedupe-2026-07-02-findings.jsonl
codex_reviewed_at: 2026-07-02T19:36:17Z
---

# Lint Hook Ownership Dedupe

## Problem

`plugins/kipi-core/hooks/hooks.json` wires six lint hooks against
`$CLAUDE_PROJECT_DIR/q-system` scripts (voice-lint, voice-substance-lint,
headline-lint, audhd-lint, linkedin-format-lint,
prompt-only-enforcement-guard) — the same six that `settings-template.json`
regenerates into every instance's `.claude/settings.json` on `kipi update`.
Any instance with kipi-core enabled therefore runs each lint TWICE per
Edit/Write: doubled hook latency on every edit, and a blocking lint (exit 2)
surfaces its message twice. Found in the hooks review 2026-07-02; recorded as
spillover sp-700047ff.

## Goals

- Each of the six lints fires exactly once per Edit/Write in an instance with
  kipi-core enabled.
- One owner for the wiring of q-system-shipped lint scripts: the settings
  template (the scripts and the template travel together via `kipi update`).
- A regression test pins the ownership boundary — a plugin's hooks.json may
  only invoke scripts the plugin itself ships — so the double-wiring cannot
  return.

## Non-goals

- Changing any lint script's behavior or scope.
- Touching kipi-core's plugin-shipped hooks (rca-lint, fable-discipline-lint,
  rca-notify) — those are correctly owned by the plugin.
- Auditing other plugins' hook contents beyond the ownership assertion.
- Retro-cleaning instances' current settings.json (the merge regenerates hook
  wiring from the template on next `kipi update`; the plugin side stops firing
  when the marketplace/plugin copy updates).

## Proposed approach

Remove the six `$CLAUDE_PROJECT_DIR/...` hook entries from
`plugins/kipi-core/hooks/hooks.json`, keeping only `${CLAUDE_PLUGIN_ROOT}`
entries (rca-lint, fable-discipline-lint on Edit|Write|MultiEdit; rca-notify
on Bash). Add regression test
`q-system/.q-system/scripts/test/test-plugin-hook-ownership.sh`: parse every
`plugins/*/hooks/hooks.json` (json-aware) and FAIL if any hook command
references a `CLAUDE_PROJECT_DIR` path under `q-system/` (matches `${...}` and
bare variable forms; the raw command string is scanned, so wrappers and
`bash -c` forms cannot hide a reference). Scope is deliberately narrower than
"any CLAUDE_PROJECT_DIR use" (Codex finding-2): only the q-system tree is
kipi-update-propagated, so only those references belong to the template.
Reproducer-first: the test is shown red against the current hooks.json before
the removal.

## Alternatives considered

- **Remove the six from settings-template.json instead (plugin owns them).**
  Rejected: the lint scripts live in `q-system/.q-system/scripts/`, shipped by
  `kipi update` together with the template; kipi-core is also installed in
  non-kipi projects where those paths do not exist (the `test -f` guard makes
  each hook a silent no-op there, pure overhead). Ownership follows shipping.
- **Keep both, make the lints self-dedupe (lockfile per tool-call).**
  Rejected: adds state and failure modes to 6 scripts to preserve a wiring
  mistake.

## Scenarios

- **Instance edit.** Founder edits a draft in an instance with kipi-core;
  PostToolUse fires voice-lint once (settings.json wiring); the plugin
  contributes only rca-lint + fable-discipline-lint. One block message per
  violation.
- **Non-kipi project with kipi-core.** Standalone user installs kipi-core;
  plugin hooks reference only CLAUDE_PLUGIN_ROOT scripts, all of which exist —
  no dead `$CLAUDE_PROJECT_DIR/q-system` probes on every edit.
- **Future plugin edit.** Someone re-adds a q-system wiring to a plugin
  hooks.json; `test-plugin-hook-ownership.sh` (standing gate) goes red.

## Resolved decisions

- **Template owns q-system lint wirings.** Decided: remove from plugin.
  Rationale: scripts and template propagate together via `kipi update`; a
  plugin reaching into the host project's scripts is a layering violation.

## Risks and rollback

- Blast radius: one plugin hooks.json + one new test. Instances keep the
  settings.json wiring, so lint coverage never drops; the change only removes
  the duplicate firing path.
- Propagation lag: running sessions and stale plugin caches keep the old
  hooks.json until the marketplace clone / plugin version updates. During the
  lag the status quo (double fire) persists — no new failure mode.
- Rollback: restore the six entries in kipi-core/hooks/hooks.json; the
  ownership test goes red, which is the alarm working.

## Open questions

- None. The ownership call is settled in Resolved decisions.

## Persona Review

### Skeptic

Q1: What is the strongest argument against doing this?
A1: The plugin wiring is a belt-and-suspenders backstop if an instance's
settings.json loses the lints. But the settings-template-sync-check and the
merge tests already guard that path deterministically; redundancy here costs
every edit, every day.

Q2: What is the smallest experiment that would disprove the thesis?
A2: Enable kipi-core in an instance, edit a file violating voice-lint, count
block messages. Two today; must be one after.

Q3: What is the cheapest non-build alternative?
A3: Do nothing — the lints are idempotent so correctness holds. Rejected
because doubled latency on every Edit/Write fleet-wide is a permanent tax, and
the layering violation invites future divergence (two copies to update).

## Issues

<!--
After review and approval, populate the fenced JSON block below. The manifest is
read by TWO consumers and every entry must satisfy both:
  - `prd_split.py` materializes one issue spec per entry (needs `id`).
  - the approval gate proves every ACCEPTED finding is covered by an entry (needs
    `finding_id` + a `bypass_check`). One entry per accepted finding.

Required keys per entry (spine-native -- both consumers):
  - id (kebab-case, unique across the repo)            -- prd_split.py
  - finding_id (the accepted finding it covers, e.g. "finding-1") -- approval gate
  - title (non-empty string)
  - allowed_files (non-empty list of glob patterns)
  - required_checks (non-empty list, e.g. ["pytest -q"]). The stop-gate checks
    three receipts (verified, reviewed, findings_triaged); they are meaningless
    unless the spec documents what must be verified, so an empty list is rejected.
  - bypass_check (a command proving no bypass remains) OR
    bypass_exempt: "<reason>"                          -- spine contract

Optional keys:
  - priority (default p1)
  - disallowed_files, required_reviews, acceptance

Authoring a manifest with `id` but no `finding_id` (the pre-spine shape) is
rejected at approve. The template-vs-runner contract test enforces this list.
-->

```json
[
  {
    "id": "lint-hook-ownership-dedupe",
    "finding_id": "finding-2",
    "title": "Remove kipi-core's six q-system lint wirings; ownership test bans CLAUDE_PROJECT_DIR q-system references in plugin hooks (sp-700047ff)",
    "allowed_files": [
      "plugins/kipi-core/hooks/hooks.json",
      "plugins/kipi-core/.claude-plugin/plugin.json",
      "q-system/.q-system/scripts/test/test-plugin-hook-ownership.sh"
    ],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-plugin-hook-ownership.sh"
    ],
    "bypass_check": "bash q-system/.q-system/scripts/test/test-plugin-hook-ownership.sh",
    "priority": "p2",
    "acceptance": "kipi-core/hooks/hooks.json contains only CLAUDE_PLUGIN_ROOT hook commands (rca-lint + fable-discipline-lint on Edit|Write|MultiEdit, rca-notify on Bash). The ownership test parses every plugins/*/hooks/hooks.json json-aware and fails on any hook command referencing a CLAUDE_PROJECT_DIR path under q-system/ (covering ${} and bare variable forms via raw-string scan); it was shown failing against the pre-fix hooks.json (negative self-test) and passes after."
  }
]
```
