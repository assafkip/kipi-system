---
description: End-of-task wiring gate — verify every change is connected end-to-end across kipi plugins, hooks, MCP tools, agents, bus files, canonical, and rules. Nothing dangling.
allowed-tools: Bash, Read, Grep, Glob
---

Run a Wiring Check on the work done in this session. Treat "this session" as the
current `git diff` against the default branch unless the founder specifies
otherwise (e.g., `since HEAD~3`, or a file list).

Goal: nothing disconnected, unused, unreachable, or half-integrated. If a file
was created or edited, prove it is reachable from something that already runs.

## Process (required, in order)

### 1. Enumerate changes
Run:
```bash
git diff --name-status origin/main...HEAD
git status --short
```
List every changed/created/deleted file. Group by kipi category (see matrix below).

### 2. Map to integration points
For each changed file, state the expected wiring based on its path. Use the
matrix below. If a file doesn't fit any category, call it out — it may be in
the wrong directory per `.claude/rules/folder-structure.md`.

### 3. Verify each wire
Use Grep/Glob/Read to prove the connection exists. No assumptions. If
verification requires running a script, run it.

### 4. Fix gaps, then re-verify
If a wire is missing, fix it. Do not leave a "TODO: wire this up" — that is the
exact failure mode this command exists to prevent.

### 5. Output WIRING REPORT
Structure:
- **Changes shipped** (file list, grouped by category)
- **Wiring evidence** (file + symbol/line for each connection)
- **Verification run** (commands executed + results, pass/fail)
- **Gaps found and fixed** (if any)
- **Exceptions** (rare; rationale + tracking reference)
- **Skeleton propagation status** — if this is the skeleton repo
  (`kipi-system`), confirm `kipi update --dry` would pick up these changes; if
  this is an instance repo, note whether the change belongs upstream in the
  skeleton

## Wiring Matrix (kipi-specific)

Check the wires that apply. Do not skip a category because "it looks obvious."

### New or edited skill (`plugins/*/skills/<name>/SKILL.md`)
- [ ] SKILL.md has frontmatter with `name`, `description`, `license`
- [ ] Skill directory is under a plugin that ships (kipi-core / kipi-ops / kipi-design / kipi-dsse / prd-os)
- [ ] Any references in the skill (scripts, refs/) exist at the stated paths
- [ ] If auto-invoked, the trigger rule exists in `.claude/rules/*-auto-invoke.md` OR the skill description contains a clear trigger pattern
- [ ] No duplicate skill name across plugin groups

### New or edited slash command (`plugins/*/commands/<name>.md`)
- [ ] Frontmatter has `description` and `allowed-tools`
- [ ] Command name is listed in the project CLAUDE.md commands section (if project-wide)
- [ ] Any scripts the command calls exist and are executable (`${CLAUDE_PLUGIN_ROOT}/scripts/...`)
- [ ] Any templates/rubrics the command references exist

### New or edited hook (`settings.json` hooks + hook scripts)
- [ ] Hook script is referenced from `.claude/settings.json` (or plugin hooks config)
- [ ] Script file exists, has `#!/usr/bin/env ...` shebang, and is `chmod +x`
- [ ] Script uses `set -euo pipefail` (bash) or explicit error handling (Python)
- [ ] Exit codes match the Claude Code hook contract (0 = ok, 2 = block with message)
- [ ] Cross-check `.claude/rules/token-discipline.md` for any existing guard behavior that could conflict

### New or edited MCP tool (kipi-core/kipi-mcp)
- [ ] Tool is registered in the MCP server's tool list
- [ ] Tool appears in the plugin description (so it's discoverable)
- [ ] Any resource URIs (`kipi://...`) are served by the same server
- [ ] Input schema is set; required params are marked

### New or edited agent (`.claude/agents/*.md` OR `q-system/.q-system/agent-pipeline/agents/*.md`)
- [ ] Frontmatter names a concrete model ID (per `memory/reference_agent_models.md` — do not use deprecated IDs)
- [ ] Tool allowlist is explicit
- [ ] For pipeline agents: input/output bus files match a schema in `agent-pipeline/schemas/`
- [ ] Orchestrator invokes the agent in the expected phase

### New or edited bus file / schema
- [ ] `_bus-envelope.schema.json` structure is respected
- [ ] Schema file exists at `agent-pipeline/schemas/<name>.schema.json`
- [ ] At least one producer writes it AND at least one consumer reads it
- [ ] `verify-bus.py` passes

### New or edited canonical file (`q-system/canonical/*.md`)
- [ ] Change is referenced in `ripple-graph.json`
- [ ] `canonical-digest.py` was re-run and the bridge digest is updated
- [ ] Council check fired (per `.claude/rules/auto-detection.md`) if >5 lines or new section

### New or edited rule (`.claude/rules/<name>.md`)
- [ ] Rule is auto-loaded (project-scoped rules in `.claude/rules/` load by convention) OR is imported via `@` in CLAUDE.md
- [ ] Rule name doesn't shadow an existing one
- [ ] If ENFORCED, the enforcement mechanism exists (hook, script, or explicit agent instruction)

### New or edited Python harness (`q-system/.q-system/*.py` or `scripts/*.py`)
- [ ] QROOT resolves to `q-system/` per folder-structure rule (`..` or `../..` depending on depth)
- [ ] At least one caller references it (command, hook, or another script)
- [ ] Runs clean on an empty/fresh instance (not just this founder's state)

### New or edited PRD / issue spec (`q-system/output/prd-*.md`, DSSE issues)
- [ ] PRD uses the template at `q-system/marketing/templates/prd.md`
- [ ] Mandatory wiring checklist section is filled
- [ ] If advancing state, `prd_runner.py` / DSSE scripts stamped the expected receipts

### Skeleton → instance propagation (when working in `kipi-system`)
- [ ] File is in a path `kipi-update.sh` copies (check the script's include list)
- [ ] If it's instance-specific (e.g., `my-project/`, `memory/`, `output/`), it is NOT being shipped to the skeleton
- [ ] Run `kipi update --dry` — the changed files should appear in the preview

## Standard verification commands

Run whichever apply:
```bash
python3 q-system/.q-system/verify-bus.py
python3 q-system/.q-system/verify-orchestrator.py
python3 q-system/.q-system/verify-schedule.py
python3 q-system/.q-system/scripts/instruction-budget-audit.py
python3 q-system/.q-system/scripts/ripple-verify.py
python3 validate-separation.py     # kipi check
kipi update --dry                   # skeleton propagation preview
```

## Anti-patterns — if you see these, fail the gate

- A new skill with no trigger path (rule, command, or clear auto-invoke description)
- A new hook script not referenced in any `settings.json`
- A new MCP tool not listed in the plugin description
- A new bus producer with no consumer (or vice versa)
- A new canonical file not in `ripple-graph.json`
- A new command not listed in the CLAUDE.md commands section
- `TODO: wire this up` or `# placeholder` introduced in this session
- Changes sitting in an instance repo that belong in the skeleton (or vice versa)

## Reporting rule

If the gate fails, say so plainly in the first line of the report. Do not bury
failures under green checkmarks. The founder needs to know at a glance whether
to ship or fix.
