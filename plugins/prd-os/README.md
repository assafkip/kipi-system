# prd-os

Portable Claude Code plugin for PRD creation and PRD execution with Codex review as a formal gate.

## Status

Shipped and wired. The authoritative version is `.claude-plugin/plugin.json`; per-version history is in `CHANGELOG.md`. Commands live in `commands/`, runner scripts in `scripts/`, hooks in `hooks/hooks.json`, templates in `templates/`.

This line read "Version `0.1.0`, nothing wired yet" until 0.18.0, long after all of it shipped. Do not restate the version number here -- a second copy is a second thing to drift (ASK-402).

## What this plugin does

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
| Spillover ledger (`spillover.jsonl` + `prd_runner.py spillover …`) | Out-of-scope findings are captured + gated, never silently dropped |
| Hooks (`scope-hook.py`, `stop-gate.py`) | Same enforcement contract everywhere |
| Templates (`prd.md`, `issue.md`, `review-rubric.md`, `gap-classes.md`) | Start-from shape; copied into repo on use |
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

Per-repo bootstrap happens via `/prd-os-init`. That command creates `.prd-os/` in the target repo, writes `config.json` with defaults, and adds the runtime state dir to `.gitignore`.

It does NOT register hooks. Both this file and `SKILL.md` claimed it did, through 0.17.0, with no such code in `prd_os_init.py` -- the exact defect class this plugin exists to catch, surviving in the plugin's own docs (ASK-402). Hooks are wired by the plugin's `hooks/hooks.json`, which Claude Code loads when the plugin is enabled; nothing writes to a host repo's `.claude/settings.json`.

## Deliberately still out of scope

- No changes to the host repo's `.claude/settings.json`
- No changes to existing `/issue-*` commands in `.claude/commands/`

A five-item scaffold-era list used to sit here, asserting that no commands, no
runner scripts, no hooks, no templates and no tests existed yet. Every item was
false from roughly 0.5.0 onward and it survived to 0.18.0 because no test read
this file. `test_docs_do_not_carry_scaffold_era_text` now reads THIS file too,
not only `SKILL.md` (ASK-402).
- No changes to existing `q-ktlyst/.q-system/` runtime

Those land in steps 3-10 per the approved build order.

## Why plugin packaging over a copied directory

FAANG-style internal developer tools ship as versioned, installable packages with explicit upgrade paths. Claude Code's plugin system supports that directly: versioned manifest, auto-discovery of commands and skills, hook registration via `hooks.json` using `${CLAUDE_PLUGIN_ROOT}`, and marketplace distribution. A copied directory can't give us any of that without building it ourselves. The plugin model is the most practical path, not the fanciest.


## The spine contract (prd-os-spine-native, 2026-06-12)

Acceptance is a negative invariant, machine-enforced:

- **Manifest fields** — every issue entry carries `bypass_check` (the command
  proving no bypass remains) or an explicit `bypass_exempt: <reason>`;
  optional `invariant` (the statement) and `deletes` (regex list the issue
  must remove from tracked source). Approval refuses entries with neither.
- **Gate registry** — `.prd-os/gates.jsonl` (committed). Issue closeout
  auto-registers `bypass_check` BEFORE flipping status; a registration
  failure aborts the close. `prd_runner.py gates list|run` — run executes
  every registered gate from the repo root, red exits non-zero. The registry
  only grows; gates are forever.
- **Deletion rule** — closeout greps each `deletes` regex is GONE from
  tracked *.py/*.html (excluding tests/, .prd-os/, docs/, q-system/output/).
- **Phase gating** — PRD frontmatter `depends_on: <prd-id>`; activation
  (`load`) refuses while the dependency has any RED registered gate.
- **Umbrella PRDs** — `kind: umbrella` legalizes an empty manifest; accepted
  findings carry `covered_by: <phase-prd-id>` (verified to exist and be past
  `idea` at archive; replaces issue receipts for those findings).
- **Plan findings** — `findings_writer.py add --source plan` records the
  author's decomposition for manifest traceability WITHOUT stamping
  the review proof (which still requires a real independent reviewer pass:
  `codex-review`, `codex-adversarial`, `claude-review`, or
  `claude-adversarial`). The stamp records `reviewed_by: <source>` so the
  ledger names the reviewer that actually ran.
