---
name: 06-compliance-check
description: "REPLACED BY PYTHON SCRIPT. Run: python3 {{QROOT}}/.q-system/scripts/compliance-check.py {date}"
model: haiku
maxTurns: 5
---

# Agent: Compliance Check (DEPRECATED - Use Python Script)

This agent has been replaced by a deterministic Python script.

Run instead:
```bash
python3 q-system/.q-system/scripts/compliance-check.py {date}
```

The script checks all generated content against:
- Misclassification: "What We Are NOT" list from current-state.md
- Overclaiming: claims vs works_today capabilities
- Voice: banned words (reuses scan-draft.py lists), emdashes, hedging density
- Platform rules: Reddit URL requirement

Also tracks recurring violations across last 5 days and recommends promotion to auto-fail.

Exit 0 = pass, Exit 1 = auto-fail violations found.

This file is kept for reference only. The orchestrator calls the script directly.
