# Kipi System Architecture

## Overview

Kipi is a portable founder operating system that runs inside Claude Code. It uses a skeleton + instance architecture where generic capabilities live in a shared skeleton and project-specific content lives in each instance.

## Skeleton (kipi-system)

The skeleton contains everything that's generic across all instances:

- **Agent pipeline**: 50 agent prompt files for the morning routine, content pipeline, engagement, lead sourcing, etc.
- **Scripts**: Audit harness, anti-AI scanner, bus verification, schedule builder, orchestrator validator
- **Canonical templates**: Empty `{{}}` placeholder files for positioning, objections, talk tracks, etc.
- **Marketing templates**: Channel structure, guardrails framework, review pipeline
- **Voice skill framework**: Layer loading matrix, anti-AI rules, quality checks (no actual voice content)
- **CLAUDE.md**: Behavioral rules, operating modes, memory architecture, setup wizard
- **Validation harness**: the `kipi_validate` MCP tool verifies skeleton integrity and instance health

The skeleton lives at `https://github.com/assafkip/kipi-system.git`.

## Instances

Each instance is a project that embeds the skeleton as a git subtree at `q-system/`. Instances add:

- **Instance CLAUDE.md**: Imports skeleton rules via `@q-system/q-system/CLAUDE.md`, adds project-specific identity and rules
- **Populated canonical files**: Real positioning, objections, talk tracks for the specific project
- **my-project/ data**: Founder profile, relationships, current state, competitive landscape
- **Marketing assets**: Real bios, stats, proof points, content themes
- **Voice content**: Founder's actual voice DNA, writing samples, gotchas
- **Instance-specific skills**: Custom commands and workflows

## Directory Layout

```
instance-root/
  q-system/                    # Git subtree (skeleton)
    q-system/                  # Core OS
      agent-pipeline/
        agents/                # 50 agent prompt files
      scripts/                 # Utility scripts
      data/                    # DB init, queries
      canonical/               # Template files ({{}} placeholders)
      my-project/              # Template files ({{SETUP_NEEDED}})
      marketing/               # Template structure
    CLAUDE.md                  # Skeleton root
    kipi-mcp/                  # MCP server (validation, updates, instance management)
  instance-content/            # Project-specific (varies by instance)
    canonical/                 # Populated positioning, objections, etc.
    my-project/                # Real founder data
    marketing/assets/          # Real marketing content
  CLAUDE.md                    # Instance root (imports skeleton)
```

The exact location of instance content varies. Some instances use a dedicated directory (e.g., `q-myproject/`), others may use `instance/` or keep files at root.

## Instance Types

| Type | How skeleton arrives | How it updates |
|------|---------------------|----------------|
| subtree | `git subtree add` | `git subtree pull` or `kipi_update` MCP tool |
| direct-clone | `git clone` of kipi-system | `git pull` |

## Propagation

```
Skeleton (kipi-system)
  |
  |-- git subtree pull -->  instance-A
  |-- git subtree pull -->  instance-B
  |-- git subtree pull -->  VC_Reachout
  |-- git subtree pull -->  q-education
  |-- git pull ---------->  car-research (direct clone)
```

The `kipi_update` MCP tool automates this for all registered instances.

The `kipi_push_upstream` MCP tool pushes generic improvements from an instance back to the skeleton.

## Instance Registry

`instance-registry.json` is the single source of truth for all instances. It tracks:
- Instance name, path, subtree prefix
- Instance type (subtree or direct-clone)
- Instance-specific q-dir (where project content lives)

## Key Constraint

**Never put instance-specific content in `q-system/`.** The subtree is read-only from the instance's perspective. Changes go upstream through the `kipi_push_upstream` MCP tool, not by editing files in the subtree directly.
