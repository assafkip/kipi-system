---
description: Security rules for secrets, credentials, and dangerous operations
paths:
  - "**/*"
---

# Security Rules

- Never read, edit, or write `.env`, `.env.*`, or credentials files
- Never include API keys, tokens, or secrets in code output or committed files
- Never expose MCP server tokens, OAuth credentials, or API keys
- Use environment variable references (`${VAR}`) instead of hardcoded secrets
- Never run `rm -rf` on root or dot directories
- Never run untrusted scripts via `curl | bash`
- Review all MCP server interactions for data leakage before executing
