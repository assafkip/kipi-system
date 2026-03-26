# Updating Kipi Instances

## Pull Skeleton Updates to All Instances

```bash
# From the kipi-system directory:
./kipi-update.sh

# Dry run (see what would happen without making changes):
./kipi-update.sh --dry-run
```

The script reads `instance-registry.json` and runs `git subtree pull` for each registered instance.

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

Some instances (like car-research) are direct clones of kipi-system rather than subtrees. These update with `git pull` instead of `git subtree pull`. The update script handles this automatically based on the `type` field in `instance-registry.json`.
