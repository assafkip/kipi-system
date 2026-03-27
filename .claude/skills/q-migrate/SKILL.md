# /q-migrate — One-time migration from legacy in-repo layout to plugin directories

Migrates user data (canonical files, project data, memory, marketing config, metrics DB) from the old in-repo `q-system/` layout to the `${CLAUDE_PLUGIN_DATA}` directory with proper instance naming.

This is a one-time operation. After migration, data lives under `${CLAUDE_PLUGIN_DATA}/instances/{name}/` and the old files can be cleaned up.

## Steps

### 1. Check status

Read the `kipi://status` MCP resource.

- If `legacy_data_detected` is **false**: Tell the user "No legacy data found — nothing to migrate." and stop.
- If `legacy_data_detected` is **true**: Continue.

### 2. Instance naming

The old system had no concept of instances. Every installation now needs a unique instance name (e.g. `acme-spark7`).

Check the status response for an existing instance name:

- If an instance name is already set: Tell the user which name it is and skip to step 3.
- If no instance exists: The user needs to pick one.

Ask: "What's your company or project name?" Then:

1. Call `kipi_suggest_instance_name(company="<their answer>")` to generate a Discord-style name.
2. Show the suggestion: "Suggested instance name: **<name>**. This identifies your data across the system. You can override it if you'd like."
3. Let them confirm or provide their own.

### 3. Dry run

Call `kipi_migrate(dry_run=True, instance_name="<name>")` (omit `instance_name` if marker already exists).

Show the user what will be migrated:
- Number of files to copy
- The source and destination for each
- Any templates that will be skipped
- Whether metrics.db was found and where

Ask: "Ready to migrate? This copies files to your platform data directory — nothing is deleted from the repo."

### 4. Execute

On confirmation, call `kipi_migrate(dry_run=False, instance_name="<name>")`.

Show the result:
- Files copied (count)
- Files skipped and why
- Any errors
- The instance name that was set

### 5. Verify

Call `kipi_validate` to run the full validation suite.

Report the result. If any files are missing, tell the user which ones and suggest re-running or manual investigation.

### 6. Cleanup guidance

Tell the user:

> Migration complete. Your data now lives under `${CLAUDE_PLUGIN_DATA}/instances/{name}/`:
> - Instance dir: `{base}/instances/{name}/` (founder-profile, canonical/, marketing/, my-project/, memory/, output/, bus/, metrics.db)
> - Global dir: `{base}/global/` (voice DNA, AUDHD profile)
> - Registry: `{base}/instance-registry.json`
>
> The old files in `q-system/` are still in the repo. You can safely remove them with `git rm` when you're satisfied everything works. They won't be used anymore — the system reads from plugin paths now.

Do NOT delete anything automatically. The user decides when to clean up.
