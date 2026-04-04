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
