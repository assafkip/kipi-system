# Contributing Back to the Skeleton

## Push Generic Improvements Upstream

If you make a generic improvement in an instance (new agent, script fix, template enhancement) that would benefit all instances:

```bash
cd /path/to/my-instance
/path/to/kipi-system/kipi-push-upstream.sh
```

The script:
1. Checks for instance-specific content in the subtree (blocks if found)
2. Pushes the subtree changes to the kipi-system remote

## Safety Rules

- Never put instance-specific content in `q-system/` (canonical files, my-project data, voice samples)
- The push script checks for common leaks (company names, personal info, hardcoded paths)
- If the safety check fails, clean the instance content out first

## Workflow

1. Make the improvement in your instance's `q-system/` directory
2. Test it works
3. Run `kipi-push-upstream.sh` to push to skeleton
4. Run `kipi-update.sh` to propagate to other instances

## What Belongs in the Skeleton

- Agent prompt files (generic pipeline logic, no domain-specific rules)
- Scripts (audit, verification, build tools)
- Canonical templates (empty `{{}}` placeholders, not populated content)
- Marketing templates (structure, not content)
- Voice skill framework (not voice DNA or writing samples)
- CLAUDE.md behavioral rules (not instance identity)

## What Stays in the Instance

- Populated canonical files (talk tracks, objections, positioning)
- my-project/ data (founder profile, relationships, current state)
- Marketing assets (bios, stats, proof points)
- Voice DNA and writing samples
- Instance-specific skills and commands
