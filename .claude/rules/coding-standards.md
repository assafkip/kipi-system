---
paths:
  - "**/*.js"
  - "**/*.py"
  - "**/*.sh"
  - "**/*.json"
  - "**/*.ts"
  - "**/*.tsx"
---

# Coding Standards

- Python: use python3, follow PEP 8
- JavaScript: ES modules, const/let (no var)
- Shell scripts: use `set -euo pipefail` at the top
- JSON: 2-space indentation
- File naming: kebab-case for output files, snake_case for scripts
- Always handle errors explicitly, never silently swallow exceptions

## Code Hygiene (IMPORTANT — apply on EVERY change)

- ALWAYS remove dead code: unused functions, unreachable branches, commented-out blocks. Never leave them "for later."
- ALWAYS remove unused imports, variables, and dependencies after every edit.
- When refactoring or removing a feature, delete ALL references: imports, route registrations, config entries, test fixtures, and the files themselves.
- Every function parameter must be used in the body. If unused, remove it or prefix with `_`.
- No placeholder classes with trivial or empty methods.
- Before finishing any task, run a quick grep for orphaned references to deleted symbols.
