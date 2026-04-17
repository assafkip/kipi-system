---
description: Triage pending findings on the active PRD
argument-hint: [finding-id disposition [rationale]]
allowed-tools: Bash
---

Set dispositions on the active PRD's findings. `/prd-approve` is blocked by the
runner's findings gate until every finding has a non-pending disposition.

Dispositions:
- `accepted` — will be fixed in this PRD. No rationale needed.
- `rejected` — will NOT be addressed. `--rationale` REQUIRED (why not).
- `deferred` — tracked but out of scope for this PRD. `--rationale` REQUIRED (where).
- `pending` — initial state; can be used to revert a premature disposition.

Do not edit the JSONL file by hand. The writer enforces the rationale rule and
stamps `resolved_at` atomically with the disposition change.

Steps:

1. Resolve the active PRD id:

```bash
PRD_ID=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/prd_runner.py" status | \
  python3 -c "import sys,json; s=json.load(sys.stdin); print(s.get('prd_id') or '')")
```

If `PRD_ID` is empty, tell the author no PRD is active and stop.

2. List pending findings:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/findings_writer.py" list "$PRD_ID" --only-pending
```

Show them to the author. For each, ask what disposition they want. Do NOT guess the author's intent; pending findings are theirs to resolve.

3. Apply each disposition:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/findings_writer.py" \
  set-disposition "$PRD_ID" <finding-id> <accepted|rejected|deferred> \
  [--rationale "<text>"]
```

4. When all findings are dispositioned, remind the author to run `/prd-approve`.
