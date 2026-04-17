# prd-os

Portable Claude Code plugin for PRD creation and PRD execution with Codex review as a formal gate.

## Status

Scaffold only. Version `0.1.0`. No commands, scripts, hooks, or templates are wired yet. Tracking tree is in place so later steps can drop logic into the right directories without further structural decisions.

## What this plugin will do (once built)

**PRD creation flow.** Turn a rough idea into a reviewable PRD, run it through `/codex:review` and `/codex:adversarial-review` as a formal gate, triage findings, approve, and decompose the approved PRD into atomic issue specs.

**Issue execution flow.** Start an issue in planning mode, require explicit approval to transition to in-progress, enforce scope on every edit, require verify + review + findings-triage receipts before closeout, clear runtime state cleanly.

## Package layout

```
plugins/prd-os/
├── .claude-plugin/plugin.json   # manifest (name, version, description, author)
├── README.md                    # this file
├── CHANGELOG.md                 # version history
├── commands/                    # slash commands (auto-discovered)
├── hooks/                       # hook registrations (hooks.json)
├── scripts/                     # runner scripts
├── templates/                   # PRD / issue / rubric / findings schema
├── tests/                       # workflow tests for the plugin itself
└── skills/prd-os/SKILL.md       # skill telling Claude how to use the system
```

## Portable core vs repo-local split

The plugin holds everything that should be identical across repos. The target repo holds everything that is project-specific: the actual PRD docs, the actual issue specs, the runtime state, and the path overrides.

### Lives in the plugin (portable, versioned via semver, installable)

| Thing | Why it belongs here |
|---|---|
| Commands (`/prd-*`, `/issue-*`) | Same workflow across every repo |
| Runner scripts (`prd_runner.py`, `issue_runner.py`, `prd_split.py`) | Deterministic logic, config-driven |
| Hooks (`scope-hook.py`, `stop-gate.py`) | Same enforcement contract everywhere |
| Templates (`prd.md`, `issue.md`, `review-rubric.md`) | Start-from shape; copied into repo on use |
| Findings schema (`findings.schema.json`) | Contract for PRD and issue review findings |
| Skill (`SKILL.md`) | How Claude Code uses the system |
| Tests (workflow-level) | Pin plugin behavior regardless of host repo |

### Lives in the repo (local, per-project)

| Thing | Why it belongs here |
|---|---|
| `.prd-os/config.json` | Maps portable commands to this repo's paths |
| `.prd-os/prds/<slug>.md` | The actual PRD content for this project |
| `.prd-os/issues/issue-N-slug.md` | Issue specs for this project |
| `.prd-os/findings/{prd,issue}/*.jsonl` | Review findings for this project |
| `.claude/state/active-{prd,issue}.json` | Runtime session state — must be gitignored |

### Config file (`.prd-os/config.json`) structure (planned)

Populated by `/prd-os-init` in the target repo. Fields include at minimum:

- `config_schema_version` — lets the plugin migrate older configs on load
- `prds_dir`, `issues_dir`, `findings_dir`, `state_dir` — path overrides
- `codex.base_ref`, `codex.review_mode` — Codex invocation defaults
- `control_plane_files` — additional files Claude may always edit (active spec is implicit)

This is **not yet implemented.** The schema lands in step 3 (port runner + config).

## Versioning

Semantic versioning. `MAJOR.MINOR.PATCH`.

| Bump | Meaning |
|---|---|
| PATCH | Bug fixes, doc edits, test additions. No behavior change that any repo depends on. |
| MINOR | Additive: new commands, new templates, new optional config keys, new tests. Existing repos keep working without changes. |
| MAJOR | Breaking: state-machine change, command removal, config-key removal, findings schema change. Requires repo-level action on upgrade. |

Pre-1.0 (`0.x.y`) signals scaffold-in-progress. Stability contract kicks in at `1.0.0`. Until then, treat MINOR bumps as potentially breaking and pin versions.

**Two independent version dimensions:**

1. **Plugin version** — in `.claude-plugin/plugin.json`. Bumped on every release.
2. **Config schema version** — in `.prd-os/config.json`. Bumped only when the runner cannot load older configs without migration. Most plugin releases leave this untouched.

`CHANGELOG.md` lists both when they change.

## Install (planned, not yet implemented)

Two install paths will be supported:

1. **Local plugin** (this repo): add `plugins/prd-os` to the local plugins directory. Already discoverable once hooks/commands are wired in later steps.
2. **Marketplace** (cross-repo): publish `plugins/prd-os` to a Claude Code marketplace (GitHub source). Other repos enable via `claude plugin install prd-os`.

Per-repo bootstrap happens via `/prd-os-init` (lands in step 8). That command creates `.prd-os/` in the target repo, writes `config.json` with defaults, adds the runtime state dir to `.gitignore`, and registers hooks in `.claude/settings.json` idempotently with a backup.

## Out of scope for the scaffold step

- No command files yet
- No runner scripts yet
- No hooks wired yet
- No templates yet
- No tests yet
- No changes to the host repo's `.claude/settings.json`
- No changes to existing `/issue-*` commands in `.claude/commands/`
- No changes to existing `q-ktlyst/.q-system/` runtime

Those land in steps 3-10 per the approved build order.

## Why plugin packaging over a copied directory

FAANG-style internal developer tools ship as versioned, installable packages with explicit upgrade paths. Claude Code's plugin system supports that directly: versioned manifest, auto-discovery of commands and skills, hook registration via `hooks.json` using `${CLAUDE_PLUGIN_ROOT}`, and marketplace distribution. A copied directory can't give us any of that without building it ourselves. The plugin model is the most practical path, not the fanciest.
