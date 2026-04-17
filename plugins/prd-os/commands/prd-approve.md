---
description: Advance the active PRD to `approved` (blocked by pending findings)
allowed-tools: Bash
---

Approve the active PRD. The runner's findings gate blocks approval when any
finding is still `pending` or the findings JSONL contains an invalid line.

Do not bypass by editing the findings file. If the gate blocks, run
`/prd-triage` to set dispositions, then retry this command.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/prd_runner.py" advance approved
```

On success, tell the author the next step is `/prd-split` to materialize the
PRD's issue manifest into one issue spec per entry.

On block, surface stderr verbatim. The runner names the offending finding ids.
