---
description: Split the approved PRD into one issue spec per manifest entry
allowed-tools: Bash
---

Materialize the PRD's `## Issues` fenced JSON manifest into issue specs under
`issues_dir`. The split script enforces:
- PRD status is `approved`.
- Every entry has non-empty `allowed_files` and non-empty `required_checks`.
  (An empty `required_checks` silently bypasses the runner's verification
  gate — the split refuses to create such specs.)
- No existing issue file is clobbered. Re-runs are idempotent only when
  byte-identical.

Two-step flow — dry-run first so the author can see planned writes before any
file lands on disk:

1. Dry-run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/prd_split.py" --dry-run
```

Read the `would_create` paths back to the author. Confirm before committing.
If they do not confirm, stop. Do NOT run step 2 without explicit agreement.

2. Commit:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/prd_split.py"
```

On collision, the script names the divergent files. Do not delete or overwrite
them. Ask the author to rename either the manifest entry or the existing file.

After a successful split, tell the author to archive or clear the PRD before
starting an issue (`prd_runner.py archive` or `prd_runner.py clear`). The
concurrency guard blocks loading an issue while a PRD context is active.
