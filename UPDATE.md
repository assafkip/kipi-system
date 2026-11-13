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

## Instance post-sync step

An instance may declare ONE command in `.kipi-post-sync` at its repo root (one
command line; blank lines and `#` lines are ignored). `kipi-update.sh` runs it
in the instance after the rsyncs and before it stages and commits the config
half, for an instance whose own commit-time check needs a derived artifact
refreshed first. A non-zero exit, a missing command, or a file holding zero or
more than one command line abandons that instance through the normal rollback,
prints the step's output and names the step in the summary. Other instances are
unaffected. `--dry-run` prints the command and does not run it. No file means
no change. Test: `test-kipi-update-post-sync-step.sh`.

Trust boundary:

- The step is the instance's own code, the same trust as its pre-commit hook, which already runs arbitrary instance code at that moment.
- The updater does not limit or undo what a step writes. The config commit stages only `.claude/` and `plugins/`, so a write elsewhere is not in the sync's commit.
- A failed step abandons the instance through the existing rollback, which resets the synced paths (`.claude/`, `plugins/` and the subtree prefix) to HEAD and removes files that are untracked there and absent from the run's checkpoint, so a failed step's new files under those paths go too. Writes outside those paths stay.
- The step gets 600 seconds (`KIPI_POST_SYNC_TIMEOUT`). Past that the updater kills it and abandons the instance. It kills only the step's own process, so a step must not leave a background child.
- A step must not write under `.claude/` or `plugins/`. The config commit stages tracked files there (`git add -u`), so an edit to one lands in the sync's commit as if the skeleton had shipped it. A new file there is not staged, and an instance's integrity tripwire may delete it and raise a SECURITY alert.

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

## Rolling Back a Sync

If a `kipi update` propagated a bad skeleton change, revert the last sync:

```bash
kipi rollback             # revert the last sync commit in every registered instance
kipi rollback my-instance # scope to one instance by name
```

The rollback script:
- Finds the sync commit by message (`chore: sync q-system from skeleton ...`), not by HEAD, so it reverts the right commit even when a later content commit sits on top.
- Uses `git revert` (non-destructive). It never hard-resets, and your `chore: auto-commit before kipi update` snapshot stays intact.
- Skips any instance with a dirty working tree (commit or stash first) and any instance with no sync commit.
- On a revert conflict it aborts cleanly and reports the instance as failed, leaving it untouched, so you can resolve by hand.

Instance state in `my-project/`, `canonical/`, `memory/`, and `output/` is never touched by a rollback because those dirs are excluded from the sync in the first place.

Direct-clone instances (those with `type: direct-clone` in the registry, like car-research) update via `git pull` and carry no local `chore: sync q-system from skeleton` commit, so `kipi rollback` skips them with a note. Roll those back with `git` inside the instance (e.g. `git reset` to the pre-pull ref or `git revert` the pulled range).
