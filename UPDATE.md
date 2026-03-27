# Updating Kipi Instances

## Pull Skeleton Updates to All Instances

Use the `kipi_update` MCP tool, which reads `instance-registry.json` and runs `git subtree pull` for each registered instance. Pass `dry_run=true` to preview changes without applying them.

## Update a Single Instance

```bash
cd /path/to/my-instance
git subtree pull --prefix=q-system https://github.com/assafkip/kipi-system.git main --squash
```

## When to Update

Run after meaningful skeleton improvements (new agents, script fixes, template updates). Not after every commit.

## Handling Conflicts

If a subtree pull has conflicts:
1. Resolve conflicts in the affected files
2. `git add` the resolved files
3. `git commit`

Instance content outside `q-system/` will never conflict. Only modify skeleton files through the upstream repo, not directly in instances.

## Direct-Clone Instances

Some instances (like car-research) are direct clones of kipi-system rather than subtrees. These update with `git pull` instead of `git subtree pull`. The `kipi_update` MCP tool handles this automatically based on the `type` field in `instance-registry.json`.
