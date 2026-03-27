# Kipi System Separation - Execution Plan

> Date: 2026-03-25
> Status: APPROVED - ready for execution
> Depends on: PHASE-0-AUDIT.md (reviewed and approved)

---

## Validation Harness

The `kipi_validate` MCP tool runs after every phase. It checks everything that should be true at that point. Validation is additive - Phase 2 checks include Phase 1 checks. If any check fails, STOP.

The harness is built FIRST, before any code changes. This way we're testing against known-good state before we break anything.

---

## Pre-Execution: Build the Harness

### Step 0.1: Create validation harness

The `kipi_validate` MCP tool takes a phase number argument and runs all checks up to that phase.

```
Use the `kipi_validate` MCP tool with phase=1   # Run Phase 1 checks
Use the `kipi_validate` MCP tool with phase=2   # Run Phase 1 + 2 checks
Use the `kipi_validate` MCP tool with phase=5   # Run all checks
```

### Step 0.2: Create `instance-registry.json`

Single source of truth for all instances:

```json
{
  "skeleton": {
    "path": "/Users/assafkip/Desktop/kipi-system",
    "remote": "https://github.com/assafkip/kipi-system.git"
  },
  "instances": [
    {
      "name": "KTLYST_strategy",
      "path": "/Users/assafkip/Desktop/KTLYST_strategy",
      "subtree_prefix": "q-system",
      "current_q_dir": "q-ktlyst",
      "has_git": true
    },
    {
      "name": "ktlyst",
      "path": "/Users/assafkip/Desktop/ktlyst",
      "subtree_prefix": "q-system",
      "current_q_dir": null,
      "has_git": true
    },
    {
      "name": "VC_Reachout",
      "path": "/Users/assafkip/Desktop/assafs_qs/VC_Reachout",
      "subtree_prefix": "q-system",
      "current_q_dir": "q-VC-Sourcing",
      "has_git": false
    },
    {
      "name": "car-research",
      "path": "/Users/assafkip/Desktop/car-research",
      "subtree_prefix": "q-system",
      "current_q_dir": "q-system",
      "has_git": true
    },
    {
      "name": "q-education",
      "path": "/Users/assafkip/Desktop/q-education",
      "subtree_prefix": "q-system",
      "current_q_dir": "q-system",
      "has_git": false
    },
    {
      "name": "Pure_spectrum_Q",
      "path": "/Users/assafkip/Desktop/Pure_spectrum_Q",
      "subtree_prefix": "q-system",
      "current_q_dir": ".q-system",
      "has_git": true
    },
    {
      "name": "q-investigate-osint-bot",
      "path": "/Users/assafkip/Desktop/q-investigate-osint-bot",
      "subtree_prefix": "q-system",
      "current_q_dir": ".q-system",
      "has_git": true
    }
  ],
  "eliminate": [
    {
      "name": "kipi-pipeline-plugin",
      "path": "/Users/assafkip/Desktop/kipi-pipeline-plugin"
    },
    {
      "name": "q-founder-os",
      "path": "/Users/assafkip/Desktop/q-founder-os"
    }
  ]
}
```

### Step 0.3: Snapshot current state

Before ANY changes, create a recovery snapshot:

```bash
# Tag current state in every git repo
# Create tar backup of non-git repos
```

**GATE 0: Harness runs clean against current state (no false failures)**

---

## Phase 1: Update the Skeleton

Goal: kipi-system becomes the canonical, comprehensive skeleton with all generic capabilities merged from KTLYST.

### Step 1.1: Reconcile agent files

Merge the two agent sets into one canonical set (~43+ agents).

**Process per agent:**
1. If agent exists in BOTH: merge KTLYST content into skeleton structure (keep frontmatter)
2. If agent exists ONLY in skeleton: keep as-is
3. If agent exists ONLY in KTLYST: port to skeleton, add frontmatter, strip KTLYST-specific content
4. For MIXED agents: extract domain-specific rules to `canonical/` references, keep generic pipeline logic

**Files to produce:** ~43 agent files in `q-system/.q-system/agent-pipeline/agents/`

**Validation checks (GATE 1.1):**
- [ ] Every agent file has valid YAML frontmatter (name, description, model)
- [ ] Every agent file has ## Reads and ## Writes sections
- [ ] Every agent file references `{{BUS_DIR}}` or `{{QROOT}}` (not hardcoded paths)
- [ ] No agent file contains "KTLYST", "ktlyst", "CISO", "re-breach", "threat intel", "CNS", or any KTLYST-specific terms
- [ ] No agent file contains hardcoded paths like `q-ktlyst/` or `/Users/assafkip/`
- [ ] Agent count >= 43
- [ ] `step-orchestrator.md` exists and references all agents
- [ ] `_cadence-config.yaml` exists (YAML format)
- [ ] `_scoring-config.md` exists
- [ ] `_auto-fail-checklist.md` exists

### Step 1.2: Port scripts from KTLYST

Scripts to port:
- `scan-draft.py` (anti-AI scanner)
- `verify-bus.py` (bus validation)
- `verify-orchestrator.py` (orchestrator validation)
- `build_schedule` MCP tool (JSON to HTML builder - replaces build-schedule.sh)

**Validation checks (GATE 1.2):**
- [ ] `scan-draft.py` exists and runs without error: `python3 scan-draft.py --help` or dry-run
- [ ] `verify-bus.py` exists and runs without error
- [ ] `verify-orchestrator.py` exists and runs without error
- [ ] `build_schedule` MCP tool is callable
- [ ] `verify-schedule.py` exists (already in skeleton)
- [ ] `audit-morning.py` exists (already in skeleton)
- [ ] No script contains hardcoded KTLYST paths or references

### Step 1.3: Update canonical templates

Ensure all canonical template files exist with proper structure but no instance content.

**Validation checks (GATE 1.3):**
- [ ] All canonical files exist: discovery.md, objections.md, talk-tracks.md, decisions.md, engagement-playbook.md, lead-lifecycle-rules.md, market-intelligence.md, mom-test-playbook.md, pricing-framework.md, verticals.md, content-intelligence.md
- [ ] All my-project files exist: founder-profile.md (with {{SETUP_NEEDED}}), current-state.md, relationships.md, competitive-landscape.md, progress.md, budget-qualifiers.md, lead-sources.md, notion-ids.md
- [ ] No canonical file contains KTLYST-specific content
- [ ] `founder-profile.md` contains `{{SETUP_NEEDED}}`

### Step 1.4: Update voice skill framework

Ensure the framework (structure) is in skeleton, content slots are empty templates.

**Validation checks (GATE 1.4):**
- [ ] `.claude/skills/founder-voice/SKILL.md` exists (framework)
- [ ] `.claude/skills/founder-voice/references/voice-dna.md` exists (empty template)
- [ ] `.claude/skills/founder-voice/references/writing-samples.md` exists (empty template)
- [ ] No voice file contains Assaf-specific content ("Assaf", "KTLYST", "threat intel")

### Step 1.5: Update CLAUDE.md template

Ensure skeleton CLAUDE.md uses `{{}}` placeholders for all instance-specific sections.

**Validation checks (GATE 1.5):**
- [ ] `CLAUDE.md` exists at root
- [ ] `q-system/CLAUDE.md` exists with full behavioral rules
- [ ] Both files use `@` imports correctly
- [ ] No CLAUDE.md contains KTLYST-specific content
- [ ] Anti-misclassification section uses `{{}}` placeholders
- [ ] Language rules section uses `{{}}` placeholders

### Step 1.6: Ensure build_schedule MCP tool works

The `build_schedule` MCP tool replaces the old build-schedule.sh script.

**Validation checks (GATE 1.6):**
- [ ] `build_schedule` MCP tool is callable
- [ ] Tool contains verification gate (calls verify-schedule.py)

### Step 1.7: Clean up

- Remove `q-founder-os` reference from any docs
- Update README.md if needed
- Ensure `.mcp.json` and `settings-template.json` are current

**Validation checks (GATE 1.7):**
- [ ] `README.md` has no KTLYST references
- [ ] `settings-template.json` has no hardcoded tokens
- [ ] `.mcp.json` uses `${ENV_VAR}` syntax only

### PHASE 1 GATE (all must pass)

```bash
Use the `kipi_validate` MCP tool with phase= 1
```

Checks:
- All GATE 1.1 through 1.7 checks pass
- `grep -r "KTLYST\|ktlyst\|q-ktlyst\|CISO\|re-breach\|threat.intel\|Assaf" q-system/` returns ZERO matches (excluding this plan file)
- `grep -r "/Users/assafkip" q-system/` returns ZERO matches
- Every `.md` file in `q-system/.q-system/agent-pipeline/agents/` has YAML frontmatter
- Every `.py` and `.sh` script is syntactically valid
- Git status shows only expected changes
- Commit with message "v2.0: Consolidated skeleton - all agents reconciled, scripts ported, templates updated"

**FOUNDER CHECKPOINT:** Review the skeleton. Confirm it's generic, comprehensive, and has no KTLYST leaks. Read 3-5 random agent files. Spot-check canonical templates.

---

## Phase 2: Restructure KTLYST_strategy as Subtree Consumer

Goal: KTLYST_strategy has kipi-system embedded as `q-system/` subtree, with all KTLYST-specific content in instance directories.

### Step 2.0: Backup

```bash
cd /Users/assafkip/Desktop/KTLYST_strategy
git stash  # if dirty
git tag pre-subtree-backup
```

**GATE 2.0:** Tag exists, working tree is clean.

### Step 2.1: Rename q-ktlyst to q-system

Move KTLYST's current q-dir to match the standard prefix.

**GATE 2.1:** `q-system/` exists in KTLYST_strategy. `q-ktlyst/` does not.

### Step 2.2: Separate instance content from skeleton content

Before adding the subtree, move KTLYST-specific files OUT of `q-system/` to instance-specific locations:

```
KTLYST_strategy/
  q-system/                     # Will become the subtree (skeleton only)
  instance/                     # KTLYST-specific content
    canonical/                  # KTLYST talk tracks, objections, CISO pains
    my-project/                 # Assaf profile, relationships, current-state
    marketing/
      assets/                   # KTLYST boilerplate, bios, stats
      content-themes.md         # 8 KTLYST themes
      editorial-calendar.md     # KTLYST cadence
    voice/                      # Assaf's voice DNA, writing samples
    seed-materials/             # 50+ debriefs
    output/                     # All generated content
  CLAUDE.md                     # Instance CLAUDE.md (extends skeleton)
```

**GATE 2.2:**
- [ ] `instance/canonical/` has KTLYST-specific canonical files
- [ ] `instance/my-project/` has KTLYST-specific project files
- [ ] `instance/voice/` has Assaf's voice files
- [ ] `q-system/canonical/` has only template files ({{}} placeholders)
- [ ] `q-system/my-project/founder-profile.md` contains `{{SETUP_NEEDED}}`
- [ ] No file in `q-system/` contains KTLYST-specific content

### Step 2.3: Replace q-system/ with subtree

```bash
rm -rf q-system/
git subtree add --prefix=q-system https://github.com/assafkip/kipi-system.git main --squash
```

**GATE 2.3:**
- [ ] `q-system/` contains the skeleton from kipi-system
- [ ] `git log --oneline q-system/` shows the squashed subtree commit
- [ ] `q-system/.q-system/agent-pipeline/agents/` has 43+ agent files

### Step 2.4: Create instance CLAUDE.md

The instance CLAUDE.md imports skeleton rules and adds KTLYST-specific sections.

**GATE 2.4:**
- [ ] Root `CLAUDE.md` contains `@q-system/CLAUDE.md`
- [ ] Root `CLAUDE.md` contains KTLYST identity section
- [ ] Root `CLAUDE.md` contains Three CISO Pains section
- [ ] Root `CLAUDE.md` contains anti-misclassification (populated, not {{}} placeholders)

### Step 2.5: Wire up instance content to skeleton agents

Agents read from `canonical/`, `my-project/`, etc. The skeleton agents use `{{QROOT}}` which resolves to the instance root. Instance canonical files must be accessible at the paths agents expect.

Options:
- (a) Symlink: `q-system/canonical/ -> ../instance/canonical/`
- (b) Agents read `{{INSTANCE_DIR}}/canonical/` directly
- (c) Keep instance canonical files AT `q-system/canonical/` (outside the subtree, git ignores them)

**Decision needed during execution.** Pick the simplest option that doesn't break `git subtree pull`.

**GATE 2.5:**
- [ ] A test agent can resolve its canonical file reads
- [ ] `{{QROOT}}/canonical/talk-tracks.md` resolves to KTLYST talk tracks
- [ ] `{{QROOT}}/my-project/relationships.md` resolves to KTLYST relationships

### Step 2.6: Move q-routines into instance

Ensure `/q-morning`, `/q-wrap`, `/q-debrief` work from KTLYST_strategy's own `.claude/commands/` or `.claude/skills/`.

**GATE 2.6:**
- [ ] `.claude/commands/` or `.claude/skills/` contains morning, wrap, debrief skills
- [ ] No dependency on kipi-pipeline-plugin
- [ ] Commands reference `q-system/` paths (not `q-ktlyst/`)

### Step 2.7: Functional test

Run a dry-run of the morning routine (or at minimum, the preflight + first 2 steps).

**GATE 2.7:**
- [ ] `python3 q-system/.q-system/audit-morning.py` runs without import errors
- [ ] `python3 q-system/.q-system/scripts/scan-draft.py --help` works
- [ ] `build_schedule` MCP tool responds without error
- [ ] Agent files are readable and parseable at expected paths

### PHASE 2 GATE

```bash
Use the `kipi_validate` MCP tool with phase= 2
```

All Phase 1 checks still pass (skeleton integrity preserved) PLUS:
- KTLYST_strategy has `q-system/` as a subtree
- Instance content is separated from skeleton
- No dependency on kipi-pipeline-plugin
- CLAUDE.md imports work
- Paths resolve correctly

**FOUNDER CHECKPOINT:** Open KTLYST_strategy in Claude Code. Run `/q-morning` preflight (Step 0 only). Confirm tools load, canonical files are found, voice files load.

---

## Phase 3: Eliminate the Plugin

Goal: kipi-pipeline-plugin is removed. Nothing depends on it.

### Step 3.1: Verify no remaining dependencies

```bash
# Search all instances for references to kipi-pipeline-plugin
grep -r "kipi-pipeline-plugin" /Users/assafkip/Desktop/*/
grep -r "kipi-pipeline-plugin" ~/.claude/
```

**GATE 3.1:** Zero matches.

### Step 3.2: Remove from Claude Code plugins

```bash
# Check if registered
cat ~/.claude/plugins.json 2>/dev/null || echo "no plugins.json"
```

Remove any reference.

**GATE 3.2:** `~/.claude/plugins.json` (if exists) has no kipi-pipeline-plugin entry.

### Step 3.3: Archive the plugin directory

```bash
mv /Users/assafkip/Desktop/kipi-pipeline-plugin /Users/assafkip/Desktop/_archived/kipi-pipeline-plugin
```

**GATE 3.3:** `/Users/assafkip/Desktop/kipi-pipeline-plugin` does not exist.

### Step 3.4: Archive q-founder-os

```bash
mv /Users/assafkip/Desktop/q-founder-os /Users/assafkip/Desktop/_archived/q-founder-os
```

**GATE 3.4:** `/Users/assafkip/Desktop/q-founder-os` does not exist.

### PHASE 3 GATE

```bash
Use the `kipi_validate` MCP tool with phase= 3
```

- Plugin directory gone
- q-founder-os directory gone
- No remaining references to either in any instance
- KTLYST still works (re-run Phase 2 functional test)

**FOUNDER CHECKPOINT:** Confirm comfortable with archival. Can restore from `_archived/` if needed.

---

## Phase 4: Update Other Instances

Goal: All 6 remaining instances are subtree consumers of kipi-system.

### Per-instance process (repeat for each):

#### Step 4.X.0: Backup
- If git: tag `pre-subtree-backup`
- If no git: `git init` first, commit current state, then tag

#### Step 4.X.1: Commit any dirty state
- Commit uncommitted changes so nothing is lost

#### Step 4.X.2: Separate instance content
- Move instance-specific files to `instance/` (or appropriate location)
- Keep only skeleton-compatible structure in what will become `q-system/`

#### Step 4.X.3: Add subtree
```bash
git subtree add --prefix=q-system https://github.com/assafkip/kipi-system.git main --squash
```

#### Step 4.X.4: Create instance CLAUDE.md
- Import skeleton with `@q-system/CLAUDE.md`
- Add instance-specific sections

#### Step 4.X.5: Wire instance content to skeleton paths

#### Step 4.X.6: Verify
- Agent files accessible
- CLAUDE.md imports resolve
- Scripts run without errors

### Instance-specific notes:

| Instance | Special Considerations |
|----------|----------------------|
| **ktlyst** (product) | Python product repo. Subtree adds founder OS capabilities. May only use marketing + voice, not full pipeline. |
| **VC_Reachout** | No git. Init first. Rename `q-VC-Sourcing/` content. Has its own methodology/ and scripts/. |
| **car-research** | Dirty state. Commit car-specific changes first. Car skills stay outside subtree. |
| **q-education** | No git. Init first. Lightweight - founder profile already populated. |
| **Pure_spectrum_Q** | Custom architecture. Subtree adds capabilities it can grow into. Keep existing `.q-system/commands.md` as instance override. |
| **q-investigate-osint-bot** | Self-contained OSINT system. Subtree adds marketing + voice it can optionally use. Keep existing tools/ and skills/. |

### PHASE 4 GATE

```bash
Use the `kipi_validate` MCP tool with phase= 4
```

For EACH of the 6 instances:
- [ ] `q-system/` directory exists
- [ ] `q-system/.q-system/agent-pipeline/agents/` has 43+ agent files
- [ ] `q-system/CLAUDE.md` matches skeleton version (content hash)
- [ ] Instance CLAUDE.md exists at root and contains `@q-system/`
- [ ] No instance has modified skeleton files (they're read-only from subtree)
- [ ] `git subtree pull` would succeed (test with `--dry-run` if available)
- [ ] Instance-specific content is outside the subtree prefix

**FOUNDER CHECKPOINT:** Open 2-3 instances in Claude Code. Verify they load without errors. Spot-check that canonical files are found.

---

## Phase 5: Propagation + Documentation

Goal: A working update mechanism and clear docs for creating new instances.

### Step 5.1: `kipi_update` MCP tool

Propagation tool that pulls skeleton updates to all registered instances.

```
Use the `kipi_update` MCP tool
# Reads instance-registry.json, runs git subtree pull for each
```

**GATE 5.1:**
- [ ] MCP tool is available and callable
- [ ] Tool reads `instance-registry.json`
- [ ] Dry run completes without errors
- [ ] Tool reports success/failure per instance

### Step 5.2: `kipi_new_instance` MCP tool

Tool to set up a new instance from scratch.

```
Use the `kipi_new_instance` MCP tool with path=<path> and name=<name>
# 1. Creates directory
# 2. git init
# 3. git subtree add kipi-system
# 4. Creates instance/ directory structure
# 5. Creates template CLAUDE.md
# 6. Registers in instance-registry.json
```

**GATE 5.2:**
- [ ] MCP tool is available and callable
- [ ] Running it creates a valid instance (test with a throwaway dir)
- [ ] New instance passes Phase 4 single-instance checks

### Step 5.3: `kipi_push_upstream` MCP tool

Tool to push generic improvements from an instance back to skeleton.

```
Use the `kipi_push_upstream` MCP tool
# Runs git subtree push from current instance to kipi-system
```

**GATE 5.3:**
- [ ] MCP tool is available and callable
- [ ] Includes safety check: warns if instance-specific content is in subtree prefix

### Step 5.4: Write documentation

- `SETUP.md` - How to create a new kipi instance (human-readable version of the script)
- `UPDATE.md` - How to pull skeleton updates
- `CONTRIBUTE.md` - How to push improvements back to skeleton
- `ARCHITECTURE.md` - How skeleton + instance layering works

**GATE 5.4:**
- [ ] All 4 docs exist
- [ ] Each doc has a "Quick Start" section with copy-paste commands
- [ ] No doc references KTLYST-specific content

### Step 5.5: Final verification sweep

Run the full harness one last time across everything.

### PHASE 5 GATE (FINAL)

```bash
Use the `kipi_validate` MCP tool with phase= 5
```

ALL previous phase checks PLUS:
- [ ] `kipi_update` MCP tool is callable
- [ ] `kipi_new_instance` MCP tool is callable
- [ ] `kipi_push_upstream` MCP tool is callable
- [ ] All 4 documentation files exist
- [ ] Every instance in `instance-registry.json` passes all checks
- [ ] kipi-system skeleton has zero instance-specific content
- [ ] kipi-pipeline-plugin is archived
- [ ] q-founder-os is archived

**FOUNDER CHECKPOINT:**
1. Use the `kipi_update` MCP tool to verify propagation works
2. Use the `kipi_new_instance` MCP tool to create a test instance, verify it works
3. Open KTLYST_strategy, run `/q-morning` (full run or first 3 steps)
4. Confirm everything is clean

---

## Execution Summary

| Phase | Steps | Key Output | Gate |
|-------|-------|------------|------|
| 0 (DONE) | Audit | PHASE-0-AUDIT.md | Founder reviewed |
| Pre | Build harness | kipi_validate MCP tool, instance-registry.json, snapshots | Harness runs clean |
| 1 | Update skeleton | 43+ agents, scripts, templates, CLAUDE.md | Zero KTLYST references in skeleton |
| 2 | KTLYST subtree | q-system/ subtree, instance/ content, wired paths | Morning preflight passes |
| 3 | Eliminate plugin | Archived plugin + q-founder-os | Zero references remain |
| 4 | Other instances | 6 subtree consumers | All instances load in Claude Code |
| 5 | Propagation | Update/create/push scripts, docs | Full sweep green |

## Abort Conditions

At ANY point, STOP if:
- A validation gate fails and can't be resolved in < 10 minutes
- Git state becomes confused (detached HEAD, merge conflicts in subtree)
- An instance loses data (files missing that existed before)
- The founder says stop

Recovery: every repo is tagged/backed up before changes. Restore with `git checkout pre-subtree-backup` or extract from `_archived/`.

## Token Budget Estimate

| Phase | Estimated Tool Calls | Notes |
|-------|---------------------|-------|
| Pre (harness) | 15-20 | Write 2 scripts, snapshot repos |
| Phase 1 | 80-120 | 43 agent files to reconcile, scripts to port |
| Phase 2 | 30-40 | File moves, subtree add, wiring |
| Phase 3 | 10-15 | Verify + archive |
| Phase 4 | 60-90 | 6 instances x 10 steps each |
| Phase 5 | 20-30 | Scripts + docs |
| **Total** | **215-315** | Multiple sessions likely needed |

**Recommended session splits:**
- Session 1: Pre + Phase 1 (build harness, update skeleton)
- Session 2: Phase 2 (KTLYST subtree - highest risk, needs focus)
- Session 3: Phase 3 + Phase 4 (plugin elimination + other instances)
- Session 4: Phase 5 (propagation + docs)
