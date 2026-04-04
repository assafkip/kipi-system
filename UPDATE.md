# Updating Kipi Instances

## Full Lifecycle

```
Skeleton change -> validate -> commit -> push -> propagate -> verify
```

### 1. Make changes in kipi-system

```bash
cd ~/Desktop/kipi-system
# edit files...
```

### 2. Pre-commit validates automatically

The `.githooks/pre-commit` hook runs phases 0-1 on every commit. If it fails, the commit is blocked.

### 3. Pre-push validates fully

The `.githooks/pre-push` hook runs phases 0-5 before any push. All instances are checked.

### 4. Push to remote

```bash
git push origin main
```

GitHub Actions runs Phase 1 validation on the remote.

### 5. Preview changes for instances

```bash
kipi update --dry
```

Shows skeleton HEAD vs each instance's last sync, and commits behind for direct clones.

### 6. Propagate to all instances

```bash
kipi update
```

The script:
- Reads `instance-registry.json` for all registered instances
- Auto-stashes dirty working trees
- Runs `git subtree pull` (subtree instances) or `git pull` (direct clones)
- Syncs `.claude/` config: settings, agents, rules, output styles, plugins
- Restores stash after update

### 7. Verify

```bash
kipi check
```

## Settings Merge Logic

During `kipi update`, `settings.json` is rebuilt from `settings-template.json` with these preservation rules:

| Section | Behavior |
|---------|----------|
| `hooks` | Template wins (new hooks propagate) |
| `permissions.allow` | Union merge (instance additions kept) |
| `permissions.deny` | Template wins (security rules propagate) |
| `mcpServers` | Instance wins (all servers preserved, including disabled) |
| `enabledPlugins` | Union merge (instance additions kept) |
| `toolConfigurations` | Instance wins (custom configs preserved) |
| `model` | Instance wins if different from template |
| `outputStyle`, `effortLevel` | Template wins |

After sync, subtree instances get path fixups (`/q-system/hooks/` -> `/q-system/q-system/hooks/`).

## Pushing Changes Back from an Instance

If you improve an agent, script, or template inside an instance's `q-system/`:

```bash
cd /path/to/my-instance
kipi push
```

The push script:
1. Checks for instance-specific content leaks (company names, personal info, hardcoded paths)
2. Blocks if leaks found
3. Pushes subtree changes to the skeleton remote
4. You then run `kipi update` to propagate to other instances

## Propagation Checklist

Use after any significant skeleton change:

- [ ] `kipi check` passes (phases 0-5 GREEN)
- [ ] `git push origin main` succeeds (CI passes)
- [ ] `kipi update --dry` shows expected instances
- [ ] `kipi update` completes without failures
- [ ] Spot-check 1 instance: open in Claude Code, verify `/q-morning` boots
- [ ] If settings changed: verify `.claude/settings.json` in an instance has correct merge

## Handling Conflicts

If a subtree pull has conflicts:
1. Resolve conflicts in the affected files
2. `git add` the resolved files
3. `git commit`

Instance content outside `q-system/` never conflicts. Only modify skeleton files through the upstream repo, not directly in instances.

## Direct-Clone Instances

Some instances (like car-research) are direct clones of kipi-system rather than subtrees. These update with `git pull` instead of `git subtree pull`. The update script handles this automatically based on the `type` field in `instance-registry.json`.

## Update a Single Instance

```bash
cd /path/to/my-instance
git subtree pull --prefix=q-system https://github.com/assafkip/kipi-system.git main --squash
```
