---
name: 03-publish-reconciliation
description: "REPLACED BY PYTHON SCRIPT. Run: python3 {{QROOT}}/.q-system/scripts/publish-reconciliation.py {date}"
model: haiku
maxTurns: 5
---

# Agent: Publish Reconciliation (DEPRECATED - Use Python Script)

This agent has been replaced by a deterministic Python script.

Run instead:
```bash
python3 q-system/.q-system/scripts/publish-reconciliation.py {date}
```

The script fuzzy-matches LinkedIn/X posts against Content Pipeline drafts using
`difflib.SequenceMatcher` and produces `bus/{date}/publish-reconciliation.json`.

This file is kept for reference only. The orchestrator calls the script directly.
