---
description: Code style and naming conventions for Python, JS, Shell, and JSON
paths:
  - "**/*.js"
  - "**/*.py"
  - "**/*.sh"
  - "**/*.json"
---

# Coding Standards

- Python: use python3, follow PEP 8
- JavaScript: ES modules, const/let (no var)
- Shell scripts: use `set -euo pipefail` at the top
- JSON: 2-space indentation
- File naming: kebab-case for output files, snake_case for scripts
- Always handle errors explicitly, never silently swallow exceptions

## Test After Edit (ENFORCED)
- After every code edit, run the relevant test, lint, or verification command before marking the edit done.
- If no test exists for the changed code, state what cannot be verified and offer to add one.
- Never report "done" without a run. Compilation is not verification. Writing is not running.
- If a run fails, do not retry the same edit. Diagnose the failure, then change the approach.
