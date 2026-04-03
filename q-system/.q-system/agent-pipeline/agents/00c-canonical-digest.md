---
name: 00c-canonical-digest
description: "REPLACED BY PYTHON SCRIPT. Run: python3 {{QROOT}}/.q-system/scripts/canonical-digest.py {date}"
model: haiku
maxTurns: 5
---

# Agent: Canonical Digest (DEPRECATED - Use Python Script)

This agent has been replaced by a deterministic Python script.

Run instead:
```bash
python3 q-system/.q-system/scripts/canonical-digest.py {date}
```

The script reads all canonical files, parses them with regex, and produces
`bus/{date}/canonical-digest.json` with the same schema as this agent.

This file is kept for reference only. The orchestrator calls the script directly.
