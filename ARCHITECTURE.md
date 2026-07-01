# Kipi System Architecture

## Overview

Kipi is a portable entrepreneur operating system that runs inside Claude Code. It uses a skeleton + instance architecture where generic capabilities live in a shared skeleton and project-specific content lives in each instance.

## Design Thesis

Kipi assumes the LLM is unreliable on complex content. Every architectural choice in this repo follows from that assumption. The canonical layer exists so the model has files to cite instead of facts to invent. The `graph.jsonl` gives every claim a timestamped triple with provenance. The hooks fire deterministic checks the model can't talk its way past. The `{{UNVALIDATED}}` markers force ungrounded claims to wear a label. The `DQ-###` system keeps open questions open until evidence answers them. The sycophancy harness runs second-model verification on debriefs. Together these don't make the model accurate. They make the model's mistakes findable. Trust moves from the model to the trail. The trail is the product.

For the full mechanism see `q-system/methodology/anti-hallucination.md`.

## Skeleton (kipi-system)

The skeleton contains everything that's generic across all instances:

- **Agent pipeline**: 50 agent prompt files for the morning routine, content pipeline, engagement, lead sourcing, etc.
- **Scripts**: Audit harness, anti-AI scanner, bus verification, schedule builder, orchestrator validator
- **Canonical templates**: Empty `{{}}` placeholder files for positioning, objections, talk tracks, etc.
- **Marketing templates**: Channel structure, guardrails framework, review pipeline
- **Voice skill framework**: Layer loading matrix, anti-AI rules, quality checks (no actual voice content)
- **CLAUDE.md**: Behavioral rules, operating modes, memory architecture, setup wizard
- **Validation harness**: `validate-separation.py` verifies skeleton integrity and instance health

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
      .q-system/
        agent-pipeline/
          agents/              # 50 agent prompt files
        scripts/               # Utility scripts
        data/                  # DB init, queries
      canonical/               # Template files ({{}} placeholders)
      my-project/              # Template files ({{SETUP_NEEDED}})
      marketing/               # Template structure
    CLAUDE.md                  # Skeleton root
    validate-separation.py     # Validation harness
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
| subtree | `git subtree add` | `git subtree pull` or `kipi-update.sh` |
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

`kipi-update.sh` automates this for all registered instances.

`kipi-push-upstream.sh` pushes generic improvements from an instance back to the skeleton.

## Instance Registry

`instance-registry.json` is the single source of truth for all instances. It tracks:
- Instance name, path, subtree prefix
- Instance type (subtree or direct-clone)
- Instance-specific q-dir (where project content lives)

## Key Constraint

**Never put instance-specific content in `q-system/`.** The subtree is read-only from the instance's perspective. Changes go upstream through `kipi-push-upstream.sh`, not by editing files in the subtree directly. (Instance-specific *automation* also stays out of `q-system/` — repo-root only — because the subtree is an `rsync --delete` target. See RULE-2026-06-30-A.)

## Autonomous Systems

The fleet self-heals (launchd jobs + a watchdog + the updater's warn-and-preserve guard) and self-learns (a nightly loop that distills every instance's RCAs into fleet-wide lessons behind a fail-closed client-data gate). Full design, build story, and operate/verify commands: **[AUTONOMOUS-SYSTEMS.md](AUTONOMOUS-SYSTEMS.md)**. The decisions behind it are logged as RULE-2026-06-30-A..E in `q-system/canonical/decisions.md`.
