---
name: 05-temperature-scoring
description: "REPLACED BY PYTHON SCRIPT. Run: python3 {{QROOT}}/.q-system/scripts/temperature-scoring.py {date}"
model: haiku
maxTurns: 5
---

# Agent: Temperature Scoring (DEPRECATED - Use Python Script)

This agent has been replaced by a deterministic Python script.

Run instead:
```bash
python3 q-system/.q-system/scripts/temperature-scoring.py {date}
```

The script reads DM/post/email/Notion bus files, applies weighted signal scoring
(DM reply +3, email reply +3, comment +2, etc.), and produces `bus/{date}/temperature.json`.

Signal weights and cadence config thresholds are parsed from `_cadence-config.md`.

This file is kept for reference only. The orchestrator calls the script directly.
