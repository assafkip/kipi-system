---
description: Create the queued Linear projects and issues that shell scripts captured offline.
allowed-tools: Bash, Read, mcp__linear__list_projects, mcp__linear__list_issues, mcp__linear__save_project, mcp__linear__save_issue
---

Drain the local Linear queue into real Linear objects.

## Why this command exists

There is no Linear API key in `~/.config/kipi/`, so a shell script (`kipi new`,
`kipi linear issue`, any build hook) cannot reach the Linear MCP server. Those
scripts capture intents into a local append-only queue instead. You are the half
that has credentials. Capture is deterministic and offline; you do the network.

## Before you create anything, read this

`mcp__linear__*delete*` and archive are blocked by
`~/.claude/hooks/destructive-op-deny.sh`, and you cannot set `ALLOW_DESTRUCTIVE=1`
for yourself. **Every object you create is permanent.** Duplicates cannot be
cleaned up, only marked `Duplicate`. So the dedup check below is not optional and
not a formality.

## Step 1 — what is pending

```bash
python3 "${CLAUDE_PROJECT_DIR}/q-system/.q-system/scripts/linear-queue.py" pending --json
```

If the list is empty, say so and stop. Do not go looking for work to do.

## Step 2 — the remote guard

For each distinct repo in the pending list, fetch what Linear already has. Never
skip this step on the grounds that the queue "looks fresh": a parallel session, a
wiped ledger, or a re-run all produce a queue that looks fresh and a Linear that
already has the object.

- `mcp__linear__list_projects` with `team: a75b9b87-bfdf-4fb7-bff3-a5a1a2a6946f`,
  to see whether the project exists.
- `mcp__linear__list_issues` with `project: <project id>` for the issues, then
  parse each description for its `<!-- kipi-key: ... -->` marker.

Write the result to a snapshot file shaped like
`{"project": {...} | null, "issues": [{"id", "identifier", "title", "description"}]}`.

## Step 3 — plan, do not improvise

```bash
python3 "${CLAUDE_PROJECT_DIR}/q-system/.q-system/scripts/linear-sync.py" plan \
  --map <capability-map.json> --remote <snapshot.json> --out <plan.json>
```

The planner applies both guards (local ledger, then the remote markers) and tells
you exactly what to create. **Create only what the plan lists.** If the plan is
empty, everything already exists; say so and stop.

For queue items that are loose issues rather than capability-map entries, the
queue's own key is already the dedup key: skip any whose key appears in the
snapshot markers or in the ledger.

## Step 4 — create

Projects: `mcp__linear__save_project` with `name`, `summary`, `description`, and
`addTeams: ["a75b9b87-bfdf-4fb7-bff3-a5a1a2a6946f"]`.

Issues: `mcp__linear__save_issue` with `team`, `project`, `title`, `description`,
`state`, `labels`. **The description must keep the `<!-- kipi-key: ... -->` marker
line verbatim** — it is what makes the next run idempotent. Dropping it is how a
future run creates a duplicate it cannot delete.

Respect the rate limit: `token-guard.py` enforces `MCP_RATE_LIMIT=30/60s`. Batch in
runs of about 20 and commit between repos.

## Step 5 — record, then mark drained

```bash
python3 "${CLAUDE_PROJECT_DIR}/q-system/.q-system/scripts/linear-sync.py" record --results <results.json>
python3 "${CLAUDE_PROJECT_DIR}/q-system/.q-system/scripts/linear-queue.py" mark-drained --key <key> --identifier <ASK-nn>
```

Record every created object before moving to the next repo. An unrecorded create
is exactly the state that produces a duplicate on the next run.

## Step 6 — report

Say what was created, what was skipped as already-existing, and what is still
pending. If anything real turned up that you are not fixing, capture it rather
than mentioning it:

```bash
python3 plugins/prd-os/scripts/prd_runner.py spillover add --source ASK-113 --desc "..."
```
